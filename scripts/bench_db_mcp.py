#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: bench_db_mcp.py
项目: SmartCampus — 数据层延迟基准测试
描述: 测量「MySQL 直连 SQL 查询」与「MCP 工具调用（HTTP 往返 + 校验 + SQL）」两层延迟，
      输出 mean / P50 / P95 / P99，用于简历「项目成果」查询速度指标。
用法: PYTHONPATH=. python scripts/bench_db_mcp.py
"""
import time
import json
import statistics
import asyncio

import mysql.connector
from mcp import Client

from app.config import Config

conf = Config()
RUNS_DB = 50     # 直连 SQL 每查询重复次数
RUNS_MCP = 20    # MCP 工具调用每查询重复次数

# 代表性查询（课程 2 条 + 设施 4 条，覆盖全部 5 张表）
DB_QUERIES = {
    "course_code_exact": "SELECT course_code, course_name, department, instructor, schedule_day, start_time, end_time, classroom, building, credits, capacity, enrolled, category FROM course_info WHERE course_code = 'CSCI2100'",
    "course_name_like": "SELECT course_code, course_name, department, instructor, schedule_day, start_time, end_time, classroom, building, credits, capacity, enrolled, category FROM course_info WHERE course_name LIKE '%Data Structures%'",
    "canteen_open": "SELECT id, name, location, opening_hours, phone, category, status FROM canteen WHERE status = 'Open'",
    "event_recent": "SELECT id, event_name, organizer, venue, start_time, end_time, category, total_capacity, registered, description FROM campus_events ORDER BY start_time DESC LIMIT 10",
    "news_recent": "SELECT id, title, source, category, publish_date, summary, url FROM campus_news ORDER BY publish_date DESC LIMIT 10",
    "library_univ": "SELECT id, library_name, area, day_of_week, date, open_time, close_time, is_closed FROM library_hours WHERE library_name LIKE '%University Library%'",
}


def pct(data, q):
    """线性插值分位数"""
    s = sorted(data)
    if not s:
        return 0.0
    k = (len(s) - 1) * q
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def summarize(label, samples_ms):
    return (
        f"{label:<22} n={len(samples_ms):<3} "
        f"mean={statistics.mean(samples_ms):8.2f}ms "
        f"P50={pct(samples_ms, 0.50):7.2f}ms "
        f"P95={pct(samples_ms, 0.95):7.2f}ms "
        f"P99={pct(samples_ms, 0.99):7.2f}ms"
    )


def bench_db():
    print("\n" + "=" * 90)
    print("【第 1 层】MySQL 直连 SQL 查询延迟（本地库，无 HTTP/协议开销）")
    print("=" * 90)
    conn = mysql.connector.connect(
        host=conf.host, user=conf.user, password=conf.password,
        database=conf.database, charset="utf8mb4",
    )
    all_results = {}
    for name, sql in DB_QUERIES.items():
        samples = []
        # 预热
        cur = conn.cursor(dictionary=True)
        cur.execute(sql); cur.fetchall(); cur.close()
        for _ in range(RUNS_DB):
            cur = conn.cursor(dictionary=True)
            t0 = time.perf_counter()
            cur.execute(sql)
            cur.fetchall()
            dt = (time.perf_counter() - t0) * 1000
            samples.append(dt)
            cur.close()
        all_results[name] = samples
        print(summarize(name, samples))
    conn.close()
    return all_results


def bench_mcp():
    print("\n" + "=" * 90)
    print("【第 2 层】MCP 工具调用延迟（HTTP 往返 + 只读校验 + SQL + JSON 序列化）")
    print("=" * 90)
    mcp_cases = [
        ("course/query_courses", conf.mcp_course_url, "query_courses",
         {"sql": DB_QUERIES["course_code_exact"]}),
        ("course/query_courses", conf.mcp_course_url, "query_courses",
         {"sql": DB_QUERIES["course_name_like"]}),
        ("facility/query_facilities", conf.mcp_facility_url, "query_facilities",
         {"sql": DB_QUERIES["canteen_open"]}),
        ("facility/query_facilities", conf.mcp_facility_url, "query_facilities",
         {"sql": DB_QUERIES["event_recent"]}),
        ("facility/query_facilities", conf.mcp_facility_url, "query_facilities",
         {"sql": DB_QUERIES["library_univ"]}),
    ]

    async def _run():
        results = {}
        for key, url, tool, args in mcp_cases:
            samples = []
            # 预热
            async with Client(url) as client:
                await client.call_tool(tool, args)
            for _ in range(RUNS_MCP):
                async with Client(url) as client:
                    t0 = time.perf_counter()
                    await client.call_tool(tool, args)
                    dt = (time.perf_counter() - t0) * 1000
                    samples.append(dt)
            results[key] = samples
            print(summarize(key, samples))
        return results

    return asyncio.run(_run())


if __name__ == "__main__":
    db_results = bench_db()
    mcp_results = bench_mcp()
    print("\n" + "=" * 90)
    print("汇总（P50 延迟）：")
    for name, samples in {**db_results, **mcp_results}.items():
        print(f"  {name:<22} P50 = {pct(samples, 0.50):.2f}ms")
    print("=" * 90)
