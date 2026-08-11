#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: course_agent.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/4
描述: 课程查询 A2A Agent 服务器（端口 5005）

v3.4 Tier 1 升级:
  - MCP stateless Client (无需 initialize 握手)
  - 动态获取 table schema (不再硬编码表结构)
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
MCP_COURSE_URL = conf.mcp_course_url

# ============ LLM ============
llm = create_llm()

# ============ 动态 Schema ============
_schema_cache = {"text": "", "fetched_at": 0}
_SCHEMA_TTL = 3600  # 缓存 1 小时


async def _fetch_schema_async():
    """从 MCP Server 获取 course_info 表结构"""
    async with Client(MCP_COURSE_URL) as client:
        result = await client.call_tool("get_course_schema", {})
        return result.content[0].text


def _get_table_schema() -> str:
    """获取表结构（带缓存），转为 SQL CREATE TABLE 格式的文本"""
    global _schema_cache
    now = time.time()
    if _schema_cache["text"] and (now - _schema_cache["fetched_at"]) < _SCHEMA_TTL:
        return _schema_cache["text"]

    try:
        raw = asyncio.run(_fetch_schema_async())
        schema_data = json.loads(raw)
        if schema_data.get("status") == "success":
            # 将 SHOW FULL COLUMNS 结果转为 SQL DDL 风格的文本
            columns = schema_data.get("columns", [])
            lines = ["CREATE TABLE course_info ("]
            for col in columns:
                field = col.get("Field", "")
                col_type = col.get("Type", "")
                null = "NULL" if col.get("Null", "YES") == "YES" else "NOT NULL"
                default = col.get("Default")
                comment = col.get("Comment", "")
                parts = [f"  {field} {col_type} {null}"]
                if default is not None:
                    parts.append(f"DEFAULT {default}")
                if comment:
                    parts.append(f"COMMENT '{comment}'")
                lines.append("    ".join(parts) + ",")
            # 索引
            indexes = schema_data.get("indexes", [])
            seen_keys = set()
            for idx in indexes:
                key_name = idx.get("Key_name", "")
                if key_name == "PRIMARY" or key_name in seen_keys:
                    continue
                seen_keys.add(key_name)
                col_name = idx.get("Column_name", "")
                lines.append(f"  UNIQUE KEY {key_name} ({col_name}),")
            lines.append(") ENGINE=INNODB DEFAULT CHARSET=utf8mb4;")
            text = "\n".join(lines)
            _schema_cache["text"] = text
            _schema_cache["fetched_at"] = now
            logger.info(f"[Schema] course_info 表结构已刷新 ({len(columns)} 列)")
            return text
    except Exception as e:
        logger.warning(f"[Schema] 获取 course_info 表结构失败: {e}，使用缓存")
        if _schema_cache["text"]:
            return _schema_cache["text"]
        raise

    return _schema_cache["text"]


# ============ SQL 生成 Prompt ============
sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是一个专业的CUHK课程SQL生成器，需要从对话历史（含用户的问题）中提取关键信息，然后基于course_info表生成SELECT语句。
- 如果用户需要查课程，则至少需要课程代码或课程名称信息。如果对话历史中缺乏必要的信息，可以向其追问，输出格式为json格式，如示例所示；如果对话历史中信息齐全，则输出纯SQL即可。
- 如果用户问与课程无关的问题，则模仿最后2个示例回复即可。


示例：
- 对话: user: CSCI2100
输出: SELECT course_code, course_name, department, instructor, schedule_day, start_time, end_time, classroom, building, credits, capacity, enrolled, category FROM course_info WHERE course_code = 'CSCI2100'
- 对话: user: Data Structures 这门课
输出: SELECT course_code, course_name, department, instructor, schedule_day, start_time, end_time, classroom, building, credits, capacity, enrolled, category FROM course_info WHERE course_name LIKE '%Data Structures%'

- 对话: user: 有什么课
输出: {{"status": "input_required", "message": "请提供具体的课程代码或课程名称，例如 'CSCI2100' 或 'Data Structures'。"}}
- 对话: user: CSCI
assistant: 请提供具体的课程代码。
user: CSCI3100
输出: SELECT course_code, course_name, department, instructor, schedule_day, start_time, end_time, classroom, building, credits, capacity, enrolled, category FROM course_info WHERE course_code = 'CSCI3100'
- 对话: user: CSCI4180的上课时间\nassistant: 周一和周三16:30-18:15在Science Centre。\nuser: 那CSCI4430呢
输出: SELECT course_code, course_name, department, instructor, schedule_day, start_time, end_time, classroom, building, credits, capacity, enrolled, category FROM course_info WHERE course_code = 'CSCI4430'

- 对话: user: 你好
输出: {{"status": "input_required", "message": "请提供课程代码或课程名称，例如 'CSCI2100' 或 'Data Structures'。"}}
- 对话: user: 今天有什么好吃的
输出: {{"status": "input_required", "message": "请提供课程相关查询，包括课程代码或课程名称。"}}

