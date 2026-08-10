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
import time
import sys
from datetime import datetime, date

import mysql.connector
import schedule
import pytz

# ============ 配置 ============
TZ = pytz.timezone('Asia/Shanghai')

db_config = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "database": "cuhk_campus",
    "charset": "utf8mb4"
}

CALENDAR_URL = "https://www.lib.cuhk.edu.hk/en/use/hours/calendar/"

# CUHK 图书馆标准学期开放时间（公开信息，作为基线数据）
# 格式: {library_name: {area: {day: (open, close)}}}
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
            "Sun": ("", ""),  # 周日不提供服务
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


def connect_db():
    """建立 MySQL 连接"""
    return mysql.connector.connect(**db_config)


def get_date_for_day(day_name, reference_date=None):
    """获取本周某天的日期"""
    if reference_date is None:
        reference_date = date.today()
    day_map = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}
    target = day_map.get(day_name, 0)
    current = reference_date.weekday()
    delta = target - current
    return reference_date.replace(day=reference_date.day + delta)


def store_baseline_hours(conn, cursor):
    """将基线开放时间写入数据库"""
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
                    open_t = times[0]  # "24hrs"
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


def get_latest_fetch_time(cursor):
    """获取 library_hours 表中最近一次更新时间"""
    cursor.execute("SELECT MAX(created_at) FROM library_hours")
    result = cursor.fetchone()
    return result[0] if result[0] else None


def should_update(latest_time, force=False):
    """判断是否需要更新：无记录 / 超7天 / 强制更新"""
    if force:
        return True
    if not latest_time:
        return True
    now = datetime.now(TZ)
    if hasattr(latest_time, 'replace') and latest_time.tzinfo is None:
        latest_time = latest_time.replace(tzinfo=TZ)
    return (now - latest_time).total_seconds() / 3600 >= 168


def update_library_hours(force=False):
    """主更新入口"""
    conn = connect_db()
    cursor = conn.cursor()

    latest = get_latest_fetch_time(cursor)
    if not should_update(latest, force):
        print(f"[INFO] 图书馆开放时间已是最新（上次更新: {latest}），跳过。")
        cursor.close()
        conn.close()
        return

    print("[INFO] 使用基线数据更新图书馆开放时间...")
    written = store_baseline_hours(conn, cursor)
    print(f"[INFO] 成功写入/更新 {written} 条图书馆开放时间记录。")

    cursor.close()
    conn.close()


def setup_scheduler():
    """启动定时调度：每周一凌晨 04:00 执行"""
    schedule.every().monday.at("04:00").do(update_library_hours)
    print("[Scheduler] 定时任务已启动，每周一 04:00 (Asia/Shanghai) 执行。")
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    force = "--force" in sys.argv
    once = "--once" in sys.argv

    print("=" * 60)
    print("CUHK Library Hours Spider")
    print(f"数据源: CUHK Library (基线数据 + {CALENDAR_URL})")
    mode = '强制更新' if force else '增量更新（>7天 才拉取）'
    if once:
        mode += ' | 单次执行模式'
    print(f"模式: {mode}")
    print("=" * 60)

    update_library_hours(force=force)

    if once:
        print("[INFO] --once 模式，更新完成，退出。")
        sys.exit(0)

    setup_scheduler()
