#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: facility_agent.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/6
描述: 校园设施查询 A2A Agent 服务器 —— 校园活动/新闻/餐厅/图书馆开放时间（端口 5006）

v3.4 Tier 1 升级:
  - MCP stateless Client (无需 initialize 握手)
  - 动态获取 table schema (不再硬编码四张表结构)
  - MCP URL 通过环境变量配置
"""
import json
import asyncio
import time

from mcp import Client
from python_a2a import A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from datetime import datetime
import pytz

from app.config import Config
from app.logging import logger
from app.llm import create_llm
from app.observability import (
    span, set_trace_id, get_trace_id,
    agent_llm_calls_total, agent_llm_duration_seconds,
    mcp_tool_calls_total, mcp_tool_call_duration_seconds,
)

conf = Config()

# ============ MCP Stateless Client URL ============
MCP_FACILITY_URL = conf.mcp_facility_url

# ============ LLM ============
llm = create_llm()

# ============ 动态 Schema ============
_schema_cache = {"text": "", "fetched_at": 0}
_SCHEMA_TTL = 3600


async def _fetch_schema_async():
    """从 MCP Server 获取全部设施表结构"""
    trace_id = get_trace_id()
    async with Client(MCP_FACILITY_URL) as client:
        result = await client.call_tool(
            "get_facility_schema", {},
            meta={"trace_id": trace_id} if trace_id else None,
        )
        return result.content[0].text


def _get_table_schema() -> str:
    """获取设施表结构（带缓存），转为 SQL CREATE TABLE 格式"""
    global _schema_cache
    now = time.time()
    if _schema_cache["text"] and (now - _schema_cache["fetched_at"]) < _SCHEMA_TTL:
        return _schema_cache["text"]

    try:
        raw = asyncio.run(_fetch_schema_async())
        schema_data = json.loads(raw)
        if schema_data.get("status") == "success":
            schemas = schema_data.get("schemas", {})
            parts = []
            for table_name, info in schemas.items():
                columns = info.get("columns", [])
                lines = [f"CREATE TABLE {table_name} ("]
                for col in columns:
                    field = col.get("Field", "")
                    col_type = col.get("Type", "")
                    null = "NULL" if col.get("Null", "YES") == "YES" else "NOT NULL"
                    default = col.get("Default")
                    comment = col.get("Comment", "")
                    line_parts = [f"  {field} {col_type} {null}"]
                    if default is not None:
                        line_parts.append(f"DEFAULT {default}")
                    if comment:
                        line_parts.append(f"COMMENT '{comment}'")
                    lines.append("    ".join(line_parts) + ",")
                indexes = info.get("indexes", [])
                seen_keys = set()
                for idx in indexes:
                    key_name = idx.get("Key_name", "")
                    if key_name == "PRIMARY" or key_name in seen_keys:
                        continue
                    seen_keys.add(key_name)
                    col_name = idx.get("Column_name", "")
                    lines.append(f"  UNIQUE KEY {key_name} ({col_name}),")
                lines.append(") ENGINE=INNODB DEFAULT CHARSET=utf8mb4;")
                parts.append("\n".join(lines))
            text = "\n\n".join(parts)
            _schema_cache["text"] = text
            _schema_cache["fetched_at"] = now
            logger.info(f"[Schema] 设施表结构已刷新 ({len(schemas)} 张表)")
            return text
    except Exception as e:
        logger.warning(f"[Schema] 获取设施表结构失败: {e}，使用缓存")
        if _schema_cache["text"]:
            return _schema_cache["text"]
        raise

    return _schema_cache["text"]


# ============ SQL 生成 Prompt ============
sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是一个专业的CUHK校园信息SQL生成器，需要从对话历史（含用户的问题）中提取用户的意图以及关键信息，然后基于 campus_events、campus_news、canteen、library_hours 表生成SELECT语句。
根据对话历史：
1. 提取用户的意图，意图有4种（campus_event: 校园活动, campus_news: 校园新闻, canteen: 餐厅, library_hours: 图书馆开放时间），输出：{{"type": "campus_event/campus_news/canteen/library_hours"}}；如果无法识别意图，或者意图不在这4种内，则模仿最后1个示例回复即可。
2. 根据用户的意图，生成对应表的 SELECT 语句，仅查询指定字段：
- campus_events: id, event_name, organizer, venue, start_time, end_time, category, total_capacity, registered, description
- campus_news: id, title, source, category, publish_date, summary, url
- canteen: id, name, location, opening_hours, phone, category, status
- library_hours: id, library_name, area, day_of_week, date, open_time, close_time, is_closed
3. 重要：始终生成默认SQL，只有用户意图完全无法识别（如"你好""谢谢"）时才退回 input_required。即使模糊查询也要生成SQL。
4. 按要求输出两行数据即可，不需要输出其他内容。

中文地名 → 英文关键词映射（用于 SQL LIKE）：
  崇基/崇基学院=Chung Chi, 新亚/新亚书院=New Asia, 联合/联合书院=United College,
  善衡=S.H. Ho, 逸夫/逸夫书院=Shaw, 伍宜孙=Wu Yee Sun, 晨兴=Morningside,
  和声=Lee Woo Sing, 敬文=C.W. Chu, 大学图书馆=University Library,
  法律图书馆=Law Library, 医学图书馆=Medical Library, 建筑学图书馆=Architecture Library

默认查询策略（无明确条件时直接用）：
- campus_event: ORDER BY start_time DESC LIMIT 10（最近的10个活动）
- campus_news:  ORDER BY publish_date DESC LIMIT 10（最近的10条新闻）
- canteen:      WHERE status = 'Open'（全部营业中餐厅）
- library_hours:根据当前日期计算星期几（周一=Mon,...周日=Sun），用 day_of_week 过滤；无条件则查全部

示例：
- 对话: user: 最近有什么校园活动 讲座
输出:
{{"type": "campus_event"}}
SELECT id, event_name, organizer, venue, start_time, end_time, category, total_capacity, registered, description FROM campus_events WHERE category = 'Talk' AND start_time >= '2026-08-10'

- 对话: user: 最近有什么活动
输出:
{{"type": "campus_event"}}
SELECT id, event_name, organizer, venue, start_time, end_time, category, total_capacity, registered, description FROM campus_events ORDER BY start_time DESC LIMIT 10

- 对话: user: 最近有什么新闻
输出:
{{"type": "campus_news"}}
SELECT id, title, source, category, publish_date, summary, url FROM campus_news ORDER BY publish_date DESC LIMIT 10

- 对话: user: 有什么餐厅
输出:
{{"type": "canteen"}}
SELECT id, name, location, opening_hours, phone, category, status FROM canteen WHERE status = 'Open'

- 对话: user: 崇基学院有什么餐厅
输出:
{{"type": "canteen"}}
SELECT id, name, location, opening_hours, phone, category, status FROM canteen WHERE (location LIKE '%Chung Chi%' OR name LIKE '%Chung Chi%') AND status = 'Open'

- 对话: user: 大学图书馆今天开门吗（当前日期 2026-08-10 是 Monday → Mon）
输出:
{{"type": "library_hours"}}
SELECT id, library_name, area, day_of_week, date, open_time, close_time, is_closed FROM library_hours WHERE library_name LIKE '%University Library%' AND day_of_week = 'Mon' AND is_closed = 0

- 对话: user: 大学图书馆几点开门
输出:
{{"type": "library_hours"}}
SELECT id, library_name, area, day_of_week, date, open_time, close_time, is_closed FROM library_hours WHERE library_name LIKE '%University Library%'

- 对话: user: 你好
输出:
{{"status": "input_required", "message": "请提供校园信息查询类型（校园活动/新闻/餐厅/图书馆开放时间）和必要信息。"}}

表结构：{table_schema_string}
对话历史: {conversation}
当前日期: {current_date} (Asia/Shanghai)
    """
)


