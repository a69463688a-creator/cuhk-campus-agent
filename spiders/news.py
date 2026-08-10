#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: spider_news.py
项目: SmartCampus — CUHK校园生活助手
描述: CUHK校园新闻采集器
      从 CUHK CPR 新闻中心抓取新闻稿，解析并写入 campus_news 表。
      数据源: https://www.cpr.cuhk.edu.hk/en/news-centre/press-releases/
      支持分页抓取和增量更新。
"""
import os
import re
import time
import sys
from datetime import datetime

import mysql.connector
import schedule
import pytz
import requests
from bs4 import BeautifulSoup

# ============ 配置 ============
TZ = pytz.timezone('Asia/Shanghai')

db_config = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "123456"),
    "database": os.getenv("DB_NAME", "cuhk_campus"),
    "charset": "utf8mb4"
}

NEWS_LIST_URL = "https://www.cpr.cuhk.edu.hk/en/news-centre/press-releases/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
MAX_PAGES = 5  # 每次最多抓取页数
REQUEST_TIMEOUT = 20


def connect_db():
    """建立 MySQL 连接"""
    return mysql.connector.connect(**db_config)


def parse_date(date_str):
    """解析 "6 Aug 2026" 格式的日期 → datetime"""
    try:
        return datetime.strptime(date_str.strip(), '%d %b %Y')
    except ValueError:
        return None


def fetch_news_page(page_num=1):
    """
    抓取单页新闻列表。
    返回 list[dict]: [{title, date, url, summary}]
    """
    if page_num == 1:
        url = NEWS_LIST_URL
    else:
        url = f"{NEWS_LIST_URL}page/{page_num}/"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"[WARN] 获取新闻列表失败 (page={page_num}): {e}")
        return []

    soup = BeautifulSoup(resp.text, 'html.parser')
    news_items = []

    # CPR 新闻列表结构: 每个新闻项是一个带链接的 div 或 li
    # 查找所有指向 /press/ 的链接
    seen_titles = set()
    for link in soup.find_all('a', href=True):
        href = link['href']
        if '/press/' not in href:
            continue
        text = link.get_text(strip=True)
        if not text or len(text) < 15:
            continue

        # 解析日期+标题: "6 Aug 2026CUHK unveils ..."
        m = re.match(r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})(.*)', text, re.IGNORECASE)
        if m:
            date_str = m.group(1)
            title = m.group(2).strip()
        else:
            # 日期可能在父级文本中
            parent = link.find_parent(['div', 'li'])
            parent_text = parent.get_text(strip=True) if parent else text
            m2 = re.search(r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})', parent_text, re.IGNORECASE)
            if m2:
                date_str = m2.group(1)
                title = text
            else:
                continue

        if title in seen_titles:
            continue
        seen_titles.add(title)

        parsed_date = parse_date(date_str)
        if not parsed_date:
            continue

        # 确保完整 URL
        if href.startswith('/'):
            href = f"https://www.cpr.cuhk.edu.hk{href}"

        news_items.append({
            'title': title[:300],
            'date': parsed_date,
            'url': href,
            'summary': title[:500],  # 标题作为简要摘要
        })

    return news_items


def fetch_all_news(max_pages=MAX_PAGES):
    """抓取多页新闻，直到没有新数据或达到上限"""
    all_news = []
    for page in range(1, max_pages + 1):
        print(f"[FETCH] 新闻第 {page} 页 ...", end=' ', flush=True)
        items = fetch_news_page(page)
        if not items:
            print("无数据，停止翻页")
            break
        print(f"{len(items)} 条")
        all_news.extend(items)
        time.sleep(1)  # 请求间隔
    return all_news


def store_news(conn, cursor, news_items):
    """写入 campus_news 表，INSERT IGNORE 去重"""
    if not news_items:
        return 0

    insert_sql = """
    INSERT IGNORE INTO campus_news (
        title, source, category, publish_date, summary, url
    ) VALUES (%s, %s, %s, %s, %s, %s)
    """

    count = 0
    for item in news_items:
        try:
            cursor.execute(insert_sql, (
                item['title'],
                'CUHK CPR',
                'General',
                item['date'].strftime('%Y-%m-%d %H:%M:%S'),
                item['summary'],
                item['url'],
            ))
            count += 1
        except mysql.connector.Error as e:
            print(f"[WARN] 写入失败 ({item['title'][:40]}...): {e}")
            continue

    conn.commit()
    return count


def get_latest_fetch_time(cursor):
    """获取 campus_news 表中最近一次爬虫写入的时间"""
    cursor.execute("SELECT MAX(created_at) FROM campus_news")
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


def update_campus_news(force=False):
    """主更新入口"""
    conn = connect_db()
    cursor = conn.cursor()

    latest = get_latest_fetch_time(cursor)
    if not should_update(latest, force):
        print(f"[INFO] 新闻数据已是最新（上次更新: {latest}），跳过。")
        cursor.close()
        conn.close()
        return

    print("[INFO] 开始从 CUHK CPR 新闻中心抓取数据...")
    news_items = fetch_all_news()
    if news_items:
        written = store_news(conn, cursor, news_items)
        print(f"[INFO] 成功写入 {written} 条新闻记录（共抓取 {len(news_items)} 条）。")
    else:
        print("[WARN] 未获取到新闻数据，本次跳过。")

    cursor.close()
    conn.close()


def setup_scheduler():
    """启动定时调度：每天北京时间 06:00 执行"""
    schedule.every().day.at("06:00").do(update_campus_news)
    print("[Scheduler] 定时任务已启动，每天 06:00 (Asia/Shanghai) 执行。")
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    once = "--once" in sys.argv

    print("=" * 60)
    print("CUHK Campus News Spider")
    print(f"数据源: {NEWS_LIST_URL}")
    mode = '强制更新' if force else '增量更新（>24h 才拉取）'
    if once:
        mode += ' | 单次执行模式'
    print(f"模式: {mode}")
    print("=" * 60)

    update_campus_news(force=force)

    if once:
        print("[INFO] --once 模式，更新完成，退出。")
        sys.exit(0)

    setup_scheduler()
