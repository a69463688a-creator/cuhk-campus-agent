#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: transport_agent.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/9/17
描述: 校园交通查询 A2A Agent 服务器（端口 5008）

与 course/facility（纯 SQL 检索型）不同，本 Agent 区分两类意图：
  - route     （路线规划）：调用 MCP find_route 图搜索（判断逻辑）
  - timetable（时刻表查询）：生成 SQL + Python 频次推算「下一班车」
"""
import json
import asyncio
import functools
import re
import time

from mcp import Client
from python_a2a import A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState
from langchain_core.prompts import ChatPromptTemplate
from datetime import datetime
import pytz

from app.config import Config
from app.logging import logger
from app.llm import create_llm
from app.progress import progress_store, register_progress_endpoint, STAGE_INTENT, STAGE_QUERY
from app.observability import (
    span, set_trace_id, get_trace_id,
    agent_llm_calls_total, agent_llm_duration_seconds,
    mcp_tool_calls_total, mcp_tool_call_duration_seconds,
)
from data.transport import compute_next_departure

conf = Config()

# ============ MCP Stateless Client URL ============
MCP_TRANSPORT_URL = conf.mcp_transport_url

# ============ LLM ============
llm = create_llm()

# ============ 动态 Schema ============
_schema_cache = {"text": "", "fetched_at": 0}
_SCHEMA_TTL = 3600


async def _fetch_schema_async():
    """从 MCP Server 获取全部交通表结构"""
    trace_id = get_trace_id()
    async with Client(MCP_TRANSPORT_URL) as client:
        result = await client.call_tool(
            "get_transport_schema", {},
            meta={"trace_id": trace_id} if trace_id else None,
        )
        return result.content[0].text


def _get_table_schema() -> str:
    """获取交通表结构（带缓存），转为 SQL CREATE TABLE 格式"""
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
            logger.info(f"[Schema] 交通表结构已刷新 ({len(schemas)} 张表)")
            return text
    except Exception as e:
        logger.warning(f"[Schema] 获取交通表结构失败: {e}，使用缓存")
        if _schema_cache["text"]:
            return _schema_cache["text"]
        raise

    return _schema_cache["text"]


# ============ 意图解析 Prompt ============
transport_prompt = ChatPromptTemplate.from_template(
"""
系统提示：你是一个专业的CUHK校巴查询助手，需要从对话历史（含用户问题）中提取意图与关键信息，基于 bus_routes、bus_stops 表。

意图有 2 种：
1. route：用户要「从 A 到 B 坐几号校巴 / 怎么去」，需要起点站与终点站。输出：{{"type": "route", "origin": "起点站", "destination": "终点站"}}
2. timetable：用户要查某条路线班次/末班车/下一班，或查询有哪些路线。输出：{{"type": "timetable"}} 换行后跟一条 SELECT 语句（只查询指定字段）。

规则：
- 重要：始终生成默认结果，只有意图完全无法识别（如"你好""谢谢"）时才退回 input_required。
- bus_routes 字段：route_code, route_name, start_stop, end_stop, service_type, first_bus_time, last_bus_time, frequency_min, note
- bus_stops 字段：route_code, stop_order, stop_name, stop_name_en
- 中文地名 → 英文关键词映射（用于 SQL LIKE）：
  大学站=University Station, 本部=Central Campus, 崇基=Chung Chi,
  新亚=New Asia, 联合=United, 逸夫=Shaw

示例：
- 对话: user: 从大学站到逸夫书院坐几号校巴
输出:
{{"type": "route", "origin": "大學站", "destination": "逸夫書院"}}
- 对话: user: 3号线下一班几点
输出:
{{"type": "timetable"}}
SELECT route_code, route_name, first_bus_time, last_bus_time, frequency_min FROM bus_routes WHERE route_code = '3'
- 对话: user: N线末班车几点
输出:
{{"type": "timetable"}}
SELECT route_code, route_name, first_bus_time, last_bus_time, frequency_min FROM bus_routes WHERE route_code = 'N'
- 对话: user: 校巴有哪些路线
输出:
{{"type": "timetable"}}
SELECT route_code, route_name, start_stop, end_stop, service_type, first_bus_time, last_bus_time, frequency_min FROM bus_routes
- 对话: user: 你好
输出:
{{"status": "input_required", "message": "请提供校巴查询：例如「从大学站到逸夫书院」或「3号线末班车」。"}}

