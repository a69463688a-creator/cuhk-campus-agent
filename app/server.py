#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: server.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/8/10
描述: FastAPI Web 后端 —— REST + WebSocket API，静态前端页面，
      集成 A2A Agent 调用、天气 API、意图识别
"""
import os
import sys
import json
import re
import uuid
import time
import asyncio
import subprocess
from datetime import datetime
from typing import Optional

import pytz
import mysql.connector
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from fastapi import FastAPI, WebSocket, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.websockets import WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator
from python_a2a import AgentNetwork, Message, TextContent, MessageRole, Task

from app.config import Config
from app.a2a_types import AgentResult, status_message_text
from app.progress import await_task_with_progress
from app.logging import logger
from app.memory import MemoryManager
from app.observability import (
    span, trace, new_trace_id, set_trace_id, get_trace_id,
    http_requests_total, http_request_duration_seconds,
    a2a_agent_calls_total, a2a_agent_call_duration_seconds,
    websocket_connections,
    get_metrics,
)

# ============ 配置 ============
conf = Config()
TZ = pytz.timezone('Asia/Shanghai')

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ============ FastAPI 应用 ============
app = FastAPI(title="SmartCampus API", description="CUHK校园生活助手 Web API", version="3.1.0")

# ============ TraceMiddleware — 全链路追踪入口 ============
# 不需要追踪的路径
_TRACE_EXCLUDE_PATHS = {"/health", "/metrics", "/static", "/favicon.ico", "/docs", "/openapi.json", "/redoc"}


@app.middleware("http")
async def trace_middleware(request: Request, call_next) -> Response:
    """为每个 HTTP 请求生成 trace_id，记录耗时，注入响应头"""
    path = request.url.path

    # 跳过非业务路径
    if any(path.startswith(p) for p in _TRACE_EXCLUDE_PATHS):
        return await call_next(request)

    # 生成或继承 trace_id
    tid = request.headers.get("X-Trace-Id", new_trace_id())
    set_trace_id(tid)

    start = time.perf_counter()
    method = request.method
    status_code = 500

    with span("http_request", {
        "method": method,
        "path": path,
        "client": request.client.host if request.client else "",
    }):
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Trace-Id"] = tid
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            elapsed = time.perf_counter() - start
            http_requests_total.labels(
                method=method, endpoint=path, status=str(status_code)
            ).inc()
            http_request_duration_seconds.labels(
                method=method, endpoint=path
            ).observe(elapsed)
            logger.info(
                f"{method} {path} → {status_code} ({elapsed*1000:.1f}ms)"
            )

# 静态文件挂载
static_dir = os.path.join(BASE_DIR, "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# ============ 全局状态 ============
agent_network: Optional[AgentNetwork] = None
memory: Optional[MemoryManager] = None  # 持久化分层记忆（替换原 sessions 内存字典）

# Greeting patterns
GREETING_PATTERNS = [
    (r"^(你好|您好|hi|hello|嗨|hey)", "你好！我是CUHK校园生活助手 🎓，可以帮你查询课程、校园活动、新闻、餐厅、图书馆开放时间和天气！请问有什么可以帮你的？"),
    (r"^(你是谁|您是谁|你叫什么|你的名字)", "我是CUHK校园生活助手，专注于为中文大学师生提供便捷的校园信息查询服务！"),
    (r"^(谢谢|感谢|thanks|thank you|多谢)", "不客气！很高兴能帮到你。如有其他问题，随时问我～"),
]


# ============ 启动事件 ============
@app.on_event("startup")
async def startup():
    global agent_network, memory

    # 初始化持久化分层记忆（替换原 sessions 内存字典）
    memory = MemoryManager(conf)
    await asyncio.to_thread(memory.warmup)  # 预热 embedding，消除冷启动延迟

    # 初始化 AgentNetwork（网关只连接编排 Agent，不再直连 specialist）
    agent_network = AgentNetwork(name="CUHK Campus Assistant Network")
    agent_network.add("OrchestratorAgent", conf.orchestrator_url)
    logger.info("AgentNetwork 初始化完成：OrchestratorAgent")
    logger.info("Web 服务器启动就绪，监听 http://0.0.0.0:8100")

    # 后台异步检查数据新鲜度（不阻塞启动）
    asyncio.create_task(check_and_refresh_data())


# ============ 数据新鲜度检查 ============
async def check_and_refresh_data():
    """启动时检查各数据表的新鲜度，自动刷新过期的高频数据"""
    await asyncio.sleep(2)  # 让启动日志先输出完

    # 数据表配置: (表名, 标签, 过期阈值_hours, 脚本路径, 是否自动刷新)
    tables = [
        ("campus_events",    "校园活动",   24,  "spiders/events.py",          True),
        ("campus_news",      "校园新闻",   24,  "spiders/news.py",            True),
        ("canteen",          "餐厅信息",   168, "spiders/canteen.py",         False),
        ("library_hours",    "图书馆时间", 168, "spiders/library.py",         False),
        ("course_info",      "课程数据",   168, "spiders/course.py",          False),
    ]

    logger.info("[数据检查] ========== 检查数据新鲜度 ==========")

    conn = None
    try:
        conn = mysql.connector.connect(
            host=conf.host, user=conf.user,
            password=conf.password, database=conf.database,
            charset="utf8mb4"
        )
        cursor = conn.cursor()
    except Exception as e:
        logger.error(f"[数据检查] MySQL 连接失败，跳过数据检查: {e}")
        return

    try:
        now = datetime.now(TZ)
        stale_auto = []    # 需要自动刷新的
        stale_manual = []  # 需要手动更新的

        for table, label, max_hours, script, auto_refresh in tables:
            try:
                cursor.execute(f"SELECT MAX(created_at) FROM {table}")
                result = cursor.fetchone()
                latest = result[0] if result else None

                if latest is None:
                    logger.warning(f"  {label}: ⚠️ 无数据记录")
                    (stale_auto if auto_refresh else stale_manual).append((label, script))
                    continue

                if latest.tzinfo is None:
                    latest = TZ.localize(latest)
                hours_ago = (now - latest).total_seconds() / 3600

                if hours_ago > max_hours:
                    logger.warning(f"  {label}: ⚠️ 已过期 ({hours_ago:.0f}h 前, 阈值 {max_hours}h)")
                    (stale_auto if auto_refresh else stale_manual).append((label, script))
                else:
                    logger.info(f"  {label}: ✅ 新鲜 ({hours_ago:.0f}h 前)")
            except Exception as e:
                logger.error(f"  {label}: 检查失败 - {e}")
    finally:
        cursor.close()
        conn.close()

    # 自动刷新高频数据（新闻、活动）
    for label, script in stale_auto:
        logger.info(f"[自动刷新] 正在更新{label}...")
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda s=script: subprocess.run(
                    [sys.executable, os.path.join(BASE_DIR, s), "--force", "--once"],
                    cwd=BASE_DIR, capture_output=True, text=True, timeout=120
                ),
            )
            if result.returncode == 0:
                logger.info(f"[自动刷新] {label} ✅ 更新成功")
            else:
                stderr = (result.stderr or "")[-300:]
                logger.warning(f"[自动刷新] {label} ⚠️ 返回码 {result.returncode}: {stderr}")
        except Exception as e:
            logger.error(f"[自动刷新] {label} ❌ 失败: {e}")

    # 低频数据过期仅提示
    for label, script in stale_manual:
        logger.warning(f"[数据检查] {label}已过期，请手动运行: python {script} --force --once")

    if not stale_auto and not stale_manual:
        logger.info("[数据检查] 全部数据新鲜，无需更新 ✅")
    logger.info("[数据检查] ========== 检查完成 ==========")


# ============ 请求模型 ============
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500,
                       description="用户查询，1-500字符")
    source_filter: Optional[str] = Field(None, max_length=50,
                                         description="意图过滤")
    session_id: Optional[str] = Field(None, max_length=64,
                                      description="会话ID")

    @field_validator('query')
    @classmethod
    def sanitize_query(cls, v: str) -> str:
        """清理输入：去除首尾空白，移除 \\x00 等控制字符"""
        import re
        v = v.strip()
        v = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', v)
        if not v:
            raise ValueError('查询内容不能为空')
        return v


# ============ 工具函数 ============
def check_greeting(query: str) -> Optional[str]:
    """检查是否为日常问候，返回预设回复"""
    for pattern, response in GREETING_PATTERNS:
        if re.match(pattern, query.strip(), re.IGNORECASE):
            return response
    return None


def _get_memory() -> MemoryManager:
    """获取全局记忆管理器（startup 未触发时懒初始化）。"""
    global memory
    if memory is None:
        memory = MemoryManager(conf)
    return memory


async def _consolidate_memory(session_id: str):
    """后台巩固记忆：滚动摘要 + 长期记忆抽取（不阻塞主链路）。"""
    await asyncio.to_thread(_get_memory().consolidate, session_id)


# ============ A2A Orchestrator 调用 ============
@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((Exception,)),
    before_sleep=lambda retry_state: logger.warning(
        f"Orchestrator 调用重试 {retry_state.attempt_number}/2..."
    )
)
async def call_orchestrator(query: str, conversation_history: str, on_progress=None) -> AgentResult:
    """把查询发送给 OrchestratorAgent，返回结构化结果（区分结果 / 追问，自动重试最多 2 次）。

    Orchestrator 负责意图识别、路由委派与结果聚合，网关不再直连
    CourseQueryAssistant / FacilityQueryAssistant，也不直接处理天气/推荐。

    on_progress: 可选回调，逐条接收 orchestrator 上报的阶段（dict：stage/label/ts）。
    """
    start = time.perf_counter()
    status = "error"
    try:
        if agent_network is None:
            raise RuntimeError("AgentNetwork 未初始化（请确保 startup 事件已触发）")
        agent = agent_network.get_agent("OrchestratorAgent")
        agent.timeout = 180  # 规划链路多级 LLM，默认 30s 会读超时
        # 用 JSON payload 同时传递查询与对话历史（Orchestrator 无状态，历史随任务注入）
        payload = json.dumps(
            {"query": query, "conversation_history": conversation_history},
            ensure_ascii=False,
        )
        trace_id = get_trace_id()
        message = Message(content=TextContent(text=payload), role=MessageRole.USER)
        message_dict = message.to_dict()
        message_dict["_trace_id"] = trace_id
        task = Task(id="task-" + str(uuid.uuid4()), message=message_dict)

        with span("a2a_call_orchestrator", {"agent_name": "OrchestratorAgent"}):
            # 后台阻塞等最终结果 + 前台轮询 orchestrator 进度端点
            raw_response = await await_task_with_progress(
                agent.send_task_async(task),
                conf.orchestrator_url,
                trace_id,
                on_progress=on_progress,
            )
            state = str(raw_response.status.state)
            logger.info(f"OrchestratorAgent 响应状态: {state}")
            status = state

            if state == 'completed':
                return AgentResult("completed", raw_response.artifacts[0]['parts'][0]['text'])
            return AgentResult(state, status_message_text(raw_response.status.message))
    finally:
        elapsed = time.perf_counter() - start
        a2a_agent_calls_total.labels(agent_name="OrchestratorAgent", status=status).inc()
        a2a_agent_call_duration_seconds.labels(agent_name="OrchestratorAgent").observe(elapsed)


# ============ 核心处理逻辑（生成器版本，用于 WebSocket 流式） ============
async def process_query_stream(query: str, session_id: str):
    """流式处理查询，逐 token yield"""
    mem = _get_memory()

    # 召回分层记忆上下文（工作窗口 + 语义记忆 + 滚动摘要）
    history_text = await asyncio.to_thread(mem.recall, session_id, query)

    # 持久化本轮用户消息，并后台巩固（滚动摘要 + 长期记忆抽取）
    await asyncio.to_thread(mem.save, session_id, "user", query)
    asyncio.create_task(_consolidate_memory(session_id))

    # 问候检查
    greeting = check_greeting(query)
    if greeting:
        await asyncio.to_thread(mem.save, session_id, "assistant", greeting)
        yield greeting, True, None
        return

    # 交给 OrchestratorAgent：后台等最终结果 + 前台轮询进度（经 queue 实时上抛）
    progress_queue: asyncio.Queue = asyncio.Queue()

    def _on_progress(stage: dict):
        progress_queue.put_nowait(stage)

    orch_task = asyncio.create_task(
        call_orchestrator(query, history_text, on_progress=_on_progress)
    )

    stages = []
    while not orch_task.done():
        try:
            stage = progress_queue.get_nowait()
            stages.append(stage)
            yield "", False, {"progress": stage}
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.2)

    try:
        result = await orch_task
    except Exception as e:
        logger.error(f"Orchestrator 调用失败: {e}")
        result = AgentResult("failed", "抱歉，校园助手服务暂时不可达，请稍后重试。")

    # 记录助手回复
    await asyncio.to_thread(mem.save, session_id, "assistant", result.text)
    yield result.text, True, {"needs_input": result.needs_input, "stages": stages}


# ============ API 路由 ============
@app.get("/")
async def root():
    """返回前端页面"""
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


@app.post("/api/create_session")
async def create_session():
    """创建新会话（记忆按需落库，无需预分配）"""
    session_id = str(uuid.uuid4())
    logger.info(f"新会话创建: {session_id[:8]}...")
    return {"session_id": session_id}


@app.get("/api/history/{session_id}")
async def get_history(session_id: str):
    """获取会话历史（从持久化记忆读取）"""
    history = _get_memory().get_history(session_id)
    return {"session_id": session_id, "history": history}


@app.delete("/api/history/{session_id}")
async def clear_history(session_id: str):
    """清除会话历史（消息 + 摘要；长期记忆为跨会话资产，保留）"""
    _get_memory().clear(session_id)
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
            {"value": "transport", "label": "🚌 校巴交通"},
            {"value": "planning", "label": "🗓️ 日程规划"},
        ]
    }


@app.post("/api/query")
async def query_api(request: QueryRequest):
    """非流式查询接口"""
    start_time = time.time()
    session_id = request.session_id or str(uuid.uuid4())

    full_response = ""
    needs_input = False
    async for token, is_complete, meta in process_query_stream(request.query, session_id):
        # 只取最终回答（跳过阶段进度 yield）
        if is_complete:
            full_response = token
            if meta and meta.get("needs_input"):
                needs_input = True

    return {
        "answer": full_response,
        "is_streaming": False,
        "needs_input": needs_input,
        "session_id": session_id,
        "processing_time": round(time.time() - start_time, 3)
    }


@app.websocket("/api/stream")
async def stream_api(websocket: WebSocket):
    """WebSocket 流式查询接口"""
    await websocket.accept()
    websocket_connections.inc()

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

            # 流式处理（带 trace span）
            accumulated = ""
            needs_input = False
            with span("websocket_query", {"query": query[:100]}):
                async for token, is_complete, meta in process_query_stream(query, session_id):
                    if meta and meta.get("progress"):
                        # 阶段进度事件
                        await websocket.send_json({
                            "type": "progress",
                            "stage": meta["progress"],
                            "session_id": session_id,
                        })
                    elif meta and meta.get("needs_input"):
                        # 追问：直接上抛 input_required 事件（不逐字符打字）
                        needs_input = True
                        accumulated = token
                        await websocket.send_json({
                            "type": "input_required",
                            "message": token,
                            "session_id": session_id,
                        })
                    else:
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
                "needs_input": needs_input,
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
        websocket_connections.dec()
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/health")
async def health_check():
    """增强健康检查：Web 自身 + A2A Agent + MCP Server 连通性"""
    import httpx as _httpx

    components = {"web_server": "ok"}

    # 检查编排 Agent 可达性（1.5s 超时）
    for name, port in [("OrchestratorAgent", 5007)]:
        try:
            async with _httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://127.0.0.1:{port}/.well-known/agent-card.json",
                    timeout=1.5
                )
                components[name] = "ok" if resp.status_code == 200 else f"status:{resp.status_code}"
        except Exception:
            components[name] = "unreachable"

    # 检查 MySQL 连通性
    try:
        conn = mysql.connector.connect(
            host=conf.host, user=conf.user,
            password=conf.password, database=conf.database,
            charset="utf8mb4", connection_timeout=2
        )
        conn.close()
        components["mysql"] = "ok"
    except Exception as e:
        components["mysql"] = f"error:{str(e)[:60]}"

    # 判断总体状态
    all_ok = all(v == "ok" for v in components.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "timestamp": datetime.now(TZ).isoformat(),
        "components": components,
    }


@app.get("/metrics")
async def metrics():
    """Prometheus 指标端点"""
    return PlainTextResponse(content=get_metrics(), media_type="text/plain; charset=utf-8")


# ============ 主入口 ============
if __name__ == "__main__":
    import uvicorn
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 8100))
    print(f"\n{'='*60}")
    print(f"  SmartCampus Web 服务器 v3.1")
    print(f"  访问地址: http://localhost:{port}")
    print(f"  API 文档:  http://localhost:{port}/docs")
    print(f"{'='*60}\n")
    uvicorn.run("app.server:app", host=host, port=port, reload=False)
