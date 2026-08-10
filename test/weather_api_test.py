#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: campus_api_test.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/4
描述: CUHK校园公开页面连通性测试脚本
"""
import requests
from bs4 import BeautifulSoup


def test_cuhk_public_pages():
    """
    测试CUHK公开页面是否可访问。
    用于验证校园数据采集器的基础连通性。
    """
    test_urls = [
        ("CUHK 主站", "https://www.cuhk.edu.hk/"),
        ("CUHK 新闻", "https://www.cuhk.edu.hk/chinese/news/"),
        ("CUHK 教务处RES", "https://www.res.cuhk.edu.hk/"),
        ("CUHK 图书馆", "https://www.lib.cuhk.edu.hk/"),
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    for name, url in test_urls:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            status = "✅ 可访问" if response.status_code == 200 else f"⚠️ 状态码 {response.status_code}"
            print(f"{status} - {name}: {url}")
        except requests.RequestException as e:
            print(f"❌ 不可访问 - {name}: {url} ({e})")


if __name__ == "__main__":
    print("=== CUHK 公开页面连通性测试 ===\n")
    test_cuhk_public_pages()
    print("\n=== 测试完成 ===")
    print("提示：如需采集课程数据，可参考 another-cuhk-course-planner 开源项目。")
    print("提示：校园活动数据可通过CUHK新闻页面公开获取。")
