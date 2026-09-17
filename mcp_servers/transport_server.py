#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: transport_server.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/9/17
描述: 校园交通 MCP 服务器 —— 基于 bus_routes / bus_stops 表提供查询 + 路线规划工具（端口 8003）
"""
from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from app.config import Config
from app.logging import logger
from app.observability import set_trace_id
from data.transport import TransportService

conf = Config()


def _inject_trace_id(ctx: Context) -> None:
    """从 MCP 请求的 _meta 中提取 trace_id 并注入当前上下文，实现跨进程链路关联"""
    meta = ctx.request_context.meta or {}
    trace_id = meta.get("trace_id")
    if trace_id:
        set_trace_id(trace_id)


def create_transport_mcp_server():
    transport_mcp = MCPServer(
        name="TransportTools",
        instructions="校园交通查询工具，基于 bus_routes, bus_stops 表，支持 SQL 只读查询与站点间路线规划。",
        log_level="ERROR",
    )

    service = TransportService()

    @transport_mcp.tool(
        name="query_transport",
        description="查询校园交通数据，输入 SQL，如 'SELECT * FROM bus_routes WHERE route_code = \"3\"'"
    )
    def query_transport(sql: str, ctx: Context) -> str:
        _inject_trace_id(ctx)
        logger.info(f"执行交通查询: {sql}")
        return service.execute_query(sql)

    @transport_mcp.tool(
        name="get_transport_schema",
        description="返回 bus_routes, bus_stops 两张表的完整结构"
    )
    def get_transport_schema(ctx: Context) -> str:
        _inject_trace_id(ctx)
        logger.info("获取交通表结构")
        return service.get_all_schemas()

    @transport_mcp.tool(
        name="find_route",
        description="规划从起点站到终点站的校巴路线，返回最少换乘、其次最少站数的行程（含换乘点）"
    )
    def find_route(origin: str, destination: str, ctx: Context) -> str:
        _inject_trace_id(ctx)
        logger.info(f"路线规划: {origin} -> {destination}")
        return service.find_route(origin, destination)

    logger.info("=== 校园交通MCP服务器信息 ===")
    logger.info(f"名称: {transport_mcp.name}")
    logger.info(f"描述: {transport_mcp.instructions}")

    try:
        print("服务器已启动，请访问 http://127.0.0.1:8003/mcp")
        transport_mcp.run(transport="streamable-http", host="127.0.0.1", port=8003)
    except Exception as e:
        print(f"服务器启动失败: {e}")


if __name__ == '__main__':
    create_transport_mcp_server()
