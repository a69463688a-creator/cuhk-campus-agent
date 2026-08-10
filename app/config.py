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


# 生产环境
# env = "prod"
# 测试环境
env = "test"
# 开发环境
# env = "dev"
# 预生产环境
# env = "pre_prod"


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

        # CUHK 校园相关接口地址（预留）
        self.url_cuhk = ""

        # 意图 → Agent 映射
        self.intent = {
            "course": "CourseQueryAssistant",           # 课程查询
            "campus_event": "FacilityQueryAssistant",    # 校园活动查询
            "campus_news": "FacilityQueryAssistant",     # 校园新闻查询
            "canteen": "FacilityQueryAssistant",         # 餐厅查询
            "library_hours": "FacilityQueryAssistant",   # 图书馆开放时间查询
        }

        self.temperature = 0.1


    def get_mysql_config(self, env):
        """
        通过不同的环境获取不同的数据库配置
        :return:
        """
        if env == 'prod':
            # 数据库配置 生产
            self.host = 'localhost'
            self.user = 'root'
            self.password = 'root'
            self.database = 'cuhk_campus'
        elif env == 'dev':
            # 数据库配置 开发
            self.host = 'localhost1'
            self.user = 'root1'
            self.password = 'root1'
            self.database = 'cuhk_campus'
        elif env == 'test':
            # 数据库配置 测试
            self.host = 'localhost2'
            self.user = 'root2'
            self.password = 'root2'
            self.database = 'cuhk_campus'
        else:
            # 数据库配置 预生产
            self.host = 'localhost3'
            self.user = 'root3'
            self.password = 'root3'
            self.database = 'cuhk_campus'

        return self.host, self.user, self.password, self.database


if __name__ == '__main__':
    print(Config().log_file)
    print(Config().get_mysql_config(env))
