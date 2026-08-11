#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: course_agent.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/4
描述: 课程查询 A2A Agent 服务器（端口 5005）
"""
import json
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from python_a2a import A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from datetime import datetime
import pytz

from app.config import Config
from app.logging import logger
from app.llm import create_llm

conf = Config()

# 初始化LLM
llm = create_llm()

# 数据表 schema
table_schema_string = """  # 定义课程数据表的SQL schema字符串，用于Prompt上下文
CREATE TABLE IF NOT EXISTS course_info (
id INT AUTO_INCREMENT PRIMARY KEY,
course_code VARCHAR(20) NOT NULL COMMENT '课程代码',
course_name VARCHAR(100) NOT NULL COMMENT '课程名称',
department VARCHAR(50) NOT NULL COMMENT '开课院系',
instructor VARCHAR(50) COMMENT '授课教师',
schedule_day VARCHAR(10) COMMENT '上课日',
start_time TIME COMMENT '开始时间',
end_time TIME COMMENT '结束时间',
classroom VARCHAR(50) COMMENT '教室编号',
building VARCHAR(80) COMMENT '教学楼名称',
credits INT DEFAULT 3 COMMENT '学分数',
capacity INT COMMENT '课容量上限',
enrolled INT DEFAULT 0 COMMENT '已选课人数',
category VARCHAR(30) COMMENT '课程类别',
description TEXT COMMENT '课程简介',
update_time DATETIME COMMENT '数据更新时间',
UNIQUE KEY unique_course_time (course_code, schedule_day, start_time)
) ENGINE=INNODB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='课程信息表';
"""

# 生成SQL的提示词
sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是一个专业的CUHK课程SQL生成器，需要从对话历史（含用户的问题）中提取关键信息，然后基于course_info表生成SELECT语句。
- 如果用户需要查课程，则至少需要课程代码或课程名称信息。如果对话历史中缺乏必要的信息，可以向其追问，输出格式为json格式，如示例所示；如果对话历史中信息齐全，则输出纯SQL即可。
- 如果用户问与课程无关的问题，则模仿最后2个示例回复即可。


示例：
- 对话: user: CSCI2100
输出: SELECT course_code, course_name, department, instructor, schedule_day, start_time, end_time, classroom, building, credits, capacity, enrolled, category FROM course_info WHERE course_code = 'CSCI2100'
- 对话: user: Data Structures 这门课
输出: SELECT course_code, course_name, department, instructor, schedule_day, start_time, end_time, classroom, building, credits, capacity, enrolled, category FROM course_info WHERE course_name LIKE '%Data Structures%'

- 对话: user: 有什么课
输出: {{"status": "input_required", "message": "请提供具体的课程代码或课程名称，例如 'CSCI2100' 或 'Data Structures'。"}}
- 对话: user: CSCI
assistant: 请提供具体的课程代码。
user: CSCI3100
输出: SELECT course_code, course_name, department, instructor, schedule_day, start_time, end_time, classroom, building, credits, capacity, enrolled, category FROM course_info WHERE course_code = 'CSCI3100'
- 对话: user: CSCI4180的上课时间\nassistant: 周一和周三16:30-18:15在Science Centre。\nuser: 那CSCI4430呢
输出: SELECT course_code, course_name, department, instructor, schedule_day, start_time, end_time, classroom, building, credits, capacity, enrolled, category FROM course_info WHERE course_code = 'CSCI4430'

- 对话: user: 你好
输出: {{"status": "input_required", "message": "请提供课程代码或课程名称，例如 'CSCI2100' 或 'Data Structures'。"}}
- 对话: user: 今天有什么好吃的
输出: {{"status": "input_required", "message": "请提供课程相关查询，包括课程代码或课程名称。"}}

course_info表结构：{table_schema_string}
对话历史: {conversation}
当前日期: {current_date} (Asia/Shanghai)
    """
)


# 定义查询函数
async def get_courses(sql):
    try:
        # 启动 MCP server，通过streamable建立连接
        async with streamable_http_client("http://127.0.0.1:8002/mcp") as (read, write):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                try:
                    await session.initialize()
                    # 工具调用
                    result = await session.call_tool("query_courses", {"sql": sql})
                    result_data = json.loads(result) if isinstance(result, str) else result
                    logger.info(f"课程查询结果：{result_data}")
                    return result_data.content[0].text
                except Exception as e:
                    logger.error(f"课程 MCP 查询出错：{str(e)}")
                    return {"status": "error", "message": f"课程 MCP 查询出错：{str(e)}"}
    except Exception as e:
        logger.error(f"连接或会话初始化时发生错误: {e}")
        return {"status": "error", "message": "连接或会话初始化时发生错误"}

