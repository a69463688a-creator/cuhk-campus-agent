#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: facility_server.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/4
描述: 校园设施 MCP 服务器 —— 基于 campus_events/campus_news/canteen/library_hours
      表提供设施查询工具（端口 8001）
"""
from mcp.server import MCPServer

from app.config import Config
from app.logging import logger
from data.database import FacilityService

conf = Config()


# 创建设施查询MCP服务器
def create_facility_mcp_server():
    facility_mcp = MCPServer(
        name="FacilityTools",
        instructions="校园设施查询工具，基于 campus_events, campus_news, canteen, library_hours 表。只支持查询。",
        log_level="ERROR",
    )

    service = FacilityService()

    @facility_mcp.tool(
        name="query_facilities",
        description="查询校园设施数据，输入 SQL，如 'SELECT * FROM canteen WHERE location LIKE \"%Chung Chi%\"'"
    )
    def query_facilities(sql: str) -> str:
        logger.info(f"执行设施查询: {sql}")
        return service.execute_query(sql)

    @facility_mcp.tool(
        name="get_facility_schema",
        description="返回 campus_events, campus_news, canteen, library_hours 四张表的完整结构"
    )
    def get_facility_schema() -> str:
        logger.info("获取设施表结构")
        return service.get_all_schemas()

    logger.info("=== 校园设施MCP服务器信息 ===")
    logger.info(f"名称: {facility_mcp.name}")
    logger.info(f"描述: {facility_mcp.instructions}")

    try:
        print("服务器已启动，请访问 http://127.0.0.1:8001/mcp")
        facility_mcp.run(transport="streamable-http", host="127.0.0.1", port=8001)
    except Exception as e:
        print(f"服务器启动失败: {e}")


if __name__ == '__main__':
    create_facility_mcp_server()
