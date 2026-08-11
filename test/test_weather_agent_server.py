#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: test_course_agent_server.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/4
描述: 课程 Agent 服务器测试脚本
"""
import asyncio
import uuid

from python_a2a import A2AClient, Message, TextContent, MessageRole, Task
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.config import Config
from app.logging import logger
from app.llm import create_llm

conf = Config()

# 初始化 LLM
llm = create_llm()

# 课程总结提示模板
course_prompt = ChatPromptTemplate.from_template(
    """
    您是一位CUHK课程顾问，以清晰、友好的风格为用户介绍课程查询结果。基于以下查询结果，生成一段总结：
    - 突出课程代码、课程名称、授课教师、上课时间、地点、学分和类别。
    - 使用顾问的语气，例如"为您查询到以下课程信息..."
    - 如果结果为空，建议用户尝试其他查询条件。
    - 保持中文叙述，字数控制在 100-150 字。

    查询结果：
    {course}

    总结：
    """
)

def main():
    # 初始化课程查询客户端
    course_client = A2AClient("http://localhost:5005")

    # 获取课程代理信息
    try:
        logger.info("获取课程助手信息")
        logger.info(f"名称: {course_client.agent_card.name}")
        logger.info(f"描述: {course_client.agent_card.description}")
        logger.info(f"版本: {course_client.agent_card.version}")
        if course_client.agent_card.skills:
            logger.info("支持技能:")
            for skill in course_client.agent_card.skills:
                logger.info(f"- {skill.name}: {skill.description}")
                if skill.examples:
                    logger.info(f"  示例: {', '.join(skill.examples)}")
    except Exception as e:
        logger.error(f"无法获取课程助手信息: {str(e)}")

    # 交互循环
    while True:
        user_input = input("输入您的课程查询（输入 'exit' 退出）：")
        if user_input.lower() == 'exit':
            break

        try:
            query = user_input.strip()
            logger.info(f"用户查询 (课程): {query}")

            # 发送查询
            logger.info("正在查询数据...")
            message_course = Message(content=TextContent(text=query), role=MessageRole.USER)
            task_course = Task(id="task-" + str(uuid.uuid4()), message=message_course.to_dict())

            course_result_task = asyncio.run(course_client.send_task_async(task_course))
            logger.info(f"原始响应: {course_result_task}")

            # 生成 LLM 总结
            if course_result_task.status.state == 'completed':
                try:
                    summary_chain = course_prompt | llm
                    course_result = course_result_task.artifacts[0]["parts"][0]["text"]
                    summary = summary_chain.invoke({"course": course_result}).content.strip()
                    logger.info(f"**课程顾问总结**:\n{summary}")
                except Exception as e:
                    error_message = f"生成总结失败: {str(e)}"
                    logger.error(error_message)
            else:
                logger.info(course_result_task.status.message['content']['text'])
        except Exception as e:
            error_message = f"查询失败: {str(e)}"
            logger.error(error_message)


if __name__ == "__main__":
    print("课程Agent Server查询客户端测试脚本")
    main()
