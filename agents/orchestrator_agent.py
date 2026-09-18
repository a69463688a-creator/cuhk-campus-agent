#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: orchestrator_agent.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/9/17
描述: 编排 Agent（OrchestratorAgent）—— 端口 5007

A2A 双角色：
  - server：接收 Web 网关 / CLI 发来的编排任务
  - client：作为 AgentNetwork 客户端委派 CourseQueryAssistant / FacilityQueryAssistant

职责（自 app/server.py 迁移）：
  - 意图识别（LLM，多意图）
  - 路由：多意图并行委派 specialist agent
  - weather / recommend 内部直连 / 直调 LLM（不单独 agent 化）
  - 结果聚合，返回最终 artifact

设计要点：
  - 无状态：对话历史由调用方（网关/CLI）随任务消息以 JSON payload 注入
  - trace 对称：入站任务提取 _trace_id，出站任务注入 _trace_id
  - 并行委派：多意图用 asyncio.gather 并发下派
"""
import json
import asyncio
import functools
import time
import re
import uuid
from datetime import datetime

import pytz
import httpx
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from python_a2a import (
    A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState,
    AgentNetwork, Message, TextContent, MessageRole, Task,
)

from app.config import Config
from app.logging import logger
from app.llm import create_llm
from app.prompts import SmartCampusPrompts
from app.a2a_types import AgentResult, status_message_text
from app.progress import (
    progress_store, register_progress_endpoint, await_task_with_progress,
    STAGE_INTENT, STAGE_DELEGATE, STAGE_COMPOSE,
)
from app.observability import (
    span, set_trace_id, get_trace_id,
    a2a_agent_calls_total, a2a_agent_call_duration_seconds,
)

conf = Config()
TZ = pytz.timezone('Asia/Shanghai')
llm = create_llm()
streaming_llm = create_llm(streaming=True)  # 仅单意图 summarize 用 token 级流式

# ============ 意图 → Agent 映射（自 config.py 迁移） ============
INTENT_AGENT_MAP = {
    "course": "CourseQueryAssistant",
    "campus_event": "FacilityQueryAssistant",
    "campus_news": "FacilityQueryAssistant",
    "canteen": "FacilityQueryAssistant",
    "library_hours": "FacilityQueryAssistant",
    "transport": "TransportQueryAssistant",
    "planning": "PlannerAgent",
}

AGENT_URLS = {
    "CourseQueryAssistant": "http://localhost:5005",
    "FacilityQueryAssistant": "http://localhost:5006",
    "TransportQueryAssistant": "http://localhost:5008",
    "PlannerAgent": "http://localhost:5009",
}

# ============ Specialist AgentNetwork（orchestrator 作为 client 委派） ============
agent_network = AgentNetwork(name="CUHK Campus Specialist Network")
agent_network.add("CourseQueryAssistant", AGENT_URLS["CourseQueryAssistant"])
agent_network.add("FacilityQueryAssistant", AGENT_URLS["FacilityQueryAssistant"])
agent_network.add("TransportQueryAssistant", AGENT_URLS["TransportQueryAssistant"])
agent_network.add("PlannerAgent", AGENT_URLS["PlannerAgent"])


# ============ 意图识别 ============
@functools.lru_cache(maxsize=128)
def _intent_llm_raw(conversation_history: str, query: str, current_date: str) -> str:
    """意图识别 LLM 原始输出（进程内 LRU 缓存，命中则不再调 LLM）。"""
    chain = SmartCampusPrompts.intent_prompt() | llm
    return chain.invoke({
        "conversation_history": conversation_history,
        "query": query,
        "current_date": current_date,
    }).content.strip()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(0.5),
    retry=retry_if_exception_type((Exception,)),
    before_sleep=lambda retry_state: logger.warning(
        f"LLM 意图识别重试 {retry_state.attempt_number}/3..."
    )
)
async def recognize_intent(user_input: str, conversation_history: str) -> tuple:
    """调用 LLM 进行多意图识别（异步），自动重试最多 3 次；命中缓存则不调 LLM。"""
    current_date = datetime.now(TZ).strftime('%Y-%m-%d')

    with span("llm_recognize_intent"):
        intent_response = await asyncio.to_thread(
            _intent_llm_raw, conversation_history, user_input, current_date
        )

        intent_response = re.sub(r'^```json\s*|\s*```$', '', intent_response).strip()
        logger.info(f"意图识别: {intent_response}")

        intent_output = json.loads(intent_response)
        intents = intent_output.get("intents", [])
        user_queries = intent_output.get("user_queries", {})
        follow_up_message = intent_output.get("follow_up_message", "")
        return intents, user_queries, follow_up_message


# ============ 天气 API（内部直连，异步 httpx） ============
async def fetch_weather() -> dict:
    """调用 Open-Meteo API 获取 CUHK 区域天气"""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": 22.419,
        "longitude": 114.207,
        "current_weather": "true",
        "daily": "temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum",
        "timezone": "Asia/Shanghai",
        "forecast_days": 4
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        logger.info(f"天气 API 返回: 当前温度 {data.get('current_weather', {}).get('temperature', 'N/A')}°C")
        return {"status": "success", "data": data}
    except Exception as e:
        logger.error(f"天气 API 调用失败: {e}")
        return {"status": "error", "message": str(e)}


def format_weather_for_prompt(data: dict) -> str:
    """将 Open-Meteo 原始 JSON 转为 LLM 友好文本"""
    if data.get("status") != "success":
        return f"天气数据获取失败: {data.get('message', '未知错误')}"

    raw = data["data"]
    current = raw.get("current_weather", {})
    daily = raw.get("daily", {})

    lines = [
        f"当前温度: {current.get('temperature', 'N/A')}°C",
        f"风速: {current.get('windspeed', 'N/A')} km/h",
        f"天气代码: {current.get('weathercode', 'N/A')}",
    ]

    if daily:
        dates = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        codes = daily.get("weathercode", [])
        precip = daily.get("precipitation_sum", [])

        for i in range(min(len(dates), 4)):
            day_label = "今天" if i == 0 else f"第{i}天({dates[i]})"
            lines.append(
                f"{day_label}: {min_temps[i] if i < len(min_temps) else '?'}°C ~ "
                f"{max_temps[i] if i < len(max_temps) else '?'}°C, "
                f"天气代码 {codes[i] if i < len(codes) else '?'}, "
                f"降水 {precip[i] if i < len(precip) else '?'}mm"
            )

    return "\n".join(lines)


# ============ Specialist Agent 委派 ============
@retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(0.5),
    retry=retry_if_exception_type((Exception,)),
    before_sleep=lambda retry_state: logger.warning(
        f"Specialist Agent 调用重试 {retry_state.attempt_number}/2..."
    )
)
async def call_agent(agent_name: str, query_str: str, conversation_history: str, forward_output: bool = False) -> AgentResult:
    """委派 specialist agent 并返回结构化结果（区分结果 / 追问，自动重试最多 2 次）。

    forward_output=True 时把下游（planner）流式上抛的输出增量转发到 orchestrator
    本进程 progress_store，供 web 轮询读取；仅单意图时开启。
    """
    start = time.perf_counter()
    status = "error"
    try:
        agent = agent_network.get_agent(agent_name)
        agent.timeout = 180  # 规划型 Agent 链路过长（多级 LLM），默认 30s 会读超时
        trace_id = get_trace_id()
        chat_history = conversation_history + f'\nUser: {query_str}'
        message = Message(content=TextContent(text=chat_history), role=MessageRole.USER)
        message_dict = message.to_dict()
        message_dict["_trace_id"] = trace_id
        task = Task(id="task-" + str(uuid.uuid4()), message=message_dict)

        def _on_progress(stage: dict):
            # specialist/planner 阶段转发到 orchestrator 本进程 progress_store（同一 trace_id）
            progress_store.record(trace_id, stage.get("stage", ""), f"[{agent_name}] {stage.get('label', '')}")

        def _on_output(chunk: str):
            # planner 的 token 流转发到 orchestrator 本进程 progress_store
            progress_store.append_output(trace_id, chunk)

        with span("a2a_call_agent", {"agent_name": agent_name}):
            # 后台阻塞等最终结果 + 前台轮询下游进度端点
            raw_response = await await_task_with_progress(
                agent.send_task_async(task),
                AGENT_URLS[agent_name],
                trace_id,
                on_progress=_on_progress,
                on_output=(_on_output if forward_output else None),
            )
            state = raw_response.status.state.value  # TaskState(str,Enum) → "completed"/"input-required"/"failed"
            logger.info(f"{agent_name} 响应状态: {state}")
            status = state

            if state == 'completed':
                return AgentResult("completed", raw_response.artifacts[0]['parts'][0]['text'])

            # input-required / failed 等：从 status.message 提取追问或错误文本
            return AgentResult(state, status_message_text(raw_response.status.message))
    finally:
        elapsed = time.perf_counter() - start
        a2a_agent_calls_total.labels(agent_name=agent_name, status=status).inc()
        a2a_agent_call_duration_seconds.labels(agent_name=agent_name).observe(elapsed)


async def summarize_response(agent_name: str, query_str: str, agent_result: str, stream_output: bool = False) -> str:
    """用 LLM 总结 specialist agent 返回的原始数据（异步，可选 token 级流式）。

    stream_output=True 时用 streaming_llm + astream 逐 token 上抛（写入本进程
    progress_store 的 output）；否则走同步 ainvoke。仅单意图时开启，避免多意图
    并行 summarize 的输出互相交叠。
    """
    if agent_name == "CourseQueryAssistant":
        prompt = SmartCampusPrompts.summarize_course_prompt()
    elif agent_name == "FacilityQueryAssistant":
        prompt = SmartCampusPrompts.summarize_facility_prompt()
    elif agent_name == "TransportQueryAssistant":
        prompt = SmartCampusPrompts.summarize_transport_prompt()
    else:
        return agent_result

    payload = {"query": query_str, "raw_response": agent_result}
    if stream_output:
        chain = prompt | streaming_llm
        parts = []
        async for chunk in chain.astream(payload):
            piece = chunk.content
            if piece:
                piece = piece if isinstance(piece, str) else str(piece)
                parts.append(piece)
                progress_store.append_output(get_trace_id(), piece)
        return "".join(parts).strip()

    chain = prompt | llm
    return (await chain.ainvoke(payload)).content.strip()


# ============ Agent 卡片 ============
agent_card = AgentCard(
    name="OrchestratorAgent",
    description="CUHK 校园生活编排 Agent：识别用户意图，委派课程/设施查询 Agent，聚合结果",
    url="http://localhost:5007",
    version="1.0.0",
    capabilities={"streaming": True, "memory": False},
    skills=[
        AgentSkill(
            name="orchestrate campus queries",
            description="识别意图并委派 specialist agent，聚合为最终回答",
            examples=["CSCI2100 上课时间和今天天气", "最近有什么讲座", "崇基学院有什么餐厅"]
        )
    ]
)


# ============ A2A Server ============
class OrchestratorServer(A2AServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)

    def setup_routes(self, app):
        """注册自定义进度端点（在库默认路由之上）。"""
        super().setup_routes(app)
        register_progress_endpoint(app, self)

    @staticmethod
    def _parse_payload(text: str) -> tuple:
        """解析调用方注入的 JSON payload: {query, conversation_history}。

        兼容纯文本输入（非 JSON）——按原始文本作 query、历史为空处理。
        """
        if text:
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    return data.get("query", ""), data.get("conversation_history", "")
            except (json.JSONDecodeError, ValueError):
                pass
        return text, ""

    async def _process_one(self, intent: str, user_queries: dict, query: str, history: str, stream_output: bool = False) -> AgentResult:
        """处理单个意图，永不抛异常（返回结构化结果，区分结果 / 追问）。"""
        try:
            if intent == "weather":
                weather_data = await fetch_weather()
                weather_text = format_weather_for_prompt(weather_data)
                chain = SmartCampusPrompts.summarize_weather_prompt() | llm
                text = (await chain.ainvoke({
                    "query": user_queries.get(intent, query), "raw_response": weather_text
                })).content.strip()
                return AgentResult("completed", text)

            elif intent == "recommend":
                chain = SmartCampusPrompts.recommend_prompt() | llm
                text = (await chain.ainvoke({"query": user_queries.get(intent, query)})).content.strip()
                return AgentResult("completed", text)

            elif intent in INTENT_AGENT_MAP:
                agent_name = INTENT_AGENT_MAP[intent]
                query_str = user_queries.get(intent, query)
                logger.info(f"路由意图 '{intent}' -> {agent_name}，查询: {query_str}")
                result = await call_agent(agent_name, query_str, history, forward_output=stream_output)
                if result.needs_input:
                    # 追问：不做 summarize，原样上抛，由上层决定追问用户
                    return result
                return AgentResult("completed", await summarize_response(agent_name, query_str, result.text, stream_output))

            else:
                return AgentResult("completed", f"暂不支持「{intent}」类型的查询。")
        except Exception as e:
            logger.error(f"处理意图 '{intent}' 失败: {e}")
            return AgentResult("failed", f"查询「{intent}」时出错，请重试。")

    async def _handle_async(self, query: str, history: str) -> AgentResult:
        """编排主流程：意图识别 → 并行委派 → 聚合。"""
        trace_id = get_trace_id()
        with span("orchestrator_handle_task", {"agent": "OrchestratorAgent"}):
            progress_store.record(trace_id, STAGE_INTENT, "识别用户意图…")
            try:
                intents, user_queries, follow_up_message = await recognize_intent(query, history)
            except Exception as e:
                logger.error(f"意图识别失败: {e}")
                return AgentResult("completed", "抱歉，我暂时无法理解您的问题，请换种方式描述一下？")

            if "out_of_scope" in intents:
                return AgentResult("completed", follow_up_message)
            if follow_up_message and not intents:
                return AgentResult("completed", follow_up_message)

            progress_store.record(trace_id, STAGE_DELEGATE, "并行委派查询…")
            # 仅单意图开启 token 级流式（多意图并行 summarize 输出会互相交叠）
            stream_output = (len(intents) == 1)
            responses = await asyncio.gather(
                *[self._process_one(intent, user_queries, query, history, stream_output=stream_output) for intent in intents]
            )
            if not responses:
                return AgentResult("completed", "抱歉，没有找到相关信息。")

            progress_store.record(trace_id, STAGE_COMPOSE, "聚合结果…")
            # 全部子意图都追问 → 整体作为「追问」上抛（交由用户补充后重跑）
            if all(r.needs_input for r in responses):
                return AgentResult("input-required", "\n\n".join(r.text for r in responses))

            return AgentResult("completed", "\n\n".join(r.text for r in responses))

    def handle_task(self, task):
        # 从 A2A 消息提取 trace_id，实现跨进程链路关联（与 specialist 对称）
        trace_id = (task.message or {}).get("_trace_id", "")
        if trace_id:
            set_trace_id(trace_id)

        content = (task.message or {}).get("content", {})
        text = content.get("text", "") if isinstance(content, dict) else ""
        query, history = self._parse_payload(text)
        logger.info(f"编排任务: query={query[:80]}")

        try:
            result = asyncio.run(self._handle_async(query, history))
            if result.needs_input:
                # 追问：以 INPUT_REQUIRED 状态返回，供上游识别并追问用户
                task.status = TaskStatus(
                    state=TaskState.INPUT_REQUIRED,
                    message={"role": "agent", "content": {"text": result.text}},
                )
            else:
                task.artifacts = [{"parts": [{"type": "text", "text": result.text}]}]
                task.status = TaskStatus(state=TaskState.COMPLETED)
        except Exception as e:
            logger.error(f"编排失败: {e}")
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message={"role": "agent", "content": {"text": f"编排失败: {str(e)} 请重试。"}},
            )
        return task


if __name__ == "__main__":
    orchestrator = OrchestratorServer()
    print("\n=== 服务器信息 ===")
    print(f"名称: {orchestrator.agent_card.name}")
    print(f"描述: {orchestrator.agent_card.description}")
    print(f"版本: {orchestrator.agent_card.version}")
    print("\n委派的 specialist agents:")
    for name, url in AGENT_URLS.items():
        print(f"- {name}: {url}")
    run_server(orchestrator, host="127.0.0.1", port=5007)
