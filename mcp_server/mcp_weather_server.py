#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: mcp_course_server.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/4
描述: 课程信息 MCP 服务器 —— 基于 course_info 表提供课程查询工具
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

# 课程服务类
class CourseService:  # 定义课程服务类，封装数据库操作逻辑
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
            return json.dumps({"status": "success", "data": results} if results else {"status": "no_data", "message": "未找到课程数据，请确认课程代码和日期。"}, cls=DateEncoder, ensure_ascii=False)
        except Exception as e:
            logger.error(f"课程查询错误: {str(e)}")
            # 返回错误JSON响应
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


# 创建课程MCP服务器
def create_course_mcp_server():
    # 创建FastMCP实例
    course_mcp = FastMCP(name="CourseTools",
                         instructions="课程查询工具，基于 course_info 表。",
                         log_level="ERROR",
                         host="127.0.0.1", port=8002)

    # 实例化课程服务对象
    service = CourseService()

    @course_mcp.tool(
        name="query_courses",
        description="查询课程数据，输入 SQL，如 'SELECT * FROM course_info WHERE course_code = \"CSCI2100\"'"
    )
    def query_courses(sql: str) -> str:
        logger.info(f"执行课程查询: {sql}")
        return service.execute_query(sql)

    # 打印服务器信息
    logger.info("=== 课程MCP服务器信息 ===")
    logger.info(f"名称: {course_mcp.name}")
    logger.info(f"描述: {course_mcp.instructions}")

    # 运行服务器
    try:
        print("服务器已启动，请访问 http://127.0.0.1:8002/mcp")
        course_mcp.run(transport="streamable-http")  # 使用 streamable-http 传输方式
    except Exception as e:
        print(f"服务器启动失败: {e}")


if __name__ == '__main__':
    create_course_mcp_server()
