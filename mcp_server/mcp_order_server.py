#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: mcp_booking_server.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/4
描述: 预约 MCP 服务器 —— 提供自习室预约、图书馆座位预约、校园活动报名工具
"""
from mcp.server.fastmcp import FastMCP

from config import Config
from create_logger import logger

conf = Config()

# 创建FastMCP实例
booking_mcp = FastMCP(name="BookingTools",
                    instructions="校园预约工具，完成自习室预约、图书馆座位预约和校园活动报名。",
                    log_level="ERROR",
                    host="127.0.0.1", port=8003)


@booking_mcp.tool(
    name="book_study_room",
    description="根据日期、教学楼、教室编号、时间段预约自习室"
)
def book_study_room(room_date: str, building: str, room_number: str, start_time: str, end_time: str) -> str:
    '''
    Args:
        room_date (str): 预约日期，如 '2026-08-15'
        building (str): 教学楼名称，如 'Yasumoto International Academic Park'
        room_number (str): 教室编号，如 'YIA301'
        start_time (str): 开始时间，如 '08:00'
        end_time (str): 结束时间，如 '22:00'
    '''
    logger.info(f"正在预约自习室: {room_date}, {building}, {room_number}, {start_time}-{end_time}")
    logger.info(f"恭喜，自习室预约成功！")
    return "恭喜，自习室预约成功！"

@booking_mcp.tool(
    name="book_library_seat",
    description="根据日期、图书馆、楼层、区域、时间段预约图书馆座位"
)
def book_library_seat(seat_date: str, library_name: str, floor: int, zone: str, time_slot: str) -> str:
    '''
    Args:
        seat_date (str): 预约日期，如 '2026-08-15'
        library_name (str): 图书馆名称，如 'University Library'
        floor (int): 楼层
        zone (str): 区域名称
        time_slot (str): 时间段，如 '09:00-12:00'
    '''
    logger.info(f"正在预约图书馆座位: {seat_date}, {library_name}, Floor {floor}, {zone}, {time_slot}")
    logger.info(f"恭喜，图书馆座位预约成功！")
    return "恭喜，图书馆座位预约成功！"


@booking_mcp.tool(
    name="register_event",
    description="根据活动名称、场地、时间报名校园活动"
)
def register_event(start_date: str, event_name: str, venue: str) -> str:
    '''
    Args:
        start_date (str): 活动日期，如 '2026-09-15'
        event_name (str): 活动名称，如 'CUHK Career Fair 2026'
        venue (str): 活动场地，如 'Sir Run Run Shaw Hall'
    '''
    logger.info(f"正在报名活动: {start_date}, {event_name}, {venue}")
    logger.info(f"恭喜，活动报名成功！")
    return "恭喜，活动报名成功！"


# 创建预约MCP服务器
def create_booking_mcp_server():
    # 打印服务器信息
    logger.info("=== 校园预约MCP服务器信息 ===")
    logger.info(f"名称: {booking_mcp.name}")
    logger.info(f"描述: {booking_mcp.instructions}")

    # 运行服务器
    try:
        print("服务器已启动，请访问 http://127.0.0.1:8003/mcp")
        booking_mcp.run(transport="streamable-http")  # 使用 streamable-http 传输方式
    except Exception as e:
        print(f"服务器启动失败: {e}")


if __name__ == "__main__":
    # 调用创建服务器函数
    create_booking_mcp_server()
