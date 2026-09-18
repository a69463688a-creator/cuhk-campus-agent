#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: progress.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/9/17
描述: 阶段级进度 + token 级输出流 上报基础设施。

解决「单向阻塞、黑盒等结果」问题：agent 处理过程中把业务阶段与最终回答的
增量输出写入本进程的 progress_store（以 trace_id 为 key），并通过自定义端点
GET /progress/<trace_id> 暴露；上层客户端（orchestrator / planner / web）在
「后台阻塞等最终结果」的同时，「前台轮询」该端点读取中间阶段与输出 token，
逐级上抛至前端。

设计要点：
  - 阶段级进度（stage）：粒度 = 业务阶段，与 observability 的 span 命名对应。
  - token 级输出流（output）：最终回答 LLM 用 astream 逐 token 累积，轮询端只取增量。
  - 线程安全：每个 agent 进程独立一个 progress_store，dict 读写由锁保护。
  - 不侵入 python_a2a：端点通过 override A2AServer.setup_routes 注册（见各 agent）。
  - trace 连续：全链路沿用同一个 _trace_id，各进程 /progress/<trace_id> 累积下游内容。
"""
import asyncio
import threading
import time
from typing import Awaitable, Callable, Optional

# ============ 阶段常量（与 observability span 命名对应） ============
STAGE_INTENT = "intent"           # 意图识别
STAGE_DECOMPOSE = "decompose"     # 拆解复合目标为子任务
STAGE_DELEGATE = "delegate"       # 委派 specialist / 并行查询
STAGE_CONFLICT = "conflict"       # 时间/地点冲突检测
STAGE_COMPOSE = "compose"         # 合成日程 / 聚合结果
STAGE_SQL = "sql"                 # 生成 SQL
STAGE_QUERY = "query"             # 执行 MCP 查询


class ProgressStore:
    """进程内进度存储：trace_id → {"stages": [...], "output": "..."}（线程安全）。"""

    def __init__(self):
        self._store = {}
        self._lock = threading.Lock()

    def record(self, trace_id: str, stage: str, label: str = ""):
        """记录一个阶段。trace_id 为空时不记录。"""
        if not trace_id:
            return
        entry = {"stage": stage, "label": label, "ts": round(time.time(), 3)}
        with self._lock:
            self._store.setdefault(trace_id, {"stages": [], "output": ""})["stages"].append(entry)

    def append_output(self, trace_id: str, text: str):
        """累积最终回答的输出增量（token 流）。trace_id 或 text 为空时忽略。"""
        if not trace_id or not text:
            return
        with self._lock:
            self._store.setdefault(trace_id, {"stages": [], "output": ""})["output"] += text

    def get(self, trace_id: str) -> list:
        """返回当前已记录的阶段列表（按时间有序）。"""
        with self._lock:
            rec = self._store.get(trace_id)
            return list(rec["stages"]) if rec else []

    def get_output(self, trace_id: str) -> str:
        """返回当前已累积的输出文本。"""
        with self._lock:
            rec = self._store.get(trace_id)
            return rec["output"] if rec else ""

    def clear(self, trace_id: str):
        """任务结束后清理，避免长期占用内存。"""
        with self._lock:
            self._store.pop(trace_id, None)


# 每个 agent 进程的全局单例（agent 独立进程，各持一份）
progress_store = ProgressStore()


def register_progress_endpoint(app, server) -> None:
    """在 A2AServer 的 Flask app 上注册 GET /progress/<trace_id>。

    各 agent 在 override setup_routes 时调用：
        super().setup_routes(app)
        register_progress_endpoint(app, self)
    """
    from flask import jsonify

    @app.route("/progress/<trace_id>", methods=["GET"])
    def get_progress(trace_id):
        return jsonify({
            "trace_id": trace_id,
            "stages": progress_store.get(trace_id),
            "output": progress_store.get_output(trace_id),
        })


async def fetch_progress(base_url: str, trace_id: str):
    """异步拉取指定 agent 进程已记录的进度，返回 (stages, output)。

    失败（端点不可达/超时）静默降级为 ([], "")。
    """
    import httpx

    url = f"{base_url.rstrip('/')}/progress/{trace_id}"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            return data.get("stages", []), data.get("output", "")
    except Exception:
        return [], ""


async def await_task_with_progress(
    send_coro: Awaitable,
    base_url: str,
    trace_id: str,
    on_progress: Optional[Callable[[dict], None]] = None,
    on_output: Optional[Callable[[str], None]] = None,
    poll_interval: float = 0.3,
):
    """后台阻塞等待 send_coro 完成，前台轮询 /progress/<trace_id> 上抛新增内容。

    返回 send_coro 的最终结果（Task）。阶段（dict：stage/label/ts）逐条回调给
    on_progress；输出增量（str）逐段回调给 on_output。无进度能力（端点不可达）
    时静默降级，等价于一次性等最终结果。
    """
    send_task = asyncio.ensure_future(send_coro)
    seen = 0
    seen_output_len = 0

    def _pump(stages: list, output: str):
        nonlocal seen, seen_output_len
        if len(stages) > seen:
            for s in stages[seen:]:
                if on_progress:
                    on_progress(s)
            seen = len(stages)
        if len(output) > seen_output_len:
            if on_output:
                on_output(output[seen_output_len:])
            seen_output_len = len(output)

    while not send_task.done():
        stages, output = await fetch_progress(base_url, trace_id)
        _pump(stages, output)
        if not send_task.done():
            await asyncio.sleep(poll_interval)

    # 收尾：最终结果已就绪，补拉一次确保阶段与输出完整上抛
    stages, output = await fetch_progress(base_url, trace_id)
    _pump(stages, output)
    return await send_task
