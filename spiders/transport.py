#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: transport.py
项目: SmartCampus — CUHK校园生活助手
描述: CUHK 校巴数据采集器
      数据源: https://www.transport.cuhk.edu.hk/sc/ （交通处）
      校巴路线/站点为公开信息，相对固定。通过基线数据 + 定期校验更新。
      由于官方时间表为 PDF/JS 动态渲染，采用内置基线数据（同 library.py 模式）。
"""
import mysql.connector

from spiders.base import BaseSpider

DATA_SOURCE = "https://www.transport.cuhk.edu.hk/sc/"

# ── 基线路线（route_code 唯一） ──
BASELINE_ROUTES = [
    {"route_code": "1",  "route_name": "大學站—本部線",   "start_stop": "大學站", "end_stop": "本部",   "service_type": "regular",       "first_bus_time": "07:30", "last_bus_time": "23:30", "frequency_min": 10, "note": ""},
    {"route_code": "2",  "route_name": "大學站—逸夫書院線", "start_stop": "大學站", "end_stop": "逸夫書院", "service_type": "regular",     "first_bus_time": "07:20", "last_bus_time": "23:20", "frequency_min": 10, "note": ""},
    {"route_code": "3",  "route_name": "本部—逸夫書院線",   "start_stop": "本部",   "end_stop": "逸夫書院", "service_type": "regular",       "first_bus_time": "08:00", "last_bus_time": "23:00", "frequency_min": 15, "note": ""},
    {"route_code": "5",  "route_name": "轉堂線5",          "start_stop": "大學站", "end_stop": "本部",   "service_type": "class_change",  "first_bus_time": "08:30", "last_bus_time": "18:00", "frequency_min": 20, "note": "教學日轉堂專線"},
    {"route_code": "N",  "route_name": "夜間線",            "start_stop": "大學站", "end_stop": "逸夫書院", "service_type": "night",        "first_bus_time": "19:00", "last_bus_time": "23:30", "frequency_min": 20, "note": "19:00 後行駛"},
    {"route_code": "H",  "route_name": "假日線",            "start_stop": "大學站", "end_stop": "本部",   "service_type": "holiday",       "first_bus_time": "08:00", "last_bus_time": "20:00", "frequency_min": 30, "note": "公眾假期行駛"},
]

# ── 基线站点 (route_code, stop_order, stop_name, stop_name_en) ──
BASELINE_STOPS = [
    ("1", 1, "大學站",   "University Station"),
    ("1", 2, "崇基書院", "Chung Chi College"),
    ("1", 3, "本部",     "Central Campus"),
    ("2", 1, "大學站",   "University Station"),
    ("2", 2, "聯合書院", "United College"),
    ("2", 3, "逸夫書院", "Shaw College"),
    ("3", 1, "本部",     "Central Campus"),
    ("3", 2, "新亞書院", "New Asia College"),
    ("3", 3, "逸夫書院", "Shaw College"),
    ("5", 1, "大學站",   "University Station"),
    ("5", 2, "本部",     "Central Campus"),
    ("N", 1, "大學站",   "University Station"),
    ("N", 2, "本部",     "Central Campus"),
    ("N", 3, "逸夫書院", "Shaw College"),
    ("H", 1, "大學站",   "University Station"),
    ("H", 2, "本部",     "Central Campus"),
]


def _store(conn, cursor, _items):
    """将基线路线/站点写入数据库，使用 UPSERT 策略"""
    route_sql = """
    INSERT INTO bus_routes (
        route_code, route_name, start_stop, end_stop, service_type,
        first_bus_time, last_bus_time, frequency_min, note
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        route_name = VALUES(route_name),
        start_stop = VALUES(start_stop),
        end_stop = VALUES(end_stop),
        service_type = VALUES(service_type),
        first_bus_time = VALUES(first_bus_time),
        last_bus_time = VALUES(last_bus_time),
        frequency_min = VALUES(frequency_min),
        note = VALUES(note)
    """
    stop_sql = """
    INSERT INTO bus_stops (route_code, stop_order, stop_name, stop_name_en)
    VALUES (%s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        stop_name = VALUES(stop_name),
        stop_name_en = VALUES(stop_name_en)
    """

    count = 0
    for r in BASELINE_ROUTES:
        try:
            cursor.execute(route_sql, (
                r["route_code"], r["route_name"], r["start_stop"], r["end_stop"],
                r["service_type"], r["first_bus_time"], r["last_bus_time"],
                r["frequency_min"], r["note"],
            ))
            count += 1
        except mysql.connector.Error as e:
            print(f"[WARN] 路线写入失败 ({r['route_code']}): {e}")
            continue
    for s in BASELINE_STOPS:
        try:
            cursor.execute(stop_sql, s)
            count += 1
        except mysql.connector.Error as e:
            print(f"[WARN] 站点写入失败 ({s[0]} {s[1]}): {e}")
            continue

    conn.commit()
    return count


class TransportSpider(BaseSpider):
    """CUHK 校巴数据爬虫"""

    name = "Transport Spider"
    data_source = f"CUHK 交通处（基线数据 + {DATA_SOURCE}）"
    stale_hours = 168
    table_name = "bus_routes"
    schedule_time = "04:00"
    schedule_rule = "monday"

    def fetch(self):
        """基线数据直接从常量读取，不需要网络请求"""
        return [BASELINE_ROUTES, BASELINE_STOPS]

    def store(self, conn, cursor, items):
        return _store(conn, cursor, items)


if __name__ == "__main__":
    TransportSpider.main()
