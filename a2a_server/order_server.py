#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: booking_server.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/6
描述: 预约 A2A Agent 服务器 —— 自习室预约/图书馆座位预约/校园活动报名（端口 5007）
"""
import asyncio
import uuid

from langchain_openai import ChatOpenAI
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from python_a2a import AgentCard, AgentSkill, run_server, TaskStatus, TaskState, A2AServer, A2AClient, Message, \
    TextContent, MessageRole, Task

from create_logger import logger
from config import Config

conf = Config()

# 初始化LLM
llm = ChatOpenAI(
    model=conf.model_name,
    base_url=conf.base_url,
    api_key=conf.api_key,
    temperature=conf.temperature
)

# 定义预约函数
async def book_resource(query):
    try:
        # 启动 MCP server，通过streamable建立连接
        async with streamablehttp_client("http://127.0.0.1:8003/mcp") as (read, write, _):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                try:
                    await session.initialize()

                    # 从 session 自动获取 MCP server 提供的工具列表。
                    tools = await load_mcp_tools(session)
                    # print(f"tools-->{tools}")

                    # 创建 agent 的提示模板
                    prompt = ChatPromptTemplate.from_messages([
                        ("system",
                         "你是一个CUHK校园预约助手，能够调用工具来完成自习室预约、图书馆座位预约或校园活动报名。你需要仔细分析工具需要的参数，然后从用户提供的信息中提取信息。如果用户提供的信息不足以提取到调用工具所有必要参数，则向用户追问，以获取该信息。不能自己编撰参数。"),
                        ("human", "{input}"),
                        ("placeholder", "{agent_scratchpad}"),
                    ])

                    # 构建工具调用代理
                    agent = create_tool_calling_agent(llm, tools, prompt)

                    # 创建代理执行器
                    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

                    # 代理调用
                    response = await agent_executor.ainvoke({"input": query})

                    return {"status": "success", "message": f"{response['output']}"}
                except Exception as e:
                    logger.error(f"预约 MCP 调用出错：{str(e)}")
                    return {"status": "error", "message": f"预约 MCP 调用出错：{str(e)}"}
    except Exception as e:
        logger.error(f"连接或会话初始化时发生错误: {e}")
        return {"status": "error", "message": "连接或会话初始化时发生错误"}


# Agent 卡片定义
agent_card = AgentCard(
    name="BookingAssistant",
    description="通过MCP提供CUHK校园预约服务的助手",
    url="http://localhost:5007",
    version="1.0.4",
    capabilities={"streaming": True, "memory": True},
    skills=[
        AgentSkill(
            name="execute campus booking",
            description="根据客户端提供的输入执行校园资源预约（自习室/图书馆座位/校园活动），返回执行结果",
            examples=["预约YIA301自习室 2026-08-15 全天",
                      "预约University Library 2楼 Quiet Study Zone 2026-08-15 上午",
                      "报名 CUHK Career Fair 2026"]
        )
    ]
)


# 预约服务器类
class BookingServer(A2AServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)
        # 初始化一个大模型
        self.llm = llm
        # 初始化一个设施查询客户端（用于查询余量）
        self.facility_client = A2AClient("http://localhost:5006")

    # 处理任务：提取输入，查询余量，调用MCP，结果输出
    def handle_task(self, task):
        content = (task.message or {}).get("content", {})  # 从消息中获取内容
        # 提取conversation，即客户端发起的任务中的query语句
        conversation = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"对话历史及用户问题: {conversation}")

        try:
            # 2 调用设施查询agent查询余量
            message_facility = Message(content=TextContent(text=conversation), role=MessageRole.USER)
            task_facility = Task(id="task-" + str(uuid.uuid4()), message=message_facility.to_dict())

            # 发送任务并获取最终结果
            facility_result_task = asyncio.run(self.facility_client.send_task_async(task_facility))
            logger.info(f"原始响应: {facility_result_task}")

            # 处理结果：未查到余量信息时，则返回提示信息
            if facility_result_task.status.state != 'completed':
                required_message = facility_result_task.status.message['content']['text']
                logger.info(f'余量未查到：{required_message}')
                task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                         message={"role": "agent", "content": {"text": required_message}})
                return task
            # 处理结果：查到余量信息时，进行预约
            facility_result = facility_result_task.artifacts[0]["parts"][0]["text"]
            logger.info(f"余量信息: {facility_result}")

            # 3 调用MCP预约  用户问题 + \n余量信息： + 调用设施查询agent的结果
            book_result = asyncio.run(book_resource(conversation + '\n余量信息：' + facility_result))
            logger.info(f"MCP 返回: {book_result}")

            # 4 结果输出
            data = book_result.get("message", '')
            logger.info(f"预约结果: {data}")
            # 检查响应状态
            if book_result.get("status") == "success":
                result = '余量信息：' + facility_result + '\n预约结果：' + data
                # 设置任务产物为文本部分，并设置任务状态为完成
                task.artifacts = [{"parts": [{"type": "text", "text": result}]}]
                task.status = TaskStatus(state=TaskState.COMPLETED)
            else:
                # 设置任务状态为失败，添加错误信息
                task.status = TaskStatus(state=TaskState.FAILED,
                                         message={"role": "agent", "content": {"text": data}})
            return task
        except Exception as e:  # 捕获异常
            logger.error(f"预约失败: {str(e)}")

            # 设置任务状态为失败，添加错误信息
            task.status = TaskStatus(state=TaskState.FAILED,
                                     message={"role": "agent", "content": {"text": f"预约失败: {str(e)} 请重试或提供更多细节。"}})
            return task



if __name__ == "__main__":
    # 创建并运行服务器
    # 实例化预约服务器
    booking_server = BookingServer()
    # 打印服务器信息
    print("\n=== 服务器信息 ===")
    print(f"名称: {booking_server.agent_card.name}")
    print(f"描述: {booking_server.agent_card.description}")
    print("\n技能:")
    for skill in booking_server.agent_card.skills:
        print(f"- {skill.name}: {skill.description}")
    # 运行服务器
    run_server(booking_server, host="127.0.0.1", port=5007)
