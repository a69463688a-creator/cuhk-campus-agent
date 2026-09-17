#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端验证脚本：验证 A2A 流式中间反馈 + 反问闭环（子能力 A/B）。

前置：MySQL + 9 服务已启动（本脚本只做客户端验证，不启动服务）。
用法：python test/e2e_verify.py
"""
import asyncio
import json
import sys

import httpx
import websockets

BASE = "http://127.0.0.1:8100"
WS = "ws://127.0.0.1:8100/api/stream"

PLANNING_QUERY = "帮我规划周四下午：下课后去图书馆，再坐校巴回逸夫书院"
INPUT_REQUIRED_QUERY = "有什么课"  # course agent 判定缺课程代码 → input_required


async def test_planning_progress():
    """子能力 B：planning 请求应依次收到阶段进度（拆解/委派/冲突/合成）。"""
    print("\n" + "=" * 60)
    print(f"[子能力 B] planning 阶段进度流 — 查询: {PLANNING_QUERY}")
    print("=" * 60)

    progress_events = []
    token_count = 0
    got_end = False

    async with websockets.connect(WS) as ws:
        await ws.send(json.dumps({
            "query": PLANNING_QUERY,
            "source_filter": None,
            "session_id": "e2e-planning",
        }))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=180)
            d = json.loads(raw)
            t = d.get("type")
            if t == "start":
                print(f"  [start] session={d.get('session_id')}")
            elif t == "progress":
                stage = d.get("stage", {})
                progress_events.append(stage)
                print(f"  [progress] {stage.get('stage'):<10} {stage.get('label')}")
            elif t == "token":
                token_count += 1
            elif t == "input_required":
                print(f"  [input_required] {d.get('message', '')[:60]}")
            elif t == "end":
                got_end = True
                print(f"  [end] needs_input={d.get('needs_input')} processing_time={d.get('processing_time')}s")
                break
            elif t == "error":
                print(f"  [error] {d.get('error')}")
                break

    stages = [s.get("stage") for s in progress_events]
    print(f"\n  收到的阶段序列: {stages}")
    print(f"  token 事件数: {token_count}, 收到 end: {got_end}")

    # 断言：至少收到 orchestrator 的意图/委派/合成 三阶段
    orchestrator_stages = {"intent", "delegate", "compose"}
    received = set(stages)
    ok_orch = orchestrator_stages.issubset(received)
    # 断言：planner 的拆解/冲突 两阶段（planning 意图会下派 planner）
    ok_planner = "decompose" in received and "conflict" in received
    print(f"  ✓/✗ orchestrator 三阶段(intent/delegate/compose): {'✓' if ok_orch else '✗'}")
    print(f"  ✓/✗ planner 拆解/冲突(decompose/conflict): {'✓' if ok_planner else '✗'}")
    return ok_orch and ok_planner


async def test_input_required():
    """子能力 A：course 缺课程代码 → 返回 needs_input（反问而非结果）。"""
    print("\n" + "=" * 60)
    print(f"[子能力 A] input-required 反问闭环 — 查询: {INPUT_REQUIRED_QUERY}")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{BASE}/api/query", json={
            "query": INPUT_REQUIRED_QUERY,
            "session_id": "e2e-ir",
        })
        data = r.json()
    print(f"  needs_input: {data.get('needs_input')}")
    print(f"  answer: {data.get('answer', '')[:120]}")
    ok = bool(data.get("needs_input"))
    print(f"  ✓/✗ needs_input=True: {'✓' if ok else '✗'}")
    return ok


async def test_input_required_closure():
    """子能力 A（两轮闭环）：补充课程代码后重跑应返回结果。"""
    print("\n" + "=" * 60)
    print("[子能力 A] 两轮闭环 — 第二轮补答 CSCI2100")
    print("=" * 60)

    # 复用同一 session_id，让历史注入
    session_id = "e2e-ir"
    async with httpx.AsyncClient(timeout=120) as client:
        # 第一轮：追问
        r1 = await client.post(f"{BASE}/api/query", json={
            "query": INPUT_REQUIRED_QUERY, "session_id": session_id,
        })
        d1 = r1.json()
        print(f"  第一轮 needs_input: {d1.get('needs_input')}")

        # 第二轮：补答
        r2 = await client.post(f"{BASE}/api/query", json={
            "query": "CSCI2100", "session_id": session_id,
        })
        d2 = r2.json()
        print(f"  第二轮 needs_input: {d2.get('needs_input')}")
        print(f"  第二轮 answer: {d2.get('answer', '')[:160]}")

    ok = (bool(d1.get("needs_input")) and not bool(d2.get("needs_input")))
    print(f"  ✓/✗ 闭环(第一轮追问→第二轮结果): {'✓' if ok else '✗'}")
    return ok


async def main():
    results = {}
    results["planning_progress"] = await test_planning_progress()
    results["input_required"] = await test_input_required()
    results["closure"] = await test_input_required_closure()

    print("\n" + "=" * 60)
    print("验证结果汇总")
    print("=" * 60)
    for k, v in results.items():
        print(f"  {'✓' if v else '✗'} {k}")
    all_ok = all(results.values())
    print(f"\n{'✅ 全部通过' if all_ok else '❌ 存在失败项'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
