#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: spider_campus.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/4
描述: CUHK校园活动定时采集器
      从 CPR 活动 AJAX 接口获取真实校园活动数据，存入 campus_events 表。
      支持增量更新：超24小时自动拉取，也支持 force_update=True 强制刷新。
      配备 schedule 定时调度（默认每天北京时间凌晨1:00执行）。
数据源:
      https://apps.cuhk.edu.hk/cuhkwebsite/cpr-new/events-ajax2.aspx
"""
import os
import requests
import mysql.connector
from datetime import datetime, timedelta
import schedule
import time
import re
import json
import subprocess
import ast
import pytz

# ============ 配置 ============
TZ = pytz.timezone('Asia/Shanghai')

db_config = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "123456"),
    "database": os.getenv("DB_NAME", "cuhk_campus"),
    "charset": "utf8mb4"
}

# CUHK CPR 活动 AJAX 接口（返回 JSON 数组）
EVENTS_API_URL = "https://apps.cuhk.edu.hk/cuhkwebsite/cpr-new/events-ajax2.aspx"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def connect_db():
    """建立 MySQL 连接"""
    return mysql.connector.connect(**db_config)


def parse_event_datetime(date_str, time_html):
    """
    从 API 返回的 start_date + extracted_datetime_display 中解析开始/结束时间。
    API 格式示例:
      date_str:   "8/23/2026 12:00:00 AM"
      time_html:  "23 August 2026 <p>10:30 am</p>"  或
                  "21 May 2026–22 May 2026"          或
                  "4 July 2026&ndash;26 July 2026 <p>...</p>"

    返回 (start_datetime_str, end_datetime_str)，格式: 'YYYY-MM-DD HH:MM:SS'
    """
    if not time_html:
        time_html = ''

    # 清理 HTML 实体
    clean = re.sub(r'<[^>]+>', ' ', time_html)
    clean = clean.replace('&ndash;', '–').replace('&nbsp;', ' ').strip()

    # 解析 API 的 start_date
    try:
        parsed_start = datetime.strptime(date_str, '%m/%d/%Y %I:%M:%S %p')
    except ValueError:
        parsed_start = datetime.now(TZ)

    start_dt = parsed_start
    end_dt = parsed_start

    # 尝试匹配时间范围 "10:30 am – 12:00 pm"
    time_range = re.findall(
        r'(\d{1,2})[:.](\d{2})\s*(am|pm|a\.m\.|p\.m\.)?\s*[–\-to]+\s*'
        r'(\d{1,2})[:.](\d{2})\s*(am|pm|a\.m\.|p\.m\.)?',
        clean, re.IGNORECASE
    )
    if time_range:
        m = time_range[0]
        h1, m1 = int(m[0]), int(m[1])
        ap1 = (m[2] or '').lower().replace('.', '')
        h2, m2 = int(m[3]), int(m[4])
        ap2 = (m[5] or '').lower().replace('.', '')
        if 'pm' in ap1 and h1 != 12:
            h1 += 12
        if 'am' in ap1 and h1 == 12:
            h1 = 0
        if 'pm' in ap2 and h2 != 12:
            h2 += 12
        if 'am' in ap2 and h2 == 12:
            h2 = 0
        start_dt = parsed_start.replace(hour=h1, minute=m1, second=0, microsecond=0)
        end_dt = parsed_start.replace(hour=h2, minute=m2, second=0, microsecond=0)
        return start_dt.strftime('%Y-%m-%d %H:%M:%S'), end_dt.strftime('%Y-%m-%d %H:%M:%S')

    # 尝试匹配单时间 "10:30 am"
    single_time = re.findall(
        r'(\d{1,2})[:.](\d{2})\s*(am|pm|a\.m\.|p\.m\.)?',
        clean, re.IGNORECASE
    )
    if single_time:
        h, m = int(single_time[0][0]), int(single_time[0][1])
        ap = (single_time[0][2] or '').lower().replace('.', '')
        if 'pm' in ap and h != 12:
            h += 12
        if 'am' in ap and h == 12:
            h = 0
        start_dt = parsed_start.replace(hour=h, minute=m, second=0, microsecond=0)
        end_dt = start_dt + timedelta(hours=2)
        return start_dt.strftime('%Y-%m-%d %H:%M:%S'), end_dt.strftime('%Y-%m-%d %H:%M:%S')

    # 无具体时间 → 全天活动
    end_dt = start_dt + timedelta(hours=2)
    return start_dt.strftime('%Y-%m-%d %H:%M:%S'), end_dt.strftime('%Y-%m-%d %H:%M:%S')


def infer_category(title):
    """根据活动标题关键词推断类别"""
    t = title.lower()
    if any(kw in t for kw in ['seminar', 'lecture', 'talk', 'conference',
                               'symposium', 'forum', 'webinar', 'colloquium']):
        return 'Talk'
    if any(kw in t for kw in ['concert', 'music', 'art', 'exhibition',
                               'film', 'movie', 'show', 'gems', 'chamber']):
        return 'Culture'
    if any(kw in t for kw in ['sport', 'fiesta', 'game', 'competition',
                               'race', 'run']):
        return 'Sports'
    if any(kw in t for kw in ['workshop', 'training', 'course']):
        return 'Workshop'
    if any(kw in t for kw in ['service', 'chapel', 'sunday', 'worship',
                               'prayer', 'buddhist', 'meditation']):
        return 'Religion'
    if any(kw in t for kw in ['career', 'job', 'recruitment', 'fair']):
        return 'Career'
    return 'Others'


def _parse_api_response(raw_text):
    """
    解析 API 返回的原始文本。
    CUHK API 返回的是 Python 字面量格式：({'status': 'success', ...})
    也会尝试标准 JSON。
    返回 dict。
    """
    text = raw_text.strip()
    if not text:
        return {}

    # 方式1: 标准 JSON
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # 方式2: Python 字面量 — 外层可能有括号包裹
    try:
        result = ast.literal_eval(text)
        # 可能是 ({...}), [...], 或直接 {...}
        if isinstance(result, (list, tuple)):
            result = result[0] if result else {}
        if isinstance(result, dict):
            return result
    except (SyntaxError, ValueError):
        pass

    return {}


def fetch_events_from_api():
    """
    从 CUHK CPR 活动 AJAX 接口获取活动列表。
    优先使用 requests，若 SSL 握手失败则回退到 curl 子进程。
    返回 list[dict]。
    """
    # 方式1: requests（部分 Python 环境的 OpenSSL 与此服务器不兼容）
    try:
        resp = requests.get(EVENTS_API_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = _parse_api_response(resp.text)
        if data.get('status') == 'success':
            return data.get('structure', [])
    except Exception:
        pass  # 回退到 curl

    # 方式2: 系统 curl（Git Bash 自带，OpenSSL 兼容性更好）
    try:
        result = subprocess.run(
            ['curl', '-s', '--insecure', EVENTS_API_URL],
            capture_output=True, encoding='utf-8', errors='replace',
            timeout=20
        )
        if result.returncode == 0 and result.stdout and result.stdout.strip():
            data = _parse_api_response(result.stdout)
            if data.get('status') == 'success':
                return data.get('structure', [])
    except Exception as e:
        print(f"[ERROR] curl 回退也失败: {e}")

    return []


def get_latest_fetch_time(cursor):
    """获取 campus_events 表中最近一次爬虫写入的时间"""
    cursor.execute(
        "SELECT MAX(created_at) FROM campus_events "
        "WHERE description LIKE '%cpr_spider%'"
    )
    result = cursor.fetchone()
    return result[0] if result[0] else None


def should_update(latest_time, force=False):
    """判断是否需要更新：无记录 / 超24小时 / 强制更新"""
    if force:
        return True
    if not latest_time:
        return True
    now = datetime.now(TZ)
    if hasattr(latest_time, 'replace') and latest_time.tzinfo is None:
        latest_time = latest_time.replace(tzinfo=TZ)
    return (now - latest_time).total_seconds() / 3600 >= 24


def store_events(conn, cursor, events):
    """
    将活动数据写入 campus_events 表。
    使用 INSERT IGNORE 避免重复。
    """
    if not events:
        print("[INFO] 无新活动数据，跳过写入。")
        return 0

    count = 0
    for ev in events:
        try:
            title = (ev.get('title') or 'Unknown Event')[:100]
            link = ev.get('link') or ''
            photo = ev.get('photo_url') or ''
            date_str = ev.get('start_date') or ''
            time_html = ev.get('extracted_datetime_display') or ''
            end_date_str = ev.get('end_date') or ''

            start_time, end_time = parse_event_datetime(date_str, time_html)

            # 如果结束时间和开始时间相同，尝试用 API 的 end_date
            if end_time == start_time and end_date_str:
                try:
                    parsed_end = datetime.strptime(end_date_str,
                                                   '%m/%d/%Y %I:%M:%S %p')
                    end_time = parsed_end.strftime('%Y-%m-%d %H:%M:%S')
                except ValueError:
                    pass

            category = infer_category(title)
            now_str = datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')

            insert_sql = """
            INSERT IGNORE INTO campus_events (
                event_name, organizer, venue, start_time, end_time,
                category, total_capacity, registered, description
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            values = (
                title,
                'CUHK CPR',
                'CUHK Campus',
                start_time,
                end_time,
                category,
                500,
                0,
                f"来源: {link} | 图片: {photo} | cpr_spider @ {now_str}"
            )
            cursor.execute(insert_sql, values)
            count += 1
        except mysql.connector.Error as e:
            print(f"[WARN] 写入失败 ({title[:40]}...): {e}")
            continue

    conn.commit()
    print(f"[INFO] 成功写入 {count} 条活动记录。")
    return count


def update_campus_events(force=False):
    """主更新入口：检查→拉取→写入"""
    conn = connect_db()
    cursor = conn.cursor()

    latest = get_latest_fetch_time(cursor)
    if not should_update(latest, force):
        print(f"[INFO] 数据已是最新（上次更新: {latest}），跳过。")
        cursor.close()
        conn.close()
        return

    print("[INFO] 开始从 CUHK CPR 活动接口拉取数据...")
    events = fetch_events_from_api()
    if events:
        store_events(conn, cursor, events)
    else:
        print("[WARN] API 返回空数据，本次跳过。")

    cursor.close()
    conn.close()


def setup_scheduler():
    """启动定时调度：每天北京时间凌晨 1:00 执行"""
    schedule.every().day.at("01:00").do(update_campus_events)
    print("[Scheduler] 定时任务已启动，每天 01:00 (Asia/Shanghai) 执行。")
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    once = "--once" in sys.argv

    print("=" * 60)
    print("CUHK Campus Event Spider")
    print(f"数据源: {EVENTS_API_URL}")
    mode = '强制更新' if force else '增量更新（>24h 才拉取）'
    if once:
        mode += ' | 单次执行模式'
    print(f"模式: {mode}")
    print("=" * 60)

    # 立即执行一次
    update_campus_events(force=force)

    if once:
        print("[INFO] --once 模式，更新完成，退出。")
        sys.exit(0)

    # 启动定时调度
    setup_scheduler()
