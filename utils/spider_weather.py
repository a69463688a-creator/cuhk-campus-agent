#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: spider_campus.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/4
描述: CUHK校园数据采集器 —— 从公开页面爬取校园新闻/活动公告，存入MySQL
"""
import requests
import mysql.connector
from datetime import datetime, timedelta
import schedule
import time
import json
import pytz
from bs4 import BeautifulSoup

# 配置
TZ = pytz.timezone('Asia/Shanghai')  # 使用上海时区

# MySQL 配置
db_config = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "database": "cuhk_campus",
    "charset": "utf8mb4"
}

# CUHK 公开数据源（示例URL，实际使用时替换为真实页面）
CUHK_SOURCES = {
    "news": "https://www.cuhk.edu.hk/chinese/news/",
    "events": "https://www.cuhk.edu.hk/chinese/events/",
    "cpr": "https://www.cpr.cuhk.edu.hk/sc/press/"
}


def connect_db():
    return mysql.connector.connect(**db_config)


def fetch_cuhk_news():
    """
    从CUHK公开新闻页面获取最新校园动态。
    注意：CUHK官网无反爬机制，仅用于学习和个人项目用途。
    :return: 新闻列表
    """
    news_list = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        for source_name, url in CUHK_SOURCES.items():
            try:
                response = requests.get(url, headers=headers, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                # 提取新闻/活动条目（具体选择器根据实际页面结构调整）
                items = soup.select('a[href]')  # 通用选择器，实际使用时细化
                for item in items[:10]:  # 每次最多取10条
                    text = item.get_text(strip=True)
                    href = item.get('href', '')
                    if text and len(text) > 10:
                        news_list.append({
                            "source": source_name,
                            "title": text,
                            "url": href if href.startswith('http') else f"https://www.cuhk.edu.hk{href}",
                            "fetch_time": datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')
                        })
            except Exception as e:
                print(f"获取 {source_name} 失败: {e}")
    except Exception as e:
        print(f"新闻采集失败: {e}")

    return news_list


def get_latest_update_time(cursor, source):
    """
    获取指定数据源在 campus_news 表中的最新更新时间。
    :param cursor:
    :param source:
    :return:
    """
    cursor.execute("SELECT MAX(created_at) FROM campus_events WHERE organizer LIKE %s", (f'%{source}%',))
    result = cursor.fetchone()
    return result[0] if result[0] else None


def should_update_data(latest_time, force_update=False):
    """
    判断是否需要更新数据：没有记录 或 超过24小时 或 强制更新。
    :param latest_time: 最新更新时间
    :param force_update: 是否强制更新
    :return: True/False
    """
    if force_update:
        return True
    if not latest_time:
        return True
    current_time = datetime.now(TZ)
    if hasattr(latest_time, 'replace'):
        latest_time = latest_time.replace(tzinfo=TZ) if latest_time.tzinfo is None else latest_time
    return (current_time - latest_time).total_seconds() / 3600 >= 24


def store_campus_news(conn, cursor, news_items):
    """
    将采集到的校园新闻/活动存入 campus_events 表。
    :param conn:
    :param cursor:
    :param news_items:
    :return:
    """
    if not news_items:
        print("没有新的校园动态，跳过存储。")
        return

    for item in news_items:
        try:
            insert_query = """
            INSERT INTO campus_events (
                event_name, organizer, venue, start_time, end_time,
                category, total_capacity, registered, description
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                description = VALUES(description)
            """
            values = (
                item.get('title', 'Unknown Event'),
                f"CUHK {item.get('source', 'Official')}",
                'CUHK Campus',
                datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S'),
                (datetime.now(TZ) + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S'),
                'News',
                500,
                0,
                f"来源: {item.get('url', '')} | 采集时间: {item.get('fetch_time', '')}"
            )
            cursor.execute(insert_query, values)
            print(f"校园动态写入成功: {item.get('title', '')[:50]}...")
            conn.commit()
        except mysql.connector.Error as e:
            print(f"数据库写入错误: {e}")
            conn.rollback()


def update_campus_data(force_update=False):
    """
    主更新函数：检查是否需要更新，爬取数据，存入数据库。
    :param force_update:
    :return:
    """
    conn = connect_db()
    cursor = conn.cursor()

    for source_name in CUHK_SOURCES.keys():
        latest_time = get_latest_update_time(cursor, source_name)
        if should_update_data(latest_time, force_update):
            print(f"开始采集 {source_name} 数据...")
            news_items = fetch_cuhk_news()
            if news_items:
                store_campus_news(conn, cursor, news_items)
        else:
            print(f"{source_name} 数据已为最新。最新更新时间: {latest_time}")

    cursor.close()
    conn.close()


def setup_scheduler():
    # 北京时间每天 1:00 更新
    schedule.every().day.at("01:00").do(update_campus_data)
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    # 确保 campus_events 表存在
    with mysql.connector.connect(**db_config) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS campus_events (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
            event_name VARCHAR(200) NOT NULL COMMENT '活动名称',
            organizer VARCHAR(100) NOT NULL COMMENT '主办方',
            venue VARCHAR(100) NOT NULL COMMENT '活动场地',
            start_time DATETIME NOT NULL COMMENT '开始时间',
            end_time DATETIME NOT NULL COMMENT '结束时间',
            category VARCHAR(30) NOT NULL COMMENT '活动类别',
            total_capacity INT NOT NULL DEFAULT 100 COMMENT '总容量',
            registered INT NOT NULL DEFAULT 0 COMMENT '已报名人数',
            description TEXT COMMENT '活动简介',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_event (start_time, event_name, venue)
        ) COMMENT='校园活动信息表'
        """)
        conn.commit()

    # 立即执行一次更新
    update_campus_data()

    # 启动定时任务
    setup_scheduler()
