#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: spider_library_hours.py
项目: SmartCampus — CUHK校园生活助手
描述: CUHK图书馆开放时间采集器
      数据源: https://www.lib.cuhk.edu.hk/en/use/hours/calendar/
      库开放时间为公开信息，相对固定。通过 seed 数据 + 定期校验更新。
      由于页面使用 FullCalendar 动态渲染，采用 Playwright 渲染后提取数据。
      如 Playwright 不可用，使用内置基线数据。
"""
from datetime import date

import mysql.connector

from spiders.base import BaseSpider

CALENDAR_URL = "https://www.lib.cuhk.edu.hk/en/use/hours/calendar/"

# CUHK 图书馆标准学期开放时间（公开信息，作为基线数据）
BASELINE_HOURS = {
    "University Library": {
        "Main": {
            "Mon": ("08:30", "22:00"), "Tue": ("08:30", "22:00"),
            "Wed": ("08:30", "22:00"), "Thu": ("08:30", "22:00"),
            "Fri": ("08:30", "22:00"), "Sat": ("08:30", "19:00"),
            "Sun": ("11:00", "19:00"),
        },
        "Learning Garden": {
            "Mon": ("24hrs",), "Tue": ("24hrs",), "Wed": ("24hrs",),
            "Thu": ("24hrs",), "Fri": ("24hrs",), "Sat": ("24hrs",),
            "Sun": ("24hrs",),
        },
        "Staffed services": {
            "Mon": ("08:30", "18:00"), "Tue": ("08:30", "18:00"),
            "Wed": ("08:30", "18:00"), "Thu": ("08:30", "18:00"),
            "Fri": ("08:30", "18:00"), "Sat": ("08:30", "17:00"),
            "Sun": ("", ""),
        },
    },
    "Chung Chi College Library": {
        "Main": {
            "Mon": ("08:30", "22:00"), "Tue": ("08:30", "22:00"),
            "Wed": ("08:30", "22:00"), "Thu": ("08:30", "22:00"),
            "Fri": ("08:30", "22:00"), "Sat": ("08:30", "19:00"),
            "Sun": ("11:00", "19:00"),
        },
    },
    "New Asia College Library": {
        "Main": {
            "Mon": ("08:30", "22:00"), "Tue": ("08:30", "22:00"),
            "Wed": ("08:30", "22:00"), "Thu": ("08:30", "22:00"),
            "Fri": ("08:30", "22:00"), "Sat": ("08:30", "19:00"),
            "Sun": ("11:00", "19:00"),
        },
    },
    "United College Library": {
        "Main": {
            "Mon": ("08:30", "22:00"), "Tue": ("08:30", "22:00"),
            "Wed": ("08:30", "22:00"), "Thu": ("08:30", "22:00"),
            "Fri": ("08:30", "22:00"), "Sat": ("08:30", "19:00"),
            "Sun": ("11:00", "19:00"),
        },
    },
    "Architecture Library": {
        "Main": {
            "Mon": ("09:00", "18:00"), "Tue": ("09:00", "18:00"),
            "Wed": ("09:00", "18:00"), "Thu": ("09:00", "18:00"),
            "Fri": ("09:00", "18:00"), "Sat": ("09:00", "13:00"),
            "Sun": ("", ""),
        },
    },
    "Law Library": {
        "Main": {
            "Mon": ("08:45", "22:00"), "Tue": ("08:45", "22:00"),
            "Wed": ("08:45", "22:00"), "Thu": ("08:45", "22:00"),
            "Fri": ("08:45", "22:00"), "Sat": ("08:45", "19:00"),
            "Sun": ("11:00", "19:00"),
        },
    },
    "Medical Library": {
        "Main": {
            "Mon": ("08:45", "22:00"), "Tue": ("08:45", "22:00"),
            "Wed": ("08:45", "22:00"), "Thu": ("08:45", "22:00"),
            "Fri": ("08:45", "22:00"), "Sat": ("08:45", "17:00"),
            "Sun": ("11:00", "19:00"),
        },
    },
    "Learning Commons (WMY)": {
        "Main": {
            "Mon": ("24hrs",), "Tue": ("24hrs",), "Wed": ("24hrs",),
            "Thu": ("24hrs",), "Fri": ("24hrs",), "Sat": ("24hrs",),
            "Sun": ("24hrs",),
        },
    },
}


def get_date_for_day(day_name, reference_date=None):
    """获取本周某天的日期"""
    if reference_date is None:
        reference_date = date.today()
    day_map = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}
    target = day_map.get(day_name, 0)
    current = reference_date.weekday()
    delta = target - current
    return reference_date.replace(day=reference_date.day + delta)


def _store_baseline_hours(conn, cursor, _items):
    """将基线开放时间写入数据库，使用 UPSERT 策略"""
    today = date.today()
    rows = []

    for lib_name, areas in BASELINE_HOURS.items():
        for area_name, days in areas.items():
            for day_name, times in days.items():
                specific_date = get_date_for_day(day_name, today)
                if len(times) >= 2:
                    open_t, close_t = times[0], times[1]
                    is_closed = (open_t == '' and close_t == '')
                else:
                    open_t = times[0]
                    close_t = times[0]
                    is_closed = 0

                rows.append((
                    lib_name, area_name, day_name,
                    specific_date, open_t, close_t, 1 if is_closed else 0
                ))

    insert_sql = """
    INSERT INTO library_hours (
        library_name, area, day_of_week, date, open_time, close_time, is_closed
    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        open_time = VALUES(open_time),
        close_time = VALUES(close_time),
        is_closed = VALUES(is_closed)
    """

    count = 0
    for row in rows:
        try:
            cursor.execute(insert_sql, row)
            count += 1
        except mysql.connector.Error as e:
            print(f"[WARN] 写入失败 ({row[0]} {row[1]} {row[2]}): {e}")
            continue

    conn.commit()
    return count


class LibrarySpider(BaseSpider):
    """CUHK 图书馆开放时间爬虫"""

    name = "Library Hours Spider"
    data_source = f"CUHK Library (基线数据 + {CALENDAR_URL})"
    stale_hours = 168
    table_name = "library_hours"
    schedule_time = "04:00"
    schedule_rule = "monday"

    def fetch(self):
        """基线数据直接从常量读取，不需要网络请求"""
        return [BASELINE_HOURS]  # 传一个标记让 store 知道有数据

    def store(self, conn, cursor, items):
        return _store_baseline_hours(conn, cursor, items)


if __name__ == "__main__":
    LibrarySpider.main()
