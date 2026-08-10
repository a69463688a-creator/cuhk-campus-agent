#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: test_booking_agent_server.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/6
描述: 预约 Agent 服务器测试脚本
"""
import asyncio
import uuid

from python_a2a import A2AClient, Message, TextContent, MessageRole, Task

from config import Config
from create_logger import logger

conf = Config()


def main():
    # 初始化预约客户端
    booking_client = A2AClient("http://localhost:5007")

    # 获取预约代理信息
    try:
        logger.info("获取校园预约助手信息")
        logger.info(f"名称: {booking_client.agent_card.name}")
        logger.info(f"描述: {booking_client.agent_card.description}")
        logger.info(f"版本: {booking_client.agent_card.version}")
        if booking_client.agent_card.skills:
            logger.info("支持技能:")
            for skill in booking_client.agent_card.skills:
                logger.info(f"- {skill.name}: {skill.description}")
                if skill.examples:
                    logger.info(f"  示例: {', '.join(skill.examples)}")
    except Exception as e:
        logger.error(f"无法获取预约助手信息: {str(e)}")

    # 交互循环
    while True:
        user_input = input("输入您的校园预约需求（输入 'exit' 退出）：")
        if user_input.lower() == 'exit':
            break

        try:
            query = user_input.strip()
            logger.info(f"用户查询 (预约): {query}")

            # 发送查询
            logger.info("正在查询数据...")
            message_booking = Message(content=TextContent(text=query), role=MessageRole.USER)
            task_booking = Task(id="task-" + str(uuid.uuid4()), message=message_booking.to_dict())

            # 发送任务并获取最终结果
            booking_result_task = asyncio.run(booking_client.send_task_async(task_booking))
            logger.info(f"原始响应: {booking_result_task}")

            # 打印输出
            if booking_result_task.status.state == 'completed':
                print(booking_result_task.artifacts[0]["parts"][0]["text"])
            else:
                print(booking_result_task.status.message['content']['text'])
        except Exception as e:
            error_message = f"预约失败: {str(e)}"
            logger.error(error_message)


if __name__ == "__main__":
    print("校园预约Agent Server查询客户端测试脚本")
    main()
