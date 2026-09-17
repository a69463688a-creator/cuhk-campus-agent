#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: test_streaming_feedback.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/9/17
描述: A2A 流式中间反馈与反问闭环 单元测试

不依赖真实 MySQL / MCP / A2A 服务，聚焦可独立验证的核心逻辑：
  - AgentResult.needs_input（input-required 语义识别）
  - status_message_text（TaskStatus.message 多形态提取）
  - ProgressStore（阶段记录 / 有序 / 清理 / 空 trace 忽略）
  - await_task_with_progress（后台阻塞 + 前台轮询上抛，按序无重复）
"""
import asyncio

from app.a2a_types import AgentResult, status_message_text
from app.progress import ProgressStore, await_task_with_progress
import app.progress as progress_mod


# ============ 反问闭环：input-required 语义识别 ============
def test_agent_result_needs_input():
    assert AgentResult("input-required", "请提供课程代码或名称").needs_input is True
    assert AgentResult("completed", "正常结果").needs_input is False
    assert AgentResult("failed", "查询失败").needs_input is False


def test_task_state_value_is_canonical_string():
    """回归：TaskState 是 (str, Enum)，str(member) 得 'TaskState.COMPLETED' 而非 'completed'。

    委派链路必须用 .value 取规范字符串；否则 `state == 'completed'` 判定失效，
    结果被当成「非 completed」返回空文本（曾导致端到端空回答）。"""
    from python_a2a import TaskState

    assert TaskState.COMPLETED.value == "completed"
    assert TaskState.INPUT_REQUIRED.value == "input-required"
    assert TaskState.FAILED.value == "failed"
    # 陷阱守护：str(member) 不是值本身
    assert str(TaskState.COMPLETED) != "completed"
    assert str(TaskState.INPUT_REQUIRED) != "input-required"
    # 用 .value 构造的 AgentResult 判定正确
    assert AgentResult(TaskState.COMPLETED.value, "x").needs_input is False
    assert AgentResult(TaskState.INPUT_REQUIRED.value, "x").needs_input is True


def test_status_message_text_variants():
    # dict: content 为 dict（含 text）
    assert status_message_text({"role": "agent", "content": {"text": "追问文本"}}) == "追问文本"
    # dict: content 为 str
    assert status_message_text({"role": "agent", "content": "纯文本内容"}) == "纯文本内容"
    # 直接 str
    assert status_message_text("直接字符串") == "直接字符串"
    # None / 空
    assert status_message_text(None) == ""


# ============ 阶段进度：ProgressStore ============
def test_progress_store_records_in_order():
    store = ProgressStore()
    store.record("t1", "intent", "识别意图")
    store.record("t1", "query", "查询")
    assert [s["stage"] for s in store.get("t1")] == ["intent", "query"]
    assert [s["label"] for s in store.get("t1")] == ["识别意图", "查询"]

    store.clear("t1")
    assert store.get("t1") == []

    # 空 trace_id 不记录
    store.record("", "sql", "x")
    assert store.get("") == []


# ============ 阶段进度：轮询上抛（按序、无重复、降级不阻塞） ============
def test_await_task_with_progress_forwards_new_stages(monkeypatch):
    stages = [
        {"stage": "intent", "label": "识别意图", "ts": 1.0},
        {"stage": "query", "label": "查询", "ts": 1.1},
        {"stage": "compose", "label": "聚合", "ts": 1.2},
    ]
    calls = {"n": 0}

    async def fake_fetch(base_url, trace_id):
        calls["n"] += 1
        return stages[: min(calls["n"], len(stages))]

    monkeypatch.setattr(progress_mod, "fetch_progress", fake_fetch)

    async def fake_send():
        await asyncio.sleep(0.06)
        return "DONE"

    received = []
    result = asyncio.run(await_task_with_progress(
        fake_send(), "http://localhost", "t1",
        on_progress=received.append, poll_interval=0.005,
    ))

    assert result == "DONE"
    assert received == stages  # 按序、无重复


def test_await_task_with_progress_degrades_when_no_progress(monkeypatch):
    """无进度能力（端点不可达/返回空）时静默降级，等价于一次性等最终结果。"""
    async def fake_fetch(base_url, trace_id):
        return []  # 永远无进度

    monkeypatch.setattr(progress_mod, "fetch_progress", fake_fetch)

    async def fake_send():
        await asyncio.sleep(0.01)
        return "RESULT"

    received = []
    result = asyncio.run(await_task_with_progress(
        fake_send(), "http://localhost", "t1",
        on_progress=received.append, poll_interval=0.005,
    ))

    assert result == "RESULT"
    assert received == []
