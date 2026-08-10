#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: query1.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/4
描述: 校园设施数据服务类，封装MySQL查询逻辑
"""

import mysql.connector
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from mcp.server.fastmcp import FastMCP

from config import Config
from create_logger import logger
from utils.format import DateEncoder, default_encoder

conf = Config()


# 校园设施服务类
class FacilityService:  # 定义校园设施服务类，封装数据库操作逻辑
    def __init__(self):  # 初始化方法，建立数据库连接
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

    # 定义执行SQL查询方法，输入SQL字符串，返回JSON字符串
    def execute_query(self, sql: str) -> str:
        try:
            self._ensure_connection()  # 确保连接有效
            cursor = self.conn.cursor(dictionary=True)
            cursor.execute(sql)
            results = cursor.fetchall()
            cursor.close()
            # 格式化结果
            for result in results:  # 遍历每个结果字典
                for key, value in result.items():
                    if isinstance(value, (date, datetime, timedelta, Decimal)):  # 检查值是否为特殊类型
                        result[key] = default_encoder(value)  # 使用自定义编码器格式化该值
            # 序列化为JSON，如果有结果返回success，否则no_data；使用DateEncoder，非ASCII不转义
            return json.dumps({"status": "success", "data": results} if results else {"status": "no_data",
                                                                                      "message": "未找到相关数据，请确认查询条件。"},
                              cls=DateEncoder, ensure_ascii=False)
        except Exception as e:
            logger.error(f"设施查询错误: {str(e)}")
            # 返回错误JSON响应
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
