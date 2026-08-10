#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: test_course_mcp_server.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/4
描述: 课程 MCP 服务器测试脚本
"""
import asyncio
import json

from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# 定义服务器地址
server_url = "http://127.0.0.1:8002/mcp"

async def test_course_mcp():
    try:
        # 启动 MCP server，通过streamable建立连接
        async with streamablehttp_client(server_url) as (read, write, _):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                try:
                    await session.initialize()
                    print("会话初始化成功，可以开始调用工具。")

                    # 从 session 自动获取 MCP server 提供的工具列表。
                    tools = await load_mcp_tools(session)
                    print(f"tools-->{tools}")

                    # 测试1: 查询指定课程
                    sql = "SELECT * FROM course_info WHERE course_code = 'CSCI2100'"
                    result = await session.call_tool("query_courses", {"sql": sql})
                    print(11111, result)

                    print(22222, isinstance(result, str))
                    # False
                    result_data = json.loads(result) if isinstance(result, str) else result
                    print(f"课程查询结果：{result_data}")

                    # 测试2: 查询院系课程
                    # sql_department = "SELECT * FROM course_info WHERE department = 'CSCI'"
                    # result_department = await session.call_tool("query_courses", {"sql": sql_department})
                    # result_department_data = json.loads(result_department) if isinstance(result_department, str) else result_department
                    # print(f"院系课程查询结果：{result_department_data}")
                except Exception as e:
                    print(f"课程 MCP 测试出错：{str(e)}")
    except Exception as e:
        print(f"连接或会话初始化时发生错误: {e}")
        print("请确认课程MCP服务端脚本已启动并运行在 http://127.0.0.1:8002/mcp")


if __name__ == "__main__":
    asyncio.run(test_course_mcp())
