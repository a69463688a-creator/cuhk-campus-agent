#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: observability.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/8/11
描述: 可观测性基础设施 — Trace 上下文传播 + Span 计时 + Prometheus 指标

设计原则:
  1. 零外部依赖的 Trace 传播: 基于 contextvars 实现跨 async/sync 的 trace_id 传递
  2. 结构化日志 Span: 每个 Span 的 start/end 以 JSON 写入日志，可用 jq 查询
  3. Prometheus 指标: Counter + Histogram，在 Web 进程暴露 /metrics 端点
  4. 跨进程传播: trace_id 通过 A2A Task metadata 和 MCP _meta 字段传递

架构:
  Web Server (FastAPI)
    ├── TraceMiddleware: 为每个请求生成 trace_id
    ├── /metrics: Prometheus 指标端点
    └── span("http_request") → span("recognize_intent") → span("call_agent")
                                                                  │
  Agent Server (A2A)                                             │
    ├── 从 Task metadata 提取 trace_id                            │
    └── span("llm_generate_sql") → span("mcp_call_tool") ────────┘
                                                                  │
  MCP Server                                                      │
    └── span("db_query") → span("sql_validate") → span("sql_execute")
"""

import contextvars
import time
import uuid
import json
import functools
import logging
from contextlib import contextmanager
from typing import Optional, Dict, Any, Callable

# ============================================================================
# Trace Context (contextvars — 自动跨 asyncio Task 传播)
# ============================================================================

_trace_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "trace_id", default=None
)
_span_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "span_id", default=None
)


def new_trace_id() -> str:
    """生成 16 字符 hex trace_id"""
    return uuid.uuid4().hex[:16]


def new_span_id() -> str:
    """生成 8 字符 hex span_id"""
    return uuid.uuid4().hex[:8]


def get_trace_id() -> Optional[str]:
    """获取当前协程/线程的 trace_id"""
    return _trace_id.get()


def set_trace_id(tid: str) -> None:
    """设置当前协程/线程的 trace_id"""
    _trace_id.set(tid)


def get_span_id() -> Optional[str]:
    """获取当前协程/线程的 span_id"""
    return _span_id.get()


# ============================================================================
# Span — 轻量级计时上下文管理器
# ============================================================================

# 使用标准 logging 避免循环导入
_obs_logger = logging.getLogger("SmartCampus.observability")


@contextmanager
def span(
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    parent_trace_id: Optional[str] = None,
    parent_span_id: Optional[str] = None,
):
    """
    轻量级 Span 上下文管理器。

    用法:
        with span("llm_generate_sql", {"model": "deepseek-v4"}):
            result = llm.invoke(prompt)

    输出日志 (JSON Lines):
        {"event":"span.start","trace_id":"a1b2...","span_id":"c3d4...","name":"llm_generate_sql",...}
        {"event":"span.end","trace_id":"a1b2...","span_id":"c3d4...","duration_ms":1234.5,"status":"ok"}

    参数:
        name:              Span 名称 (如 "http_request", "llm_call", "db_query")
        attributes:        附加属性 (如 {"sql": "...", "model": "deepseek"})
        parent_trace_id:   显式指定父 trace_id (跨进程传播时使用)
        parent_span_id:    显式指定父 span_id
    """
    sid = new_span_id()
    tid = parent_trace_id or get_trace_id() or new_trace_id()
    parent_sid = parent_span_id or get_span_id()

    # 推入 context
    token_tid = _trace_id.set(tid)
    token_sid = _span_id.set(sid)

    start = time.perf_counter()
    attrs = attributes or {}

    # Span start 日志
    start_log = json.dumps(
        {
            "event": "span.start",
            "trace_id": tid,
            "span_id": sid,
            "parent_span_id": parent_sid,
            "name": name,
            "attributes": attrs,
        },
        ensure_ascii=False,
        default=str,
    )
    _obs_logger.debug(start_log)

    try:
        yield sid
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        end_log = json.dumps(
            {
                "event": "span.end",
                "trace_id": tid,
                "span_id": sid,
                "name": name,
                "duration_ms": round(elapsed_ms, 2),
                "status": "error",
                "error": str(exc),
            },
            ensure_ascii=False,
        )
        _obs_logger.warning(end_log)
        raise
    else:
        elapsed_ms = (time.perf_counter() - start) * 1000
        end_log = json.dumps(
            {
                "event": "span.end",
                "trace_id": tid,
                "span_id": sid,
                "name": name,
                "duration_ms": round(elapsed_ms, 2),
                "status": "ok",
            },
            ensure_ascii=False,
        )
        _obs_logger.debug(end_log)
    finally:
        _trace_id.reset(token_tid)
        _span_id.reset(token_sid)


# ============================================================================
# @trace 装饰器 — 自动包裹函数为 Span
# ============================================================================

def trace(_func=None, *, name: str = None, attrs: Dict[str, Any] = None):
    """
    装饰器: 将函数调用包裹在 span 中。

    用法:
        @trace
        def my_func(): ...

        @trace(name="custom_name", attrs={"key": "val"})
        async def my_async_func(): ...
    """

    def decorator(f):
        span_name = name or f.__qualname__

        @functools.wraps(f)
        def sync_wrapper(*args, **kwargs):
            with span(span_name, attributes=attrs):
                return f(*args, **kwargs)

        @functools.wraps(f)
        async def async_wrapper(*args, **kwargs):
            with span(span_name, attributes=attrs):
                return await f(*args, **kwargs)

        import asyncio

        if asyncio.iscoroutinefunction(f):
            return async_wrapper
        return sync_wrapper

    if _func is not None:
        return decorator(_func)
    return decorator


# ============================================================================
# TraceFilter — 将 trace_id 注入每条日志记录
# ============================================================================

class TraceFilter(logging.Filter):
    """注入 trace_id 和 span_id 到 LogRecord，使所有日志可关联"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id() or "-"
        record.span_id = get_span_id() or "-"
        return True


