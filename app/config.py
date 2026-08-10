#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: config.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/1/17
描述: 全局配置（LLM、数据库、日志、意图路由映射）
      从 .env 文件加载敏感配置，环境变量优先于默认值。
"""

import os
from dotenv import load_dotenv

# 加载 .env 文件（项目根目录）
_project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_project_dir, '.env'))


# 定义配置文件
class Config:

    def __init__(self):
        # 大模型配置（环境变量 > 默认值）
        self.base_url = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
        self.api_key = os.getenv('DEEPSEEK_API_KEY', 'your-api-key')
        self.model_name = os.getenv('DEEPSEEK_MODEL', 'deepseek-v4-flash')

        # 数据库配置（环境变量 > 默认值）
        self.host = os.getenv('DB_HOST', 'localhost')
        self.user = os.getenv('DB_USER', 'root')
        self.password = os.getenv('DB_PASSWORD', '123456')
        self.database = os.getenv('DB_NAME', 'cuhk_campus')

        # 日志配置
        self.log_file = os.path.join(_project_dir, 'logs', 'app.log')

        # 意图 → Agent 映射
        self.intent = {
            "course": "CourseQueryAssistant",           # 课程查询
            "campus_event": "FacilityQueryAssistant",    # 校园活动查询
            "campus_news": "FacilityQueryAssistant",     # 校园新闻查询
            "canteen": "FacilityQueryAssistant",         # 餐厅查询
            "library_hours": "FacilityQueryAssistant",   # 图书馆开放时间查询
        }

        self.temperature = 0.1
