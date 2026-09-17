#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: cli.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/6
描述: 命令行交互入口（CLI 版本）—— 作为纯 A2A client 调用 OrchestratorAgent

意图识别、路由委派、结果聚合全部由 OrchestratorAgent 完成，CLI 不再重复实现。
"""
import asyncio
import json
import uuid

from python_a2a import AgentNetwork, TextContent, Message, MessageRole, Task

from app.config import Config
from app.a2a_types import status_message_text
from app.logging import logger

conf = Config()

# 全局会话状态（CLI 用内存维护对话历史，Orchestrator 无状态）
conversation_history = ""
agent_network = None


def initialize_system():
    """初始化代理网络（指向 OrchestratorAgent）与会话状态"""
    global agent_network, conversation_history
    network = AgentNetwork(name="CUHK校园助手网络")
    network.add("OrchestratorAgent", conf.orchestrator_url)
    agent_network = network
    conversation_history = ""


def call_orchestrator(query: str, history: str) -> str:
    """向 OrchestratorAgent 发送编排任务，返回最终回答。"""
    agent = agent_network.get_agent("OrchestratorAgent")
    payload = json.dumps(
        {"query": query, "conversation_history": history}, ensure_ascii=False
    )
    message = Message(content=TextContent(text=payload), role=MessageRole.USER)
    task = Task(id="task-" + str(uuid.uuid4()), message=message.to_dict())

    raw_response = asyncio.run(agent.send_task_async(task))
    state = raw_response.status.state.value  # TaskState(str,Enum) → "completed"/"input-required"/"failed"
    if state == 'completed':
        return raw_response.artifacts[0]['parts'][0]['text']
    text = status_message_text(raw_response.status.message)
    if state == 'input-required':
        return f"💡 {text}"  # 追问：提示用户补充信息后重跑
    return text


def process_user_input(prompt):
    """处理用户输入：发送编排任务、打印回复、维护对话历史"""
    global conversation_history
    print("正在分析您的意图...")
    try:
        response = call_orchestrator(prompt, conversation_history)
        conversation_history += f"\nUser: {prompt}\nAssistant: {response}"
        print(f"\n助手回复：\n{response}\n")
    except Exception as e:
        logger.error(f"处理异常: {str(e)}")
        error_message = f"处理失败：{str(e)}。请重试。"
        print(f"\n助手回复：\n{error_message}\n")


def display_agent_cards():
    """显示所有代理的卡片信息"""
    print("\n🛠️ Agent Cards:")
    for agent_name in agent_network.agents.keys():
        agent_card = agent_network.get_agent_card(agent_name)
        print(f"\n--- Agent: {agent_name} ---")
        print(f"技能: {agent_card.skills}")
        print(f"描述: {agent_card.description}")
        print(f"地址: {agent_card.url}")
        print(f"状态: 在线")


# 主函数：脚本入口
if __name__ == "__main__":
    initialize_system()
    print("🎓 基于A2A的SmartCampus CUHK校园生活助手 v3.7")
    print("支持查询：课程 | 校园活动 | 校园新闻 | 餐厅 | 图书馆开放时间 | 天气 | 推荐")
    print("输入问题按回车提交；输入'quit'退出；输入'cards'查看代理卡片。")

    display_agent_cards()

    while True:
        prompt = input("\n请输入您的问题: ").strip()
        if prompt.lower() == 'quit':
            print("感谢使用SmartCampus！再见！")
            break
        elif prompt.lower() == 'cards':
            display_agent_cards()
            continue
        elif not prompt:
            continue
        else:
            process_user_input(prompt)

    print("\n---")
    print("Powered by CUHK CS | 基于A2A的SmartCampus校园助手系统 v3.7")
