#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: web_server.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/8/10
描述: FastAPI Web 后端 —— 替代 Streamlit app.py，提供 REST + WebSocket API
      服务静态前端页面，集成 A2A Agent 调用、天气 API、意图识别
"""
import os
import sys
import json
import re
import uuid
import time
import asyncio
from datetime import datetime
from typing import Optional, Dict, List

import pytz
import requests
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.websockets import WebSocketDisconnect
from pydantic import BaseModel
from python_a2a import AgentNetwork, Message, TextContent, MessageRole, Task
from langchain_openai import ChatOpenAI

# 添加项目根目录到路径
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from config import Config
from create_logger import logger
from main_prompts import SmartCampusPrompts

# ============ 配置 ============
conf = Config()
TZ = pytz.timezone('Asia/Shanghai')

# ============ FastAPI 应用 ============
app = FastAPI(title="SmartCampus API", description="CUHK校园生活助手 Web API", version="3.0.0")

# 静态文件挂载
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ============ 全局状态 ============
agent_network: Optional[AgentNetwork] = None
llm: Optional[ChatOpenAI] = None
sessions: Dict[str, List[dict]] = {}  # session_id -> [{role, content, timestamp}]

# Greeting patterns
GREETING_PATTERNS = [
    (r"^(你好|您好|hi|hello|嗨|hey)", "你好！我是CUHK校园生活助手 🎓，可以帮你查询课程、校园活动、新闻、餐厅、图书馆开放时间和天气！请问有什么可以帮你的？"),
    (r"^(你是谁|您是谁|你叫什么|你的名字)", "我是CUHK校园生活助手，专注于为中文大学师生提供便捷的校园信息查询服务！"),
    (r"^(谢谢|感谢|thanks|thank you|多谢)", "不客气！很高兴能帮到你。如有其他问题，随时问我～"),
]


# ============ 启动事件 ============
@app.on_event("startup")
async def startup():
    global agent_network, llm

    # 初始化 LLM
    llm = ChatOpenAI(
        model=conf.model_name,
        api_key=conf.api_key,
        base_url=conf.base_url,
        temperature=0.1
    )

    # 初始化 AgentNetwork（仅保留2个代理，移除 BookingAssistant）
    agent_network = AgentNetwork(name="CUHK Campus Assistant Network")
    agent_network.add("CourseQueryAssistant", "http://localhost:5005")
    agent_network.add("FacilityQueryAssistant", "http://localhost:5006")
    logger.info("AgentNetwork 初始化完成：CourseQueryAssistant + FacilityQueryAssistant")
    logger.info("Web 服务器启动就绪，监听 http://0.0.0.0:8080")


# ============ 请求模型 ============
class QueryRequest(BaseModel):
    query: str
    source_filter: Optional[str] = None  # 意图过滤
    session_id: Optional[str] = None


# ============ 工具函数 ============
def check_greeting(query: str) -> Optional[str]:
    """检查是否为日常问候，返回预设回复"""
    for pattern, response in GREETING_PATTERNS:
        if re.match(pattern, query.strip(), re.IGNORECASE):
            return response
    return None


def get_session(session_id: str) -> List[dict]:
    """获取或创建会话"""
    if session_id not in sessions:
        sessions[session_id] = []
    return sessions[session_id]


# ============ 意图识别 ============
def recognize_intent(user_input: str, conversation_history: str) -> tuple:
    """调用 LLM 进行多意图识别"""
    chain = SmartCampusPrompts.intent_prompt() | llm
    current_date = datetime.now(TZ).strftime('%Y-%m-%d')
    context_lines = '\n'.join(conversation_history.split("\n")[-6:])

    intent_response = chain.invoke({
        "conversation_history": context_lines,
        "query": user_input,
        "current_date": current_date
    }).content.strip()

    # 清理 Markdown 代码块
    intent_response = re.sub(r'^```json\s*|\s*```$', '', intent_response).strip()
    logger.info(f"意图识别: {intent_response}")

    intent_output = json.loads(intent_response)
    intents = intent_output.get("intents", [])
    user_queries = intent_output.get("user_queries", {})
    follow_up_message = intent_output.get("follow_up_message", "")
    return intents, user_queries, follow_up_message


# ============ 天气 API ============
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
        resp = requests.get(url, params=params, timeout=10)
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


# ============ A2A Agent 调用 ============
async def call_agent(agent_name: str, query_str: str, conversation_history: str) -> str:
    """调用 A2A Agent 并返回原始结果文本"""
    agent = agent_network.get_agent(agent_name)
    chat_history = '\n'.join(conversation_history.split("\n")[-7:-1]) + f'\nUser: {query_str}'
    message = Message(content=TextContent(text=chat_history), role=MessageRole.USER)
    task = Task(id="task-" + str(uuid.uuid4()), message=message.to_dict())

    raw_response = await agent.send_task_async(task)
    logger.info(f"{agent_name} 响应状态: {raw_response.status.state}")

    if raw_response.status.state == 'completed':
        return raw_response.artifacts[0]['parts'][0]['text']
    else:
        return raw_response.status.message['content']['text']


async def summarize_response(agent_name: str, query_str: str, agent_result: str) -> str:
    """用 LLM 总结 Agent 返回的原始数据"""
    if agent_name == "CourseQueryAssistant":
        chain = SmartCampusPrompts.summarize_course_prompt() | llm
    elif agent_name == "FacilityQueryAssistant":
        chain = SmartCampusPrompts.summarize_facility_prompt() | llm
    else:
        return agent_result

    return chain.invoke({"query": query_str, "raw_response": agent_result}).content.strip()


# ============ 核心处理逻辑（生成器版本，用于 WebSocket 流式） ============
async def process_query_stream(query: str, session_id: str):
    """流式处理查询，逐 token yield"""
    session = get_session(session_id)

    # 构建对话历史
    history_text = ""
    for msg in session:
        role_prefix = "User" if msg["role"] == "user" else "Assistant"
        history_text += f"\n{role_prefix}: {msg['content']}"

    # 记录用户消息
    session.append({"role": "user", "content": query, "timestamp": datetime.now(TZ).isoformat()})

    # 问候检查
    greeting = check_greeting(query)
    if greeting:
        session.append({"role": "assistant", "content": greeting, "timestamp": datetime.now(TZ).isoformat()})
        yield greeting, True, None
        return

    # 意图识别
    try:
        intents, user_queries, follow_up_message = recognize_intent(query, history_text)
    except Exception as e:
        logger.error(f"意图识别失败: {e}")
        error_msg = "抱歉，我暂时无法理解您的问题，请换种方式描述一下？"
        session.append({"role": "assistant", "content": error_msg, "timestamp": datetime.now(TZ).isoformat()})
        yield error_msg, True, None
        return

    # 超出范围
    if "out_of_scope" in intents:
        session.append({"role": "assistant", "content": follow_up_message, "timestamp": datetime.now(TZ).isoformat()})
        yield follow_up_message, True, None
        return

    # 追问
    if follow_up_message and not intents:
        session.append({"role": "assistant", "content": follow_up_message, "timestamp": datetime.now(TZ).isoformat()})
        yield follow_up_message, True, None
        return

    # 处理每个意图
    responses = []
    for intent in intents:
        try:
            if intent == "weather":
                # 天气：直接调 API
                weather_data = await fetch_weather()
                weather_text = format_weather_for_prompt(weather_data)
                chain = SmartCampusPrompts.summarize_weather_prompt() | llm
                final = chain.invoke({"query": user_queries.get(intent, query), "raw_response": weather_text}).content.strip()
                responses.append(final)

            elif intent == "recommend":
                # 推荐：LLM 直接生成
                chain = SmartCampusPrompts.recommend_prompt() | llm
                final = chain.invoke({"query": user_queries.get(intent, query)}).content.strip()
                responses.append(final)

            elif intent in conf.intent:
                # 有 Agent 映射的意图
                agent_name = conf.intent[intent]
                query_str = user_queries.get(intent, query)
                logger.info(f"路由意图 '{intent}' -> {agent_name}，查询: {query_str}")

                agent_result = await call_agent(agent_name, query_str, history_text)
                final = await summarize_response(agent_name, query_str, agent_result)
                responses.append(final)

            else:
                responses.append(f"暂不支持「{intent}」类型的查询。")
        except Exception as e:
            logger.error(f"处理意图 '{intent}' 失败: {e}")
            responses.append(f"查询「{intent}」时出错，请重试。")

    full_response = "\n\n".join(responses) if responses else "抱歉，没有找到相关信息。"

    # 记录助手回复
    session.append({"role": "assistant", "content": full_response, "timestamp": datetime.now(TZ).isoformat()})
    yield full_response, True, None


# ============ API 路由 ============
@app.get("/")
async def root():
    """返回前端页面"""
    return FileResponse("static/index.html")


@app.post("/api/create_session")
async def create_session():
    """创建新会话"""
    session_id = str(uuid.uuid4())
    sessions[session_id] = []
    logger.info(f"新会话创建: {session_id[:8]}...")
    return {"session_id": session_id}


@app.get("/api/history/{session_id}")
async def get_history(session_id: str):
    """获取会话历史"""
    history = get_session(session_id)
    return {"session_id": session_id, "history": history}


@app.delete("/api/history/{session_id}")
async def clear_history(session_id: str):
    """清除会话历史"""
    if session_id in sessions:
        sessions[session_id] = []
    return {"status": "success", "message": "历史记录已清除"}


@app.get("/api/sources")
async def get_sources():
    """返回可用查询类型列表"""
    return {
        "sources": [
            {"value": "", "label": "全部"},
            {"value": "course", "label": "📚 课程查询"},
            {"value": "campus_event", "label": "🎉 校园活动"},
            {"value": "campus_news", "label": "📰 校园新闻"},
            {"value": "canteen", "label": "🍽️ 餐厅信息"},
            {"value": "library_hours", "label": "📖 图书馆"},
            {"value": "weather", "label": "🌤️ 天气"},
        ]
    }


@app.post("/api/query")
async def query_api(request: QueryRequest):
    """非流式查询接口"""
    start_time = time.time()
    session_id = request.session_id or str(uuid.uuid4())

    full_response = ""
    async for token, is_complete, _ in process_query_stream(request.query, session_id):
        full_response = token

    return {
        "answer": full_response,
        "is_streaming": False,
        "session_id": session_id,
        "processing_time": round(time.time() - start_time, 3)
    }


@app.websocket("/api/stream")
async def stream_api(websocket: WebSocket):
    """WebSocket 流式查询接口"""
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_text()
            request_data = json.loads(data)
            query = request_data.get("query", "")
            session_id = request_data.get("session_id", str(uuid.uuid4()))
            start_time = time.time()

            if not query.strip():
                continue

            # 发送开始信号
            await websocket.send_json({"type": "start", "session_id": session_id})

            # 流式处理
            accumulated = ""
            async for token, is_complete, _ in process_query_stream(query, session_id):
                # 逐字符流式输出（模拟打字效果）
                new_chars = token[len(accumulated):]
                for char in new_chars:
                    await websocket.send_json({"type": "token", "token": char, "session_id": session_id})
                    await asyncio.sleep(0.02)  # 打字速度
                accumulated += new_chars

            # 发送结束信号
            await websocket.send_json({
                "type": "end",
                "session_id": session_id,
                "is_complete": True,
                "processing_time": round(time.time() - start_time, 3)
            })

    except WebSocketDisconnect as e:
        logger.info(f"WebSocket 断开: code={e.code}")
    except Exception as e:
        logger.error(f"WebSocket 错误: {e}")
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now(TZ).isoformat()}


# ============ 主入口 ============
if __name__ == "__main__":
    import uvicorn
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 8080))
    print(f"\n{'='*60}")
    print(f"  SmartCampus Web 服务器 v3.0")
    print(f"  访问地址: http://localhost:{port}")
    print(f"  API 文档:  http://localhost:{port}/docs")
    print(f"{'='*60}\n")
    uvicorn.run("web_server:app", host=host, port=port, reload=False)