表结构：{table_schema_string}
对话历史: {conversation}
当前日期: {current_date} (Asia/Shanghai)
    """
)


_ROUTE_CODE_RE = re.compile(r'(?<![A-Za-z0-9])([A-Z0-9]{1,3}号?线)')
_TIMETABLE_KW = re.compile(r'班次|末班|首班|下一班|几点|发车|时刻|频率')
_ROUTE_PLANNING_KW = re.compile(r'从|怎么去|坐几号')


def _extract_timetable_route_code(conversation: str) -> str | None:
    """仅当明确为时刻表查询（单一路线号 + 班次关键词、且非路线规划）时返回路线号 token。"""
    if _ROUTE_PLANNING_KW.search(conversation):
        return None
    if not _TIMETABLE_KW.search(conversation):
        return None
    tokens = sorted(set(_ROUTE_CODE_RE.findall(conversation)))
    return tokens[0] if len(tokens) == 1 else None


@functools.lru_cache(maxsize=256)
def _transport_llm_by_code(schema_text: str, route_token: str, current_date: str) -> str:
    """按路线号生成时刻表 SQL（确定性，进程内缓存）。键=路线号 token，跨表述复用。"""
    chain = transport_prompt | llm
    return chain.invoke({
        "conversation": f"user: {route_token}下一班几点",
        "current_date": current_date,
        "table_schema_string": schema_text,
    }).content.strip()


@functools.lru_cache(maxsize=256)
def _transport_llm_raw(schema_text: str, conversation: str, current_date: str) -> str:
    """无法归一化（路线规划 / 无路线号）时的完整对话意图解析（命中率低，但保证正确）。"""
    chain = transport_prompt | llm
    return chain.invoke({
        "conversation": conversation,
        "current_date": current_date,
        "table_schema_string": schema_text,
    }).content.strip()


# ============ MCP 工具调用 ============
def _call_mcp_sync(tool_name: str, args: dict) -> str:
    """同步封装：通过 stateless MCP Client 调用工具，经 _meta 传递 trace_id"""
    trace_id = get_trace_id()

    async def _call():
        async with Client(MCP_TRANSPORT_URL) as client:
            result = await client.call_tool(
                tool_name, args,
                meta={"trace_id": trace_id} if trace_id else None,
            )
            return result.content[0].text

    return asyncio.run(_call())


# ============ Agent 卡片 ============
agent_card = AgentCard(
    name="TransportQueryAssistant",
    description="基于图搜索与时刻表提供CUHK校巴查询的助手，支持路线规划与班次推算",
    url="http://localhost:5008",
    version="1.0.0",
    capabilities={"streaming": True, "memory": False},
    skills=[
        AgentSkill(
            name="plan campus route",
            description="规划从起点站到终点站的校巴路线（最少换乘、其次最少站数），并推算下一班/末班车",
            examples=["从大学站到逸夫书院坐几号校巴", "3号线下一班几点", "N线末班车几点"]
        )
    ]
)


# ============ A2A Server ============
class TransportQueryServer(A2AServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)
        self.llm = llm
        self.transport_prompt = transport_prompt

    def setup_routes(self, app):
        """注册自定义进度端点（在库默认路由之上）。"""
        super().setup_routes(app)
        register_progress_endpoint(app, self)

    def _get_schema(self) -> str:
        try:
            return _get_table_schema()
        except Exception as e:
            logger.error(f"无法获取表结构: {e}")
            return "bus_routes, bus_stops 表"

    def generate(self, conversation: str) -> dict:
        """LLM 解析意图：route / timetable(+SQL) / input_required"""
        try:
            schema = self._get_schema()
            current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
            route_token = _extract_timetable_route_code(conversation)
            output = (
                _transport_llm_by_code(schema, route_token, current_date)
                if route_token else _transport_llm_raw(schema, conversation, current_date)
            )
            logger.info(f"原始 LLM 输出: {output}")

            lines = output.split('\n')
            type_line = lines[0].strip()
            if type_line.startswith('```json'):
                type_line = lines[1].strip()
                sql_lines = lines[3:-1] if lines[-1].strip() == '```' else lines[3:]
            else:
                sql_lines = lines[1:] if len(lines) > 1 else []

            if type_line.startswith('{"type": "route"'):
                info = json.loads(type_line)
                return {"status": "route", "origin": info.get("origin", ""), "destination": info.get("destination", "")}
            elif type_line.startswith('{"type": "timetable"'):
                sql_query = ' '.join([
                    line.strip() for line in sql_lines
                    if line.strip() and not line.startswith('```')
                ])
                return {"status": "timetable", "sql": sql_query}
            elif type_line.startswith('{"status": "input_required"'):
                return json.loads(type_line)
            else:
                logger.error(f"无效的 LLM 输出格式: {output}")
                return {"status": "input_required", "message": "无法解析查询类型，请提供更明确的校巴查询。"}
        except Exception as e:
            logger.error(f"解析失败: {str(e)}")
            return {"status": "input_required", "message": "查询无效，请提供起点站/终点站或路线编号。"}

    def _format_route(self, raw: str) -> str:
        """格式化 find_route 结果"""
        resp = json.loads(raw) if isinstance(raw, str) else raw
        if resp.get("status") != "success":
            return resp.get("message", "未找到可通行的路线。")
        data = resp["data"]
        lines = []
        for seg in data["itinerary"]:
            lines.append(f"{seg['route_code']}号线：{seg['board_stop']} → {seg['alight_stop']}（{seg['n_stops']}站）")
        if data["transfers"] > 0:
            lines.append(f"需换乘 {data['transfers']} 次")
        lines.append(f"全程 {data['total_stops']} 站")
        return "\n".join(lines)

    def _format_timetable(self, raw: str) -> str:
        """格式化时刻表结果，若为单条路线则推算下一班车"""
        resp = json.loads(raw) if isinstance(raw, str) else raw
        if resp.get("status") != "success":
            return resp.get("message", "未找到相关数据。")
        data = resp.get("data", [])
        now = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%H:%M')
        lines = []
        for d in data:
            line = (f"{d.get('route_code', '')} {d.get('route_name', '')} | "
                    f"{d.get('start_stop', '')} ↔ {d.get('end_stop', '')} | "
                    f"{d.get('service_type', '')} | "
                    f"{d.get('first_bus_time', '')}-{d.get('last_bus_time', '')} | "
                    f"约每{d.get('frequency_min', '')}分钟一班")
            lines.append(line)
        # 单条路线且有频次信息 → 推算下一班
        if len(data) == 1 and data[0].get("frequency_min"):
            d = data[0]
            nxt = compute_next_departure(
                d.get("first_bus_time"), d.get("last_bus_time"),
                d.get("frequency_min"), now
            )
            if nxt:
                lines.append(f"当前 {now}，下一班约 {nxt}（首班 {d.get('first_bus_time')}）")
            else:
                lines.append(f"当前 {now}，已过末班车（末班 {d.get('last_bus_time')}）")
        return "\n".join(lines)

    def handle_task(self, task):
        # 从 A2A 消息中提取 trace_id，实现跨进程链路关联
        trace_id = (task.message or {}).get("_trace_id", "")
        if trace_id:
            set_trace_id(trace_id)

        content = (task.message or {}).get("content", {})
        conversation = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"对话历史及用户问题: {conversation}")

        with span("agent_handle_task", {"agent": "TransportQueryAssistant"}):
            try:
                progress_store.record(trace_id, STAGE_INTENT, "正在解析校巴查询意图…")
                llm_start = time.perf_counter()
                gen_result = self.generate(conversation)
                agent_llm_duration_seconds.labels(agent_name="TransportQueryAssistant").observe(
                    time.perf_counter() - llm_start
                )

                if gen_result["status"] == "input_required":
                    agent_llm_calls_total.labels(agent_name="TransportQueryAssistant", status="input_required").inc()
                    task.status = TaskStatus(
                        state=TaskState.INPUT_REQUIRED,
                        message={"role": "agent", "content": {"text": gen_result["message"]}},
                    )
                    return task

                agent_llm_calls_total.labels(agent_name="TransportQueryAssistant", status=gen_result["status"]).inc()

                progress_store.record(trace_id, STAGE_QUERY, "正在查询校巴路线/班次…")
                mcp_start = time.perf_counter()
                mcp_status = "ok"
                try:
                    if gen_result["status"] == "route":
                        tool_name = "find_route"
                        raw = _call_mcp_sync(tool_name, {
                            "origin": gen_result["origin"], "destination": gen_result["destination"]
                        })
                        response_text = self._format_route(raw)
                    else:  # timetable
                        tool_name = "query_transport"
                        raw = _call_mcp_sync(tool_name, {"sql": gen_result["sql"]})
                        response_text = self._format_timetable(raw)
                    mcp_tool_call_duration_seconds.labels(
                        server="transport", tool=tool_name
                    ).observe(time.perf_counter() - mcp_start)
                except Exception:
                    mcp_status = "error"
                    mcp_tool_call_duration_seconds.labels(
                        server="transport", tool=tool_name
                    ).observe(time.perf_counter() - mcp_start)
                    raise
                finally:
                    mcp_tool_calls_total.labels(
                        server="transport", tool=tool_name, status=mcp_status
                    ).inc()

                task.artifacts = [{"parts": [{"type": "text", "text": response_text}]}]
                task.status = TaskStatus(state=TaskState.COMPLETED)
                return task
            except Exception as e:
                logger.error(f"查询失败: {str(e)}")
                task.status = TaskStatus(
                    state=TaskState.FAILED,
                    message={"role": "agent", "content": {"text": f"查询失败: {str(e)} 请重试或提供更多细节。"}},
                )
                return task


if __name__ == "__main__":
    transport_server = TransportQueryServer()
    print("\n=== 服务器信息 ===")
    print(f"名称: {transport_server.agent_card.name}")
    print(f"描述: {transport_server.agent_card.description}")
    print(f"MCP URL: {conf.mcp_transport_url}")
    print("\n技能:")
    for skill in transport_server.agent_card.skills:
        print(f"- {skill.name}: {skill.description}")
    run_server(transport_server, host="127.0.0.1", port=5008)