# ============ MCP 工具调用 ============
def _call_mcp_sync(tool_name: str, args: dict) -> str:
    """同步封装：通过 stateless MCP Client 调用工具
    每次调用创建独立的 Client（stateless HTTP — 无 session 无 initialize）
    通过 _meta 字段传递 trace_id，实现跨进程链路关联"""
    trace_id = get_trace_id()

    async def _call():
        async with Client(MCP_FACILITY_URL) as client:
            result = await client.call_tool(
                tool_name, args,
                meta={"trace_id": trace_id} if trace_id else None,
            )
            return result.content[0].text

    return asyncio.run(_call())


# ============ Agent 卡片 ============
agent_card = AgentCard(
    name="FacilityQueryAssistant",
    description="基于 LangChain 提供CUHK校园信息查询服务的助手，使用 MCP stateless 协议动态获取表结构",
    url="http://localhost:5006",
    version="2.1.0",
    capabilities={"streaming": True, "memory": True},
    skills=[
        AgentSkill(
            name="execute campus query",
            description="根据客户端提供的输入执行校园信息查询，返回数据库结果，支持自然语言输入",
            examples=["最近有什么讲座", "校园新闻", "崇基学院餐厅", "大学图书馆开放时间"]
        )
    ]
)


# ============ A2A Server ============
class FacilityQueryServer(A2AServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)
        self.llm = llm
        self.sql_prompt = sql_prompt

    def _get_schema(self) -> str:
        """获取当前表结构文本（带缓存，首次调用时从 MCP 拉取）"""
        try:
            return _get_table_schema()
        except Exception as e:
            logger.error(f"无法获取表结构: {e}")
            return "campus_events, campus_news, canteen, library_hours 表"

    def generate_sql_query(self, conversation: str) -> dict:
        try:
            schema = self._get_schema()
            chain = self.sql_prompt | self.llm
            current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
            output = chain.invoke({
                "conversation": conversation,
                "current_date": current_date,
                "table_schema_string": schema,
            }).content.strip()
            logger.info(f"原始 LLM 输出: {output}")

            # 解析两行输出: 第一行是 type JSON, 第二行是 SQL
            lines = output.split('\n')
            type_line = lines[0].strip()
            if type_line.startswith('```json'):
                type_line = lines[1].strip()
                sql_lines = lines[3:-1] if lines[-1].strip() == '```' else lines[3:]
            else:
                sql_lines = lines[1:] if len(lines) > 1 else []

            if type_line.startswith('{"type":'):
                query_type = json.loads(type_line)["type"]
                sql_query = ' '.join([
                    line.strip() for line in sql_lines
                    if line.strip() and not line.startswith('```')
                ])
                logger.info(f"分类类型: {query_type}, 生成的 SQL: {sql_query}")
                return {"status": "sql", "type": query_type, "sql": sql_query}
            elif type_line.startswith('{"status": "input_required"'):
                return json.loads(type_line)
            else:
                logger.error(f"无效的 LLM 输出格式: {output}")
                return {"status": "input_required", "message": "无法解析查询类型或SQL，请提供更明确的信息。"}
        except Exception as e:
            logger.error(f"SQL 生成失败: {str(e)}")
            return {"status": "input_required", "message": "查询无效，请提供查询校园信息的相关信息。"}

    def handle_task(self, task):
        # 从 A2A 消息中提取 trace_id，实现跨进程链路关联
        trace_id = (task.message or {}).get("_trace_id", "")
        if trace_id:
            set_trace_id(trace_id)

        content = (task.message or {}).get("content", {})
        conversation = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"对话历史及用户问题: {conversation}")

        with span("agent_handle_task", {"agent": "FacilityQueryAssistant"}):
            try:
                # 1. 生成 SQL
                llm_start = time.perf_counter()
                llm_status = "ok"
                gen_result = self.generate_sql_query(conversation)
                agent_llm_duration_seconds.labels(agent_name="FacilityQueryAssistant").observe(
                    time.perf_counter() - llm_start
                )

                if gen_result["status"] == "input_required":
                    agent_llm_calls_total.labels(agent_name="FacilityQueryAssistant", status="input_required").inc()
                    task.status = TaskStatus(
                        state=TaskState.INPUT_REQUIRED,
                        message={"role": "agent", "content": {"text": gen_result["message"]}},
                    )
                    return task

                agent_llm_calls_total.labels(agent_name="FacilityQueryAssistant", status="sql_generated").inc()
                sql_query = gen_result["sql"]
                query_type = gen_result["type"]
                logger.info(f"执行 SQL 查询: {sql_query} (类型: {query_type})")

                # 2. 通过 stateless MCP Client 执行查询 (传递 trace_id)
                mcp_start = time.perf_counter()
                mcp_status = "ok"
                try:
                    facility_result = _call_mcp_sync(
                        "query_facilities", {"sql": sql_query}
                    )
                    mcp_tool_call_duration_seconds.labels(
                        server="facility", tool="query_facilities"
                    ).observe(time.perf_counter() - mcp_start)
                except Exception:
                    mcp_status = "error"
                    mcp_tool_call_duration_seconds.labels(
                        server="facility", tool="query_facilities"
                    ).observe(time.perf_counter() - mcp_start)
                    raise
                finally:
                    mcp_tool_calls_total.labels(
                        server="facility", tool="query_facilities", status=mcp_status
                    ).inc()

                # 3. 格式化结果
                response = json.loads(facility_result) if isinstance(facility_result, str) else facility_result
                logger.info(f"MCP 返回: {response}")
                if response.get("status") == "success":
                    data = response.get("data", [])
                    response_text = ""
                    for d in data:
                        if query_type == "campus_event":
                            response_text += (
                                f"{d['start_time']} | {d['event_name']} | {d['organizer']} | "
                                f"{d['venue']} | {d['category']} | "
                                f"已报名:{d['registered']}/{d['total_capacity']}\n"
                            )
                        elif query_type == "campus_news":
                            response_text += (
                                f"[{d['publish_date']}] {d['title']} | 来源:{d['source']} | "
                                f"类别:{d['category']}\n摘要: {d.get('summary', '')}\n"
                                f"链接: {d.get('url', '')}\n\n"
                            )
                        elif query_type == "canteen":
                            response_text += (
                                f"{d['name']} | {d['location']} | {d['category']} | "
                                f"营业时间: {d.get('opening_hours', '请参考店内')} | "
                                f"状态: {d['status']}\n"
                            )
                        elif query_type == "library_hours":
                            if d.get('is_closed'):
                                response_text += (
                                    f"{d['library_name']} {d['area']} | "
                                    f"{d['day_of_week']} ({d.get('date', '')}) | 闭馆\n"
                                )
                            elif d.get('open_time') == '24hrs':
                                response_text += (
                                    f"{d['library_name']} {d['area']} | "
                                    f"{d['day_of_week']} ({d.get('date', '')}) | 24小时开放\n"
                                )
                            else:
                                response_text += (
                                    f"{d['library_name']} {d['area']} | "
                                    f"{d['day_of_week']} ({d.get('date', '')}) | "
                                    f"{d.get('open_time', '')} - {d.get('close_time', '')}\n"
                                )
                    if not response_text:
                        response_text = "无结果。如需其他条件，请补充。"

                    task.artifacts = [{"parts": [{"type": "text", "text": response_text}]}]
                    task.status = TaskStatus(state=TaskState.COMPLETED)
                elif response.get("status") == "no_data":
                    response_text = response.get("message", "请提供更详细的查询条件。")
                    task.status = TaskStatus(
                        state=TaskState.INPUT_REQUIRED,
                        message={"role": "agent", "content": {"text": response_text}},
                    )
                else:
                    response_text = response.get("message", "查询失败，请重试或提供更多细节。")
                    task.status = TaskStatus(
                        state=TaskState.FAILED,
                        message={"role": "agent", "content": {"text": response_text}},
                    )
                return task
            except Exception as e:
                logger.error(f"查询失败: {str(e)}")
                task.status = TaskStatus(
                    state=TaskState.FAILED,
                    message={"role": "agent", "content": {"text": f"查询失败: {str(e)} 请重试或提供更多细节。"}},
                )
                return task


if __name__ == "__main__":
    facility_server = FacilityQueryServer()
    print("\n=== 服务器信息 ===")
    print(f"名称: {facility_server.agent_card.name}")
    print(f"描述: {facility_server.agent_card.description}")
    print(f"MCP URL: {conf.mcp_facility_url}")
    print("\n技能:")
    for skill in facility_server.agent_card.skills:
        print(f"- {skill.name}: {skill.description}")
    run_server(facility_server, host="127.0.0.1", port=5006)
