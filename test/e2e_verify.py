#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端验证脚本：验证 token 级流式 + 削减调用 + 反问闭环（子能力 C/D/E + A）。

前置：MySQL + 9 服务已启动（本脚本只做客户端验证，不启动服务）。
用法：python test/e2e_verify.py

速度口径：
  - 首进度延迟：从发起到收到首个 progress 事件（≈ 记忆召回 + 意图识别）。
  - 首 token 延迟：从发起到收到首个真实回答 token（流式后 ≈ 合成/summarize 开始的时刻）。
  - 总耗时：到 end 事件。
"""
import asyncio
import json
import sys
import time

import httpx
import websockets

BASE = "http://127.0.0.1:8100"
WS = "ws://127.0.0.1:8100/api/stream"

PLANNING_QUERY = "帮我规划周四下午：下课后去图书馆，再坐校巴回逸夫书院"
COURSE_QUERY = "CSCI2100 的上课时间和教室"
INPUT_REQUIRED_QUERY = "有什么课"  # course agent 判定缺课程代码 → input_required


async def stream_query(query: str, session_id: str, label: str) -> dict:
    """跑一次 WebSocket 流式，返回阶段序列与延迟指标。"""
    stages = []
    token_count = 0
    first_progress_ts = None
    first_token_ts = None
    needs_input = False
    t0 = time.perf_counter()

    print(f"\n--- [{label}] {query} ---")
    async with websockets.connect(WS) as ws:
        await ws.send(json.dumps({
            "query": query, "source_filter": None, "session_id": session_id,
        }))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=180)
            d = json.loads(raw)
            t = d.get("type")
            if t == "start":
                pass
            elif t == "progress":
                if first_progress_ts is None:
                    first_progress_ts = time.perf_counter()
                st = d.get("stage", {})
                stages.append(st.get("stage"))
                print(f"  [progress] {st.get('stage'):<10} {st.get('label')}")
            elif t == "token":
                if first_token_ts is None:
                    first_token_ts = time.perf_counter()
                token_count += 1
            elif t == "input_required":
                needs_input = True
                print(f"  [input_required] {d.get('message', '')[:60]}")
            elif t == "end":
                print(f"  [end] needs_input={d.get('needs_input')} "
                      f"processing_time={d.get('processing_time')}s")
                break
            elif t == "error":
                print(f"  [error] {d.get('error')}")
                break

    total = time.perf_counter() - t0
    metrics = {
        "label": label,
        "stages": stages,
        "first_progress": (first_progress_ts - t0) if first_progress_ts else None,
        "first_token": (first_token_ts - t0) if first_token_ts else None,
        "total": total,
        "token_count": token_count,
        "needs_input": needs_input,
    }
    print(f"  首进度: {metrics['first_progress']:.2f}s | "
          f"首 token: {metrics['first_token']:.2f}s | "
          f"总耗时: {total:.2f}s | token 事件: {token_count}")
    return metrics


async def test_planning_stream():
    """子能力 C/D/E：planning 应流式产出 token，且阶段为 拆解/委派/综合合成（冲突已合并）。"""
    m = await stream_query(PLANNING_QUERY, "e2e-planning", "planning 日程规划")

    received = set(m["stages"])
    ok_stream = m["token_count"] > 0 and m["first_token"] is not None
    ok_stages = {"intent", "decompose", "compose"}.issubset(received)
    ok_merged = "conflict" not in received  # 冲突检测已并入综合合成
    print(f"  ✓/✗ 流式产出 token: {'✓' if ok_stream else '✗'}")
    print(f"  ✓/✗ 阶段含 intent/decompose/compose: {'✓' if ok_stages else '✗'}  (实际: {m['stages']})")
    print(f"  ✓/✗ 冲突检测已合并(无 conflict 阶段): {'✓' if ok_merged else '✗'}")
    return ok_stream and ok_stages and ok_merged


async def test_single_intent_stream():
    """子能力 C：单意图（课程）summarize 应流式产出 token。"""
    m = await stream_query(COURSE_QUERY, "e2e-course", "单意图 课程查询")
    ok_stream = m["token_count"] > 0 and m["first_token"] is not None
    ok_no_input = not m["needs_input"]
    print(f"  ✓/✗ 流式产出 token: {'✓' if ok_stream else '✗'}")
    print(f"  ✓/✗ 非追问返回结果: {'✓' if ok_no_input else '✗'}")
    return ok_stream and ok_no_input


async def test_input_required():
    """子能力 A：course 缺课程代码 → 返回 needs_input（反问而非结果）。"""
    print(f"\n--- [input-required 反问] {INPUT_REQUIRED_QUERY} ---")
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{BASE}/api/query", json={
            "query": INPUT_REQUIRED_QUERY, "session_id": "e2e-ir",
        })
        data = r.json()
    print(f"  needs_input: {data.get('needs_input')}")
    print(f"  answer: {data.get('answer', '')[:120]}")
    ok = bool(data.get("needs_input"))
    print(f"  ✓/✗ needs_input=True: {'✓' if ok else '✗'}")
    return ok


async def test_input_required_closure():
    """子能力 A（两轮闭环）：补充课程代码后重跑应返回结果。"""
    print("\n--- [两轮闭环] 第二轮补答 CSCI2100 ---")
    session_id = "e2e-ir"
    async with httpx.AsyncClient(timeout=120) as client:
        r1 = await client.post(f"{BASE}/api/query", json={
            "query": INPUT_REQUIRED_QUERY, "session_id": session_id,
        })
        d1 = r1.json()
        print(f"  第一轮 needs_input: {d1.get('needs_input')}")

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
    results["planning_stream"] = await test_planning_stream()
    results["single_intent_stream"] = await test_single_intent_stream()
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
