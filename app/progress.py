#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: progress.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/9/17
描述: 阶段级进度上报基础设施。

解决「单向阻塞、黑盒等结果」问题：agent 处理过程中把业务阶段写入本进程的
progress_store（以 trace_id 为 key），并通过自定义端点 GET /progress/<trace_id>
暴露；上层客户端（orchestrator / planner / web）在「后台阻塞等最终结果」的同时，
「前台轮询」该端点读取中间阶段，逐级上抛至前端。

设计要点：
  - 阶段级（非 token 级）：粒度 = 业务阶段，与 observability 的 span 命名对应。
  - 线程安全：每个 agent 进程独立一个 progress_store，dict 读写由锁保护。
  - 不侵入 python_a2a：端点通过 override A2AServer.setup_routes 注册（见各 agent）。
  - trace 连续：全链路沿用同一个 _trace_id，各进程 /progress/<trace_id> 累积下游阶段。
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
    """进程内进度存储：trace_id → 有序阶段列表（线程安全）。"""

    def __init__(self):
        self._store = {}
        self._lock = threading.Lock()

    def record(self, trace_id: str, stage: str, label: str = ""):
        """记录一个阶段。trace_id 为空时不记录。"""
        if not trace_id:
            return
        entry = {"stage": stage, "label": label, "ts": round(time.time(), 3)}
        with self._lock:
            self._store.setdefault(trace_id, []).append(entry)

    def get(self, trace_id: str) -> list:
        """返回当前已记录的阶段列表（按时间有序）。"""
        with self._lock:
            return list(self._store.get(trace_id, []))

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
        return jsonify({"trace_id": trace_id, "stages": progress_store.get(trace_id)})


async def fetch_progress(base_url: str, trace_id: str) -> list:
    """异步拉取指定 agent 进程已记录到的阶段列表（失败静默返回空列表）。"""
    import httpx

    url = f"{base_url.rstrip('/')}/progress/{trace_id}"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json().get("stages", [])
    except Exception:
        return []


async def await_task_with_progress(
    send_coro: Awaitable,
    base_url: str,
    trace_id: str,
    on_progress: Optional[Callable[[dict], None]] = None,
    poll_interval: float = 0.3,
):
    """后台阻塞等待 send_coro 完成，前台轮询 /progress/<trace_id> 上抛新增阶段。

    返回 send_coro 的最终结果（Task）。阶段以 dict（含 stage/label/ts）逐条回调给
    on_progress；无进度能力（端点不可达）时静默降级，等价于一次性等最终结果。
    """
    send_task = asyncio.ensure_future(send_coro)
    seen = 0

    def _pump(stages: list):
        nonlocal seen
        if len(stages) > seen:
            for s in stages[seen:]:
                if on_progress:
                    on_progress(s)
            seen = len(stages)

    while not send_task.done():
        _pump(await fetch_progress(base_url, trace_id))
        if not send_task.done():
            await asyncio.sleep(poll_interval)

    # 收尾：最终结果已就绪，补拉一次确保阶段完整上抛
    _pump(await fetch_progress(base_url, trace_id))
    return await send_task