course_info表结构：{table_schema_string}
对话历史: {conversation}
当前日期: {current_date} (Asia/Shanghai)
    """
)


# ============ MCP 工具调用 ============
def _call_mcp_sync(tool_name: str, args: dict) -> str:
    """同步封装：通过 stateless MCP Client 调用工具
    每次调用创建独立的 Client（stateless HTTP — 无 session 无 initialize）"""
    async def _call():
        async with Client(MCP_COURSE_URL) as client:
            result = await client.call_tool(tool_name, args)
            return result.content[0].text
    return asyncio.run(_call())


# ============ Agent 卡片 ============
agent_card = AgentCard(
    name="CourseQueryAssistant",
    description="基于LangChain提供CUHK课程查询服务的助手，使用 MCP stateless 协议动态获取表结构",
    url="http://localhost:5005",
    version="1.1.0",
    capabilities={"streaming": True, "memory": True},
    skills=[
        AgentSkill(
            name="execute course query",
            description="执行课程查询，返回课程数据库结果，支持自然语言输入",
            examples=["CSCI2100 上课时间", "Data Structures 课程信息", "有哪些CS选修课"]
        )
    ]
)


# ============ A2A Server ============
class CourseQueryServer(A2AServer):
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
            return "course_info 表包含课程代码、名称、教师、时间、地点等字段"

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
            if output.startswith('{'):
                return json.loads(output)
            return {"status": "sql", "sql": output}
        except Exception as e:
            logger.error(f"SQL生成失败: {str(e)}")
            return {"status": "input_required", "message": "查询无效，请提供课程代码或名称。"}

    def handle_task(self, task):
        # 从 A2A 消息中提取 trace_id，实现跨进程链路关联
        trace_id = (task.message or {}).get("_trace_id", "")
        if trace_id:
            set_trace_id(trace_id)

        content = (task.message or {}).get("content", {})
        conversation = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"对话历史及用户问题: {conversation}")

        with span("agent_handle_task", {"agent": "CourseQueryAssistant"}):
            try:
                # 1. 生成 SQL
                llm_start = time.perf_counter()
                llm_status = "ok"
                gen_result = self.generate_sql_query(conversation)
                agent_llm_duration_seconds.labels(agent_name="CourseQueryAssistant").observe(
                    time.perf_counter() - llm_start
                )

                if gen_result["status"] == "input_required":
                    agent_llm_calls_total.labels(agent_name="CourseQueryAssistant", status="input_required").inc()
                    task.status = TaskStatus(
                        state=TaskState.INPUT_REQUIRED,
                        message={"role": "agent", "content": {"text": gen_result["message"]}},
                    )
                    return task

                agent_llm_calls_total.labels(agent_name="CourseQueryAssistant", status="sql_generated").inc()
                sql_query = gen_result["sql"]
                logger.info(f"生成的SQL查询: {sql_query}")

                # 2. 通过 stateless MCP Client 执行查询 (传递 trace_id)
                mcp_start = time.perf_counter()
                mcp_status = "ok"
                try:
                    course_result = _call_mcp_sync("query_courses", {"sql": sql_query})
                    mcp_tool_call_duration_seconds.labels(
                        server="course", tool="query_courses"
                    ).observe(time.perf_counter() - mcp_start)
                except Exception:
                    mcp_status = "error"
                    mcp_tool_call_duration_seconds.labels(
                        server="course", tool="query_courses"
                    ).observe(time.perf_counter() - mcp_start)
                    raise
                finally:
                    mcp_tool_calls_total.labels(
                        server="course", tool="query_courses", status=mcp_status
                    ).inc()

                # 3. 格式化结果
                response = json.loads(course_result) if isinstance(course_result, str) else course_result
                logger.info(f"MCP 返回: {response}")
                if response.get("status") == "success":
                    data = response.get("data", [])
                    response_text = "\n".join([
                        f"{d['course_code']} {d['course_name']} | {d['instructor']} | "
                        f"{d['schedule_day']} {d['start_time']}-{d['end_time']} | "
                        f"{d['building']} {d['classroom']} | {d['category']} | "
                        f"学分:{d['credits']} | 已选:{d['enrolled']}/{d['capacity']}"
                        for d in data
                    ])
                    task.artifacts = [{"parts": [{"type": "text", "text": response_text}]}]
                    task.status = TaskStatus(state=TaskState.COMPLETED)
                elif response.get("status") == "no_data":
                    response_text = response.get("message", "请重新输入查询的课程代码或名称。")
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
    course_server = CourseQueryServer()
    print("\n=== 服务器信息 ===")
    print(f"名称: {course_server.agent_card.name}")
    print(f"描述: {course_server.agent_card.description}")
    print(f"MCP URL: {conf.mcp_course_url}")
    print("\n技能:")
    for skill in course_server.agent_card.skills:
        print(f"- {skill.name}: {skill.description}")
    run_server(course_server, host="127.0.0.1", port=5005)
