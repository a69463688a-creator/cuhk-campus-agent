#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: config.example.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/1/17
描述: 全局配置模板。复制为 config.py 并填入真实密钥后使用。
"""
import os

project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

env = "test"

class Config:
    def __init__(self):
        # 大模型配置 — 请替换为你的 API Key
        self.base_url = 'https://api.deepseek.com'
        self.api_key = 'your-deepseek-api-key'
        self.model_name = 'deepseek-v4-flash'

        # 数据库配置 — 请替换为你的 MySQL 连接信息
        self.host = 'localhost'
        self.user = 'root'
        self.password = 'your-mysql-password'
        self.database = 'cuhk_campus'

        # 日志配置
        self.log_file = os.path.join(project_root, 'SmartCampus', 'logs/app.log')

        # 意图 → Agent 映射
        self.intent = {
            "course": "CourseQueryAssistant",
            "study_room": "FacilityQueryAssistant",
            "library_seat": "FacilityQueryAssistant",
            "campus_event": "FacilityQueryAssistant",
            "booking": "BookingAssistant"
        }

        self.temperature = 0.1