# ============================================================================
# Prometheus 指标
# ============================================================================

try:
    from prometheus_client import Counter, Histogram, Gauge, generate_latest, REGISTRY

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

    # 降级: 无 prometheus_client 时用空实现
    class _NoopMetric:
        def labels(self, **kw):
            return self

        def inc(self, val=1):
            pass

        def observe(self, val):
            pass

        def set(self, val):
            pass

    Counter = Histogram = Gauge = lambda *a, **kw: _NoopMetric()
    generate_latest = lambda: b"# prometheus_client not installed\n"
    REGISTRY = None


# HTTP 指标
http_requests_total = Counter(
    "http_requests_total",
    "HTTP 请求总数",
    ["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP 请求耗时 (秒)",
    ["method", "endpoint"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# LLM 调用指标
agent_llm_calls_total = Counter(
    "agent_llm_calls_total",
    "Agent LLM 调用次数",
    ["agent_name", "status"],
)

agent_llm_duration_seconds = Histogram(
    "agent_llm_duration_seconds",
    "Agent LLM 调用耗时 (秒)",
    ["agent_name"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

# MCP 工具调用指标
mcp_tool_calls_total = Counter(
    "mcp_tool_calls_total",
    "MCP 工具调用次数",
    ["server", "tool", "status"],
)

mcp_tool_call_duration_seconds = Histogram(
    "mcp_tool_call_duration_seconds",
    "MCP 工具调用耗时 (秒)",
    ["server", "tool"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0],
)

# 数据库查询指标
db_query_duration_seconds = Histogram(
    "db_query_duration_seconds",
    "数据库查询耗时 (秒)",
    ["service"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
)

# A2A Agent 调用指标
a2a_agent_calls_total = Counter(
    "a2a_agent_calls_total",
    "A2A Agent 调用次数",
    ["agent_name", "status"],
)

a2a_agent_call_duration_seconds = Histogram(
    "a2a_agent_call_duration_seconds",
    "A2A Agent 调用耗时 (秒)",
    ["agent_name"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

# 系统中活跃的 WebSocket 连接数
websocket_connections = Gauge(
    "websocket_connections_active",
    "活跃 WebSocket 连接数",
)


def get_metrics() -> bytes:
    """返回 Prometheus 文本格式的指标"""
    return generate_latest()


__all__ = [
    # Trace
    "span",
    "trace",
    "new_trace_id",
    "new_span_id",
    "get_trace_id",
    "set_trace_id",
    "get_span_id",
    "TraceFilter",
    # Metrics
    "http_requests_total",
    "http_request_duration_seconds",
    "agent_llm_calls_total",
    "agent_llm_duration_seconds",
    "mcp_tool_calls_total",
    "mcp_tool_call_duration_seconds",
    "db_query_duration_seconds",
    "a2a_agent_calls_total",
    "a2a_agent_call_duration_seconds",
    "websocket_connections",
    "get_metrics",
]