# Agent卡片定义
agent_card = AgentCard(
    name="CourseQueryAssistant",
    description="基于LangChain提供CUHK课程查询服务的助手",
    url="http://localhost:5005",
    version="1.0.0",
    capabilities={"streaming": True, "memory": True},
    skills=[
        AgentSkill(
            name="execute course query",
            description="执行课程查询，返回课程数据库结果，支持自然语言输入",
            examples=["CSCI2100 上课时间", "Data Structures 课程信息", "有哪些CS选修课"]
        )
    ]
)

# 课程查询服务器类
class CourseQueryServer(A2AServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)
        self.llm = llm
        self.sql_prompt = sql_prompt
        self.schema = table_schema_string

    # 定义生成SQL查询方法，输入对话历史，返回SQL或追问JSON
    def generate_sql_query(self, conversation: str) -> dict:
        try:
            # 组装链
            chain = self.sql_prompt | self.llm
            # 调用链
            current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
            output = chain.invoke({"conversation": conversation, "current_date": current_date, "table_schema_string": self.schema}).content.strip()
            logger.info(f"原始 LLM 输出: {output}")
            # 处理结果，返回字典
            if output.startswith('{'):
                return json.loads(output)
            return {"status": "sql", "sql": output}
        except Exception as e:
            logger.error(f"SQL生成失败: {str(e)}")
            return {"status": "input_required", "message": "查询无效，请提供课程代码或名称。"}

    # 处理任务：提取输入，生成SQL，调用MCP，格式化结果
    def handle_task(self, task):
        # 1 提取输入
        content = (task.message or {}).get("content", {})
        conversation = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"对话历史及用户问题: {conversation}")

        try:
            # 2 基于用户问题生成SQL查询
            gen_result = self.generate_sql_query(conversation)
            if gen_result["status"] == "input_required":
                task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                         message={"role": "agent", "content": {"text": gen_result["message"]}})
                return task

            sql_query = gen_result["sql"]
            logger.info(f"生成的SQL查询: {sql_query}")

            # 3 调用MCP
            course_result = asyncio.run(get_courses(sql_query))

            # 4 格式化结果
            response = json.loads(course_result) if isinstance(course_result, str) else course_result
            logger.info(f"MCP 返回: {response}")
            if response.get("status") == "success":
                data = response.get("data", [])
                response_text = "\n".join([
                    f"{d['course_code']} {d['course_name']} | {d['instructor']} | {d['schedule_day']} {d['start_time']}-{d['end_time']} | {d['building']} {d['classroom']} | {d['category']} | 学分:{d['credits']} | 已选:{d['enrolled']}/{d['capacity']}"
                    for d in data])

                task.artifacts = [{"parts": [{"type": "text", "text": response_text}]}]
                task.status = TaskStatus(state=TaskState.COMPLETED)
            elif response.get("status") == "no_data":
                response_text = response.get("message", "请重新输入查询的课程代码或名称。")
                task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                         message={"role": "agent", "content": {"text": response_text}})
            else:
                response_text = response.get("message", "查询失败，请重试或提供更多细节。")
                task.status = TaskStatus(state=TaskState.FAILED,
                                         message={"role": "agent", "content": {"text": response_text}})

            return task
        except Exception as e:
            logger.error(f"查询失败: {str(e)}")
            task.status = TaskStatus(state=TaskState.FAILED,
                                     message={"role": "agent",
                                              "content": {"text": f"查询失败: {str(e)} 请重试或提供更多细节。"}})
            return task


if __name__ == "__main__":
    course_server = CourseQueryServer()
    print("\n=== 服务器信息 ===")
    print(f"名称: {course_server.agent_card.name}")
    print(f"描述: {course_server.agent_card.description}")
    print("\n技能:")
    for skill in course_server.agent_card.skills:
        print(f"- {skill.name}: {skill.description}")
    run_server(course_server, host="127.0.0.1", port=5005)
