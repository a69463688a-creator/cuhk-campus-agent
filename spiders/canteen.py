#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: spider_canteen.py
项目: SmartCampus — CUHK校园生活助手
描述: CUHK校园餐厅信息采集器
      从 CUHK 校园住宿页面抓取餐厅数据，解析并写入 canteen 表。
      数据源: https://www.cuhk.edu.hk/english/campus/accommodation.html#canteen_info
"""
import re
from datetime import datetime

import mysql.connector
import requests
from bs4 import BeautifulSoup

from spiders.base import BaseSpider

CANTEEN_URL = "https://www.cuhk.edu.hk/english/campus/accommodation.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
REQUEST_TIMEOUT = 20


def clean_text(text):
    """清理 HTML 实体和多余空白"""
    text = text.replace('–', '-').replace('—', '-')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def infer_category(name):
    """根据名称推断餐厅类别"""
    n = name.lower()
    if 'cafe' in n or 'coffee' in n:
        return 'Cafe'
    if 'restaurant' in n or 'dining' in n or 'club' in n:
        return 'Restaurant'
    if 'snack' in n:
        return 'Snack Bar'
    if 'store' in n or 'shop' in n:
        return 'Store'
    return 'Canteen'


def infer_status(name, hours):
    """根据名称或营业时间判断状态"""
    if 'closed' in name.lower() or 'closed' in hours.lower():
        return 'Closed'
    return 'Open'


def fetch_canteens():
    """从 CUHK 住宿页面抓取餐厅数据"""
    try:
        resp = requests.get(CANTEEN_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] 获取餐厅页面失败: {e}")
        return []

    soup = BeautifulSoup(resp.text, 'html.parser')
    canteen_section = soup.find(id='canteen_info')
    if not canteen_section:
        print("[WARN] 未找到餐厅信息区域")
        return []

    tbody = canteen_section.find('tbody')
    if not tbody:
        print("[WARN] 未找到餐厅 tbody")
        return []

    canteens = []
    rows = tbody.find_all('tr')

    for row in rows:
        name_th = row.find('th')
        if not name_th:
            continue
        name = clean_text(name_th.get_text(strip=True))

        cells = row.find_all('td')
        if len(cells) < 3:
            continue

        # 电话：提取纯数字和符号，去掉 Email 链接
        phone_cell = cells[0]
        for mail_link in phone_cell.find_all('a', href=lambda h: h and 'mailto:' in h):
            mail_link.decompose()
        phone = clean_text(phone_cell.get_text(strip=True))

        # 地址：提取链接中的文本
        addr_cell = cells[1]
        addr_link = addr_cell.find('a')
        if addr_link:
            address = clean_text(addr_link.get_text(strip=True))
        else:
            address = clean_text(addr_cell.get_text(strip=True))

        # 营业时间
        hours = clean_text(cells[2].get_text(strip=True))

        if not name or len(name) < 3:
            continue

        canteens.append({
            'name': name[:80],
            'location': address[:100],
            'opening_hours': hours[:300],
            'phone': phone[:50],
            'category': infer_category(name),
            'status': infer_status(name, hours),
        })

    return canteens


def _store_canteens(conn, cursor, canteens):
    """写入 canteen 表，先清除旧数据再插入"""
    if not canteens:
        return 0

    cursor.execute("DELETE FROM canteen")

    insert_sql = """
    INSERT INTO canteen (
        name, location, opening_hours, phone, category, status
    ) VALUES (%s, %s, %s, %s, %s, %s)
    """

    count = 0
    for item in canteens:
        try:
            cursor.execute(insert_sql, (
                item['name'],
                item['location'],
                item['opening_hours'],
                item['phone'],
                item['category'],
                item['status'],
            ))
            count += 1
        except mysql.connector.Error as e:
            print(f"[WARN] 写入失败 ({item['name'][:40]}...): {e}")
            continue

    conn.commit()
    return count


class CanteenSpider(BaseSpider):
    """CUHK 校园餐厅爬虫"""

    name = "Campus Canteen Spider"
    data_source = CANTEEN_URL
    stale_hours = 168
    table_name = "canteen"
    schedule_time = "03:00"
    schedule_rule = "monday"

    def fetch(self):
        return fetch_canteens()

    def store(self, conn, cursor, items):
        return _store_canteens(conn, cursor, items)


if __name__ == "__main__":
    CanteenSpider.main()
