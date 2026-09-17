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
import time
import re
import uuid
from datetime import datetime

import pytz
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from python_a2a import (
    A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState,
    AgentNetwork, Message, TextContent, MessageRole, Task,
)

from app.config import Config
from app.logging import logger
from app.llm import create_llm
from app.prompts import SmartCampusPrompts
from app.observability import (
    span, set_trace_id, get_trace_id,
    a2a_agent_calls_total, a2a_agent_call_duration_seconds,
)

conf = Config()
TZ = pytz.timezone('Asia/Shanghai')
llm = create_llm()

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
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((Exception,)),
    before_sleep=lambda retry_state: logger.warning(
        f"LLM 意图识别重试 {retry_state.attempt_number}/3..."
    )
)
async def recognize_intent(user_input: str, conversation_history: str) -> tuple:
    """调用 LLM 进行多意图识别（异步），自动重试最多 3 次"""
    chain = SmartCampusPrompts.intent_prompt() | llm
    current_date = datetime.now(TZ).strftime('%Y-%m-%d')

    with span("llm_recognize_intent"):
        intent_response = (await chain.ainvoke({
            "conversation_history": conversation_history,
            "query": user_input,
            "current_date": current_date
        })).content.strip()

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
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((Exception,)),
    before_sleep=lambda retry_state: logger.warning(
        f"Specialist Agent 调用重试 {retry_state.attempt_number}/2..."
    )
)
async def call_agent(agent_name: str, query_str: str, conversation_history: str) -> str:
    """委派 specialist agent 并返回原始结果文本（自动重试最多 2 次）"""
    start = time.perf_counter()
    status = "error"
    try:
        agent = agent_network.get_agent(agent_name)
        agent.timeout = 180  # 规划型 Agent 链路过长（多级 LLM），默认 30s 会读超时
        chat_history = conversation_history + f'\nUser: {query_str}'
        message = Message(content=TextContent(text=chat_history), role=MessageRole.USER)
        message_dict = message.to_dict()
        message_dict["_trace_id"] = get_trace_id()
        task = Task(id="task-" + str(uuid.uuid4()), message=message_dict)

        with span("a2a_call_agent", {"agent_name": agent_name}):
            raw_response = await agent.send_task_async(task)
            logger.info(f"{agent_name} 响应状态: {raw_response.status.state}")

            if raw_response.status.state == 'completed':
                status = "completed"
                return raw_response.artifacts[0]['parts'][0]['text']
            status = raw_response.status.state
            return raw_response.status.message['content']['text']
    finally:
        elapsed = time.perf_counter() - start
        a2a_agent_calls_total.labels(agent_name=agent_name, status=status).inc()
        a2a_agent_call_duration_seconds.labels(agent_name=agent_name).observe(elapsed)


async def summarize_response(agent_name: str, query_str: str, agent_result: str) -> str:
    """用 LLM 总结 specialist agent 返回的原始数据（异步）"""
    if agent_name == "CourseQueryAssistant":
        chain = SmartCampusPrompts.summarize_course_prompt() | llm
    elif agent_name == "FacilityQueryAssistant":
        chain = SmartCampusPrompts.summarize_facility_prompt() | llm
    elif agent_name == "TransportQueryAssistant":
        chain = SmartCampusPrompts.summarize_transport_prompt() | llm
    else:
        return agent_result

    return (await chain.ainvoke({"query": query_str, "raw_response": agent_result})).content.strip()


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

    async def _process_one(self, intent: str, user_queries: dict, query: str, history: str) -> str:
        """处理单个意图，永不抛异常（返回错误文案）。"""
        try:
            if intent == "weather":
                weather_data = await fetch_weather()
                weather_text = format_weather_for_prompt(weather_data)
                chain = SmartCampusPrompts.summarize_weather_prompt() | llm
                return (await chain.ainvoke({
                    "query": user_queries.get(intent, query), "raw_response": weather_text
                })).content.strip()

            elif intent == "recommend":
                chain = SmartCampusPrompts.recommend_prompt() | llm
                return (await chain.ainvoke({"query": user_queries.get(intent, query)})).content.strip()

            elif intent in INTENT_AGENT_MAP:
                agent_name = INTENT_AGENT_MAP[intent]
                query_str = user_queries.get(intent, query)
                logger.info(f"路由意图 '{intent}' -> {agent_name}，查询: {query_str}")
                agent_result = await call_agent(agent_name, query_str, history)
                return await summarize_response(agent_name, query_str, agent_result)

            else:
                return f"暂不支持「{intent}」类型的查询。"
        except Exception as e:
            logger.error(f"处理意图 '{intent}' 失败: {e}")
            return f"查询「{intent}」时出错，请重试。"

    async def _handle_async(self, query: str, history: str) -> str:
        """编排主流程：意图识别 → 并行委派 → 聚合。"""
        with span("orchestrator_handle_task", {"agent": "OrchestratorAgent"}):
            try:
                intents, user_queries, follow_up_message = await recognize_intent(query, history)
            except Exception as e:
                logger.error(f"意图识别失败: {e}")
                return "抱歉，我暂时无法理解您的问题，请换种方式描述一下？"

            if "out_of_scope" in intents:
                return follow_up_message
            if follow_up_message and not intents:
                return follow_up_message

            responses = await asyncio.gather(
                *[self._process_one(intent, user_queries, query, history) for intent in intents]
            )
            return "\n\n".join(responses) if responses else "抱歉，没有找到相关信息。"

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
            answer = asyncio.run(self._handle_async(query, history))
            task.artifacts = [{"parts": [{"type": "text", "text": answer}]}]
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
