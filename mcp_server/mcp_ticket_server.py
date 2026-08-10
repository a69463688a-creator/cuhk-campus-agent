#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: mcp_facility_server.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/4
描述: 校园设施 MCP 服务器 —— 基于 study_rooms, library_seats, campus_events 表提供设施查询工具
"""
import mysql.connector
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from mcp.server.fastmcp import FastMCP

from config import Config
from create_logger import logger
from utils.format import DateEncoder, default_encoder
from query_data.query1 import FacilityService

conf = Config()



# 创建设施查询MCP服务器
def create_facility_mcp_server():
    # 创建FastMCP实例
    facility_mcp = FastMCP(name="FacilityTools",
                         instructions="校园设施查询工具，基于 study_rooms, library_seats, campus_events 表。只支持查询。",
                         log_level="ERROR",
                         host="127.0.0.1", port=8001)

    # 实例化设施服务对象
    service = FacilityService()

    @facility_mcp.tool(
        name="query_facilities",
        description="查询校园设施数据，输入 SQL，如 'SELECT * FROM study_rooms WHERE building = \"Yasumoto International Academic Park\"'"
    )
    def query_facilities(sql: str) -> str:
        logger.info(f"执行设施查询: {sql}")
        return service.execute_query(sql)

    # 打印服务器信息
    logger.info("=== 校园设施MCP服务器信息 ===")
    logger.info(f"名称: {facility_mcp.name}")
    logger.info(f"描述: {facility_mcp.instructions}")

    # 运行服务器
    try:
        print("服务器已启动，请访问 http://127.0.0.1:8001/mcp")
        facility_mcp.run(transport="streamable-http")  # 使用 streamable-http 传输方式
    except Exception as e:
        print(f"服务器启动失败: {e}")

create_facility_mcp_server()
