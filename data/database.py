#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: database.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/4
描述: 校园设施数据服务类，封装MySQL查询逻辑
"""

import mysql.connector
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.config import Config
from app.logging import logger
from app.security import validate_readonly_sql
from data.format import DateEncoder, default_encoder

conf = Config()


# 校园设施服务类
class FacilityService:
    """封装 campus_events / campus_news / canteen / library_hours 的 MySQL 查询"""
    def __init__(self):
        self.host = conf.host
        self.user = conf.user
        self.password = conf.password
        self.database = conf.database
        self._connect()

    def _connect(self):
        """建立数据库连接"""
        self.conn = mysql.connector.connect(
            host=self.host,
            user=self.user,
            password=self.password,
            database=self.database
        )

    def _ensure_connection(self):
        """确保数据库连接有效，如果断开则重连"""
        try:
            if not self.conn.is_connected():
                logger.warning("MySQL 连接已断开，正在重连...")
                self._connect()
                logger.info("MySQL 重连成功")
        except Exception:
            logger.warning("MySQL 连接检查失败，正在重连...")
            self._connect()
            logger.info("MySQL 重连成功")

    def execute_query(self, sql: str) -> str:
        try:
            validate_readonly_sql(sql)
            self._ensure_connection()
            cursor = self.conn.cursor(dictionary=True)
            cursor.execute(sql)
            results = cursor.fetchall()
            cursor.close()
            for result in results:
                for key, value in result.items():
                    if isinstance(value, (date, datetime, timedelta, Decimal)):
                        result[key] = default_encoder(value)
            return json.dumps(
                {"status": "success", "data": results} if results
                else {"status": "no_data", "message": "未找到相关数据，请确认查询条件。"},
                cls=DateEncoder, ensure_ascii=False
            )
        except Exception as e:
            logger.error(f"设施查询错误: {str(e)}")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
