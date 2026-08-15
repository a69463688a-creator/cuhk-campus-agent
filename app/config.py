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
        self.port = int(os.getenv('DB_PORT', '3306'))
        self.user = os.getenv('DB_USER', 'root')
        self.password = os.getenv('DB_PASSWORD', '123456')
        self.database = os.getenv('DB_NAME', 'cuhk_campus')

        # MCP 服务地址（Agent 连接 MCP Server 的 URL）
        self.mcp_course_url = os.getenv(
            "MCP_COURSE_URL", "http://127.0.0.1:8002/mcp"
        )
        self.mcp_facility_url = os.getenv(
            "MCP_FACILITY_URL", "http://127.0.0.1:8001/mcp"
        )

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

        # ============ 记忆系统配置（持久化分层记忆） ============
        # 本地 embedding（Ollama bge-m3，经 HTTP 调用，无 torch 重依赖）
        self.embedding_base_url = os.getenv("EMBEDDING_BASE_URL", "http://localhost:11434")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "bge-m3")
        self.embedding_dim = int(os.getenv("EMBEDDING_DIM", "1024"))

        # 记忆召回与巩固
        self.memory_window_tokens = int(os.getenv("MEMORY_WINDOW_TOKENS", "2000"))       # 单次召回上下文预算
        self.memory_summary_trigger_turns = int(os.getenv("MEMORY_SUMMARY_TRIGGER_TURNS", "10"))  # 触发滚动摘要的消息条数
        self.memory_semantic_top_k = int(os.getenv("MEMORY_SEMANTIC_TOP_K", "5"))        # 语义召回 top-K
        self.memory_dedup_threshold = float(os.getenv("MEMORY_DEDUP_THRESHOLD", "0.9"))  # 长期记忆去重余弦阈值
