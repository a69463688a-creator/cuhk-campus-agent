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
import re
import time
from datetime import datetime

import mysql.connector
import requests
from bs4 import BeautifulSoup

from spiders.base import BaseSpider

NEWS_LIST_URL = "https://www.cpr.cuhk.edu.hk/en/news-centre/press-releases/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
MAX_PAGES = 5  # 每次最多抓取页数
REQUEST_TIMEOUT = 20


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
            'summary': title[:500],
        })

    return news_items


def _fetch_all_news(max_pages=MAX_PAGES):
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
        time.sleep(1)
    return all_news


def _store_news(conn, cursor, news_items):
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


class NewsSpider(BaseSpider):
    """CUHK 校园新闻爬虫"""

    name = "Campus News Spider"
    data_source = NEWS_LIST_URL
    stale_hours = 24
    table_name = "campus_news"
    schedule_time = "06:00"
    schedule_rule = "day"

    def fetch(self):
        return _fetch_all_news()

    def store(self, conn, cursor, items):
        return _store_news(conn, cursor, items)


if __name__ == "__main__":
    NewsSpider.main()
