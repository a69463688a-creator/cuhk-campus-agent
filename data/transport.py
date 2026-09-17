#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: transport.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/9/17
描述: 校园交通数据服务类 —— 封装 bus_routes / bus_stops 的 MySQL 查询 + 校巴路线规划图搜索

职责:
  - SQL 只读查询（复用 validate_readonly_sql）
  - 表结构返回
  - find_route: 站点图搜索（Dijkstra + 换乘惩罚）
  - compute_next_departure: 频次推算下一班车（纯函数，可单测）
"""
import heapq
import math
import re
import time
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

import mysql.connector

from app.config import Config
from app.logging import logger
from app.security import validate_readonly_sql
from app.observability import span, db_query_duration_seconds
from data.format import DateEncoder, default_encoder

conf = Config()

# 边权与换乘惩罚
HOP_COST = 1             # 走一站（对行程时间的代理，假定每段等长）
TRANSFER_PENALTY = 1000  # 换乘一次（须 > 全网最大站数，约 150 节点留足余量）

# 用户常见站点别名（简繁/简称 → canonical key）
STOP_ALIASES = {
    "大学站": "university-station",
    "大學站": "university-station",
    "中大站": "university-station",
    "本部": "central-campus",
    "行政楼": "central-campus",
    "崇基": "chung-chi-college",
    "崇基书院": "chung-chi-college",
    "崇基書院": "chung-chi-college",
    "新亚": "new-asia-college",
    "新亚书院": "new-asia-college",
    "新亞書院": "new-asia-college",
    "联合": "united-college",
    "联合书院": "united-college",
    "聯合書院": "united-college",
    "逸夫": "shaw-college",
    "逸夫书院": "shaw-college",
    "逸夫書院": "shaw-college",
}


def slugify(s: str) -> str:
    """把字符串转为 slug 形式的 canonical key（英文为主，纯中文原样小写）。"""
    if not s:
        return ""
    s = s.strip().lower()
    if re.search(r"[a-z]", s):
        return re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _to_minutes(t: str) -> int:
    hh, mm = t.split(":")
    return int(hh) * 60 + int(mm)


def compute_next_departure(first_bus, last_bus, frequency_min, now_str):
    """频次推算下一班车时间。

    返回 "HH:MM" 字符串；返回 None 表示「已过末班车」或数据缺失。
    """
    try:
        if not first_bus or not last_bus or not frequency_min:
            return None
        freq = int(frequency_min)
        if freq <= 0:
            return None
        now = _to_minutes(now_str)
        first = _to_minutes(first_bus)
        last = _to_minutes(last_bus)
        if now < first:
            return first_bus
        if now >= last:
            return None
        k = math.ceil((now - first) / freq)
        next_min = first + k * freq
        if next_min > last:
            return None
        hh, mm = divmod(next_min, 60)
        return f"{hh:02d}:{mm:02d}"
    except Exception:
        return None


class TransportService:
    """封装 bus_routes / bus_stops 的 MySQL 查询 + 路线规划"""

    _SCHEMA_TABLES = ["bus_routes", "bus_stops"]

    def __init__(self):
        self.host = conf.host
        self.port = conf.port
        self.user = conf.user
        self.password = conf.password
        self.database = conf.database
        self._connect()

    def _connect(self):
        self.conn = mysql.connector.connect(
            host=self.host, port=self.port, user=self.user,
            password=self.password, database=self.database,
        )

    def _ensure_connection(self):
        try:
            if not self.conn.is_connected():
                logger.warning("MySQL 连接已断开，正在重连...")
                self._connect()
                logger.info("MySQL 重连成功")
        except Exception:
            logger.warning("MySQL 连接检查失败，正在重连...")
            self._connect()
            logger.info("MySQL 重连成功")

    def execute_query(self, sql: str) -> str:
        start = time.perf_counter()
        try:
            validate_readonly_sql(sql)
            self._ensure_connection()
            with span("db_execute_query", {"service": "TransportService", "sql": sql[:200]}):
                cursor = self.conn.cursor(dictionary=True)
                cursor.execute(sql)
                results = cursor.fetchall()
                cursor.close()
            for result in results:
                for key, value in result.items():
                    if isinstance(value, (date, datetime, timedelta, Decimal)):
                        result[key] = default_encoder(value)
            return json.dumps(
                {"status": "success", "data": results} if results
                else {"status": "no_data", "message": "未找到相关数据，请确认查询条件。"},
                cls=DateEncoder, ensure_ascii=False
            )
        except Exception as e:
            logger.error(f"交通查询错误: {str(e)}")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
        finally:
            db_query_duration_seconds.labels(service="TransportService").observe(
                time.perf_counter() - start
            )

    def get_all_schemas(self) -> str:
        """返回 bus_routes / bus_stops 两张表的完整结构。"""
        try:
            self._ensure_connection()
            all_schemas = {}
            for table in self._SCHEMA_TABLES:
                cursor = self.conn.cursor(dictionary=True)
                cursor.execute(f"SHOW FULL COLUMNS FROM {table}")
                columns = cursor.fetchall()
                cursor.close()
                cursor = self.conn.cursor(dictionary=True)
                cursor.execute(f"SHOW INDEX FROM {table}")
                indexes = cursor.fetchall()
                cursor.close()
                for col in columns:
                    for key, value in col.items():
                        if isinstance(value, (date, datetime, timedelta, Decimal)):
                            col[key] = default_encoder(value)
                all_schemas[table] = {"columns": columns, "indexes": indexes}
            return json.dumps(
                {"status": "success", "schemas": all_schemas},
                cls=DateEncoder, ensure_ascii=False
            )
        except Exception as e:
            logger.error(f"获取交通表结构失败: {str(e)}")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

    # ── 图搜索 ──

    def _load_stops(self):
        """加载全部站点行（含中英文站名）。"""
        self._ensure_connection()
        cursor = self.conn.cursor(dictionary=True)
        cursor.execute("SELECT route_code, stop_order, stop_name, stop_name_en FROM bus_stops")
        rows = cursor.fetchall()
        cursor.close()
        return rows

    @staticmethod
    def _canonical(row) -> str:
        """行 → canonical key（英文名 slug 优先，否则中文名）。"""
        en = (row.get("stop_name_en") or "").strip()
        if en:
            return slugify(en)
        return slugify(row.get("stop_name") or "")

    def _build_graph(self):
        """由 bus_stops 现算邻接表 + 别名表 + 展示名表（不落库）。"""
        rows = self._load_stops()
        adj = defaultdict(list)
        names = {}   # canonical -> 中文名
        alias = {}   # 用户输入 -> canonical

        for k, v in STOP_ALIASES.items():
            alias[k.strip().lower()] = v

        by_route = defaultdict(list)
        for r in rows:
            by_route[r["route_code"]].append(r)

        for route_code, stops in by_route.items():
            stops.sort(key=lambda s: s["stop_order"])
            # 注册别名与展示名
            for s in stops:
                c = self._canonical(s)
                names[c] = s["stop_name"]
                for field in ("stop_name", "stop_name_en"):
                    val = s[field]
                    if val:
                        alias[val.strip().lower()] = c
            # 相邻站点连双向边
            for a, b in zip(stops, stops[1:]):
                ca = self._canonical(a)
                cb = self._canonical(b)
                adj[ca].append((cb, route_code))
                adj[cb].append((ca, route_code))

        return dict(adj), names, alias

    def find_route(self, origin: str, destination: str) -> str:
        """Dijkstra 图搜索：返回最少换乘、其次最少站数的行程。"""
        try:
            self._ensure_connection()
            adj, names, alias = self._build_graph()

            o_key = (origin or "").strip().lower()
            d_key = (destination or "").strip().lower()
            o_canon = alias.get(o_key, slugify(origin))
            d_canon = alias.get(d_key, slugify(destination))

            if o_canon == d_canon:
                return json.dumps({"status": "error", "message": "起点与终点相同。"}, ensure_ascii=False)
            if o_canon not in adj:
                return json.dumps({"status": "no_route", "message": f"未找到起点站「{origin}」。"}, ensure_ascii=False)
            if d_canon not in adj:
                return json.dumps({"status": "no_route", "message": f"未找到终点站「{destination}」。"}, ensure_ascii=False)

            # Dijkstra over (stop, route) 状态
            dist = {}
            prev = {}
            pq = []
            for _nxt, route in adj[o_canon]:
                state = (o_canon, route)
                dist[state] = 0
                heapq.heappush(pq, (0, state))

            best = None
            while pq:
                cost, (stop, route) = heapq.heappop(pq)
                if cost > dist.get((stop, route), float("inf")):
                    continue
                if stop == d_canon:
                    best = (stop, route)
                    break
                for nxt, r2 in adj.get(stop, []):
                    new_cost = cost + HOP_COST if r2 == route else cost + TRANSFER_PENALTY + HOP_COST
                    nxt_state = (nxt, r2)
                    if new_cost < dist.get(nxt_state, float("inf")):
                        dist[nxt_state] = new_cost
                        prev[nxt_state] = (stop, route)
                        heapq.heappush(pq, (new_cost, nxt_state))

            if best is None:
                return json.dumps({"status": "no_route", "message": "未找到可通行的路线。"}, ensure_ascii=False)

            # 回溯状态链
            states = []
            cur = best
            while cur in prev:
                states.append(cur)
                cur = prev[cur]
            states.append(cur)
            states.reverse()

            # 压缩成「乘车段」（换乘站同时属于前后两段：前段下车站 = 后段上车站）
            segments = []
            for stop, route in states:
                if segments and segments[-1]["route_code"] == route:
                    segments[-1]["stops"].append(stop)
                elif segments:
                    segments.append({"route_code": route, "stops": [segments[-1]["stops"][-1], stop]})
                else:
                    segments.append({"route_code": route, "stops": [stop]})

            itinerary = []
            for seg in segments:
                itinerary.append({
                    "route_code": seg["route_code"],
                    "board_stop": names.get(seg["stops"][0], seg["stops"][0]),
                    "alight_stop": names.get(seg["stops"][-1], seg["stops"][-1]),
                    "n_stops": len(seg["stops"]) - 1,
                })

            return json.dumps({
                "status": "success",
                "data": {
                    "itinerary": itinerary,
                    "transfers": len(segments) - 1,
                    "total_stops": sum(s["n_stops"] for s in itinerary),
                    "total_cost": dist[best],
                }
            }, ensure_ascii=False)
        except Exception as e:
            logger.error(f"路线规划错误: {str(e)}")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
