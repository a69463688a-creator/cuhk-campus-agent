#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: spider_campus.py
项目: SmartCampus — CUHK校园生活助手
描述: CUHK校园活动定时采集器
      从 CPR 活动 AJAX 接口获取真实校园活动数据，存入 campus_events 表。
      支持增量更新：超24小时自动拉取，也支持 force_update=True 强制刷新。
数据源:
      https://apps.cuhk.edu.hk/cuhkwebsite/cpr-new/events-ajax2.aspx
"""
import re
import json
import subprocess
import ast
from datetime import datetime, timedelta

import mysql.connector
import pytz
import requests

from spiders.base import BaseSpider

TZ = pytz.timezone('Asia/Shanghai')

EVENTS_API_URL = "https://apps.cuhk.edu.hk/cuhkwebsite/cpr-new/events-ajax2.aspx"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def parse_event_datetime(date_str, time_html):
    """
    从 API 返回的 start_date + extracted_datetime_display 中解析开始/结束时间。
    返回 (start_datetime_str, end_datetime_str)，格式: 'YYYY-MM-DD HH:MM:SS'
    """
    if not time_html:
        time_html = ''

    clean = re.sub(r'<[^>]+>', ' ', time_html)
    clean = clean.replace('&ndash;', '–').replace('&nbsp;', ' ').strip()

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
    CUHK API 返回 Python 字面量或标准 JSON。
    """
    text = raw_text.strip()
    if not text:
        return {}

    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    try:
        result = ast.literal_eval(text)
        if isinstance(result, (list, tuple)):
            result = result[0] if result else {}
        if isinstance(result, dict):
            return result
    except (SyntaxError, ValueError):
        pass

    return {}


def _fetch_events_from_api():
    """
    从 CUHK CPR 活动 AJAX 接口获取活动列表。
    优先使用 requests，若 SSL 握手失败则回退到 curl 子进程。
    """
    # 方式1: requests
    try:
        resp = requests.get(EVENTS_API_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = _parse_api_response(resp.text)
        if data.get('status') == 'success':
            return data.get('structure', [])
    except Exception:
        pass

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


def _store_events(conn, cursor, events):
    """将活动数据写入 campus_events 表，使用 INSERT IGNORE 避免重复"""
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


class EventsSpider(BaseSpider):
    """CUHK 校园活动爬虫"""

    name = "Campus Event Spider"
    data_source = EVENTS_API_URL
    stale_hours = 24
    table_name = "campus_events"
    schedule_time = "01:00"
    schedule_rule = "day"
    update_filter = "description LIKE '%cpr_spider%'"

    def fetch(self):
        return _fetch_events_from_api()

    def store(self, conn, cursor, items):
        return _store_events(conn, cursor, items)


if __name__ == "__main__":
    EventsSpider.main()
