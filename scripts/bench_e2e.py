#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: bench_e2e.py
项目: SmartCampus — 端到端延迟基准测试
描述: 通过 /api/query 发送自然语言查询，测量完整链路延迟
      （意图识别 LLM → A2A Agent SQL 生成 LLM → MCP → MySQL → 汇总 LLM），
      输出 mean / P50 / P95 / P99，用于简历「项目成果」端到端指标。
用法: PYTHONPATH=. python scripts/bench_e2e.py
"""
import time
import json
import statistics
import requests

BASE = "http://127.0.0.1:8100"
WARMUP = 1   # 每条查询预热次数（触发 schema 缓存等）
RUNS = 6     # 每条查询测量次数

# 代表性自然语言查询（覆盖 2 个 Agent / 5 张表）
QUERIES = {
    "course_code": "CSCI2100 的上课时间和地点",
    "course_name": "Data Structures 这门课的老师是谁",
    "canteen": "崇基学院有什么餐厅",
    "event": "最近有什么校园讲座",
    "news": "最近有什么校园新闻",
    "library": "大学图书馆今天几点开门",
}


def pct(data, q):
    s = sorted(data)
    if not s:
        return 0.0
    k = (len(s) - 1) * q
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def one_query(query):
    t0 = time.perf_counter()
    r = requests.post(
        f"{BASE}/api/query",
        json={"query": query},
        timeout=60,
    )
    wall = (time.perf_counter() - t0) * 1000
    r.raise_for_status()
    body = r.json()
    return wall, body.get("processing_time", 0.0) * 1000, body.get("answer", "")


def main():
    results = {}
    for name, query in QUERIES.items():
        # 预热
        for _ in range(WARMUP):
            try:
                one_query(query)
            except Exception as e:
                print(f"  预热失败 {name}: {e}")

        wall_samples, proc_samples = [], []
        for i in range(RUNS):
            try:
                wall, proc, answer = one_query(query)
                wall_samples.append(wall)
                proc_samples.append(proc)
                ans_preview = answer.strip().replace("\n", " ")[:50]
                print(f"  {name:<12} #{i+1} wall={wall:7.0f}ms api={proc:7.0f}ms | {ans_preview}")
            except Exception as e:
                print(f"  {name:<12} #{i+1} 失败: {e}")

        results[name] = (wall_samples, proc_samples)
        print(
            f"  {name:<12} → wall mean={statistics.mean(wall_samples):8.0f}ms "
            f"P50={pct(wall_samples, 0.5):7.0f}ms P95={pct(wall_samples, 0.95):7.0f}ms "
            f"P99={pct(wall_samples, 0.99):7.0f}ms"
            if wall_samples else f"  {name:<12} → 无有效样本"
        )
        print()

    print("=" * 90)
    print("端到端延迟汇总（客户端墙钟 wall time）：")
    for name, (wall, proc) in results.items():
        if wall:
            print(f"  {name:<12} n={len(wall)} mean={statistics.mean(wall):7.0f}ms "
                  f"P50={pct(wall, 0.5):7.0f}ms P95={pct(wall, 0.95):7.0f}ms "
                  f"P99={pct(wall, 0.99):7.0f}ms")
    print("=" * 90)

    # 输出 JSON 供后续引用
    with open("logs/bench_e2e.json", "w", encoding="utf-8") as f:
        json.dump({k: {"wall_ms": v[0], "api_ms": v[1]} for k, v in results.items()},
                  f, ensure_ascii=False, indent=2)
    print("结果已写入 logs/bench_e2e.json")


if __name__ == "__main__":
    main()
