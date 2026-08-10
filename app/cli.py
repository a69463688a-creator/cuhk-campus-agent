#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: cli.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/6
描述: 命令行交互入口（CLI版本）
"""
import asyncio
import json
import uuid
from datetime import datetime
import pytz
import re
import requests
from python_a2a import AgentNetwork, TextContent, Message, MessageRole, Task
from langchain_openai import ChatOpenAI

from app.config import Config
from app.logging import logger
from app.prompts import SmartCampusPrompts

conf = Config()

# 初始化全局变量，用于模拟会话状态
messages = []
agent_network = None
llm = None
agent_urls = {}
conversation_history = ""


# 初始化代理网络和相关组件
def initialize_system():
    """
    初始化系统组件，包括代理网络、路由器、LLM和会话状态
    """
    global agent_network, llm, agent_urls, conversation_history
    agent_urls = {
        "CourseQueryAssistant": "http://localhost:5005",
        "FacilityQueryAssistant": "http://localhost:5006",
    }
    network = AgentNetwork(name="CUHK校园助手网络")
    network.add("CourseQueryAssistant", "http://localhost:5005")
    network.add("FacilityQueryAssistant", "http://localhost:5006")
    agent_network = network

    llm = ChatOpenAI(
        model=conf.model_name,
        api_key=conf.api_key,
        base_url=conf.base_url,
        temperature=0.1
    )

    conversation_history = ""

# 天气 API 调用
def fetch_weather():
    """调用 Open-Meteo API 获取 CUHK 区域天气"""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": 22.419,
        "longitude": 114.207,
        "current_weather": "true",
        "daily": "temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum",
        "timezone": "Asia/Shanghai",
        "forecast_days": 4
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return {"status": "success", "data": resp.json()}
    except Exception as e:
        logger.error(f"天气 API 调用失败: {e}")
        return {"status": "error", "message": str(e)}


def format_weather_for_prompt(data):
    """将 Open-Meteo 原始 JSON 转为 LLM 友好文本"""
    if data.get("status") != "success":
        return f"天气数据获取失败: {data.get('message', '未知错误')}"

    raw = data["data"]
    current = raw.get("current_weather", {})
    daily = raw.get("daily", {})

    lines = [
        f"当前温度: {current.get('temperature', 'N/A')}°C",
        f"风速: {current.get('windspeed', 'N/A')} km/h",
        f"天气代码: {current.get('weathercode', 'N/A')}",
    ]
    if daily:
        dates = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        codes = daily.get("weathercode", [])
        precip = daily.get("precipitation_sum", [])
        for i in range(min(len(dates), 4)):
            day_label = "今天" if i == 0 else f"第{i}天({dates[i]})"
            lines.append(
                f"{day_label}: {min_temps[i] if i < len(min_temps) else '?'}°C ~ "
                f"{max_temps[i] if i < len(max_temps) else '?'}°C, "
                f"天气代码 {codes[i] if i < len(codes) else '?'}, "
                f"降水 {precip[i] if i < len(precip) else '?'}mm"
            )
    return "\n".join(lines)


# 意图识别agent
def intent_agent(user_input):
    global conversation_history, llm

    chain = SmartCampusPrompts.intent_prompt() | llm

    current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
    intent_response = chain.invoke(
        {"conversation_history": '\n'.join(conversation_history.split("\n")[-6:]), "query": user_input,
         "current_date": current_date}).content.strip()
    logger.info(f"意图识别原始响应: {intent_response}")

    intent_response = re.sub(r'^```json\s*|\s*```$', '', intent_response).strip()
    logger.info(f"清理后响应: {intent_response}")
    intent_output = json.loads(intent_response)
    intents = intent_output.get("intents", [])
    user_queries = intent_output.get("user_queries", {})
    follow_up_message = intent_output.get("follow_up_message", "")
    logger.info(f"intents: {intents}||user_queries: {user_queries}||follow_up_message: {follow_up_message} ")

    return intents, user_queries, follow_up_message

# 处理用户输入的核心函数
def process_user_input(prompt):
    """
    处理用户输入：识别意图、调用代理、生成响应
    """
    global messages, conversation_history, llm
    messages.append({"role": "user", "content": prompt})
    conversation_history += f"\nUser: {prompt}"

    print("正在分析您的意图...")
    try:
        intents, user_queries, follow_up_message = intent_agent(prompt)

        if "out_of_scope" in intents:
            response = follow_up_message
            conversation_history += f"\nAssistant: {response}"
        elif follow_up_message != "":
            response = follow_up_message
            conversation_history += f"\nAssistant: {response}"
        else:
            responses = []
            routed_agents = []
            for intent in intents:
                logger.info(f"处理意图：{intent}")
                agent_name = conf.intent.get(intent)

                if intent == "recommend":
                    chain = SmartCampusPrompts.recommend_prompt() | llm
                    rec_response = chain.invoke({"query": prompt}).content.strip()
                    responses.append(rec_response)
                elif intent == "weather":
                    weather_data = fetch_weather()
                    weather_text = format_weather_for_prompt(weather_data)
                    chain = SmartCampusPrompts.summarize_weather_prompt() | llm
                    final = chain.invoke(
                        {"query": user_queries.get(intent, prompt), "raw_response": weather_text}).content.strip()
                    responses.append(final)
                elif agent_name:
                    query_str = user_queries.get(intent, {})
                    logger.info(f"{agent_name} 查询：{query_str}")
                    agent = agent_network.get_agent(agent_name)
                    chat_history = '\n'.join(conversation_history.split("\n")[-7:-1]) + f'\nUser: {query_str}'
                    message = Message(content=TextContent(text=chat_history), role=MessageRole.USER)
                    task = Task(id="task-" + str(uuid.uuid4()), message=message.to_dict())
                    raw_response = asyncio.run(agent.send_task_async(task))
                    logger.info(f"{agent_name} 原始响应: {raw_response}")
                    if raw_response.status.state == 'completed':
                        agent_result = raw_response.artifacts[0]['parts'][0]['text']
                    else:
                        agent_result = raw_response.status.message['content']['text']

                    if agent_name == "CourseQueryAssistant":
                        chain = SmartCampusPrompts.summarize_course_prompt() | llm
                        final_response = chain.invoke({"query": query_str, "raw_response": agent_result}).content.strip()
                    elif agent_name == "FacilityQueryAssistant":
                        chain = SmartCampusPrompts.summarize_facility_prompt() | llm
                        final_response = chain.invoke({"query": query_str, "raw_response": agent_result}).content.strip()
                    else:
                        final_response = agent_result

                    responses.append(final_response)
                    routed_agents.append(agent_name)
                else:
                    responses.append("暂不支持此意图。")

            response = "\n\n".join(responses)
            if routed_agents:
                logger.info(f"路由到代理：{routed_agents}")
            conversation_history += f"\nAssistant: {response}"

        print(f"\n助手回复：\n{response}\n")
        messages.append({"role": "assistant", "content": response})

    except json.JSONDecodeError as json_err:
        logger.error(f"意图识别JSON解析失败")
        error_message = f"意图识别JSON解析失败：{str(json_err)}。请重试。"
        print(f"\n助手回复：\n{error_message}\n")
        messages.append({"role": "assistant", "content": error_message})
    except Exception as e:
        logger.error(f"处理异常: {str(e)}")
        error_message = f"处理失败：{str(e)}。请重试。"
        print(f"\n助手回复：\n{error_message}\n")
        messages.append({"role": "assistant", "content": error_message})


def display_agent_cards():
    """显示所有代理的卡片信息"""
    print("\n🛠️ Agent Cards:")
    for agent_name in agent_network.agents.keys():
        agent_card = agent_network.get_agent_card(agent_name)
        agent_url = agent_urls.get(agent_name, "未知地址")
        print(f"\n--- Agent: {agent_name} ---")
        print(f"技能: {agent_card.skills}")
        print(f"描述: {agent_card.description}")
        print(f"地址: {agent_url}")
        print(f"状态: 在线")


# 主函数：脚本入口
if __name__ == "__main__":
    initialize_system()
    print("🎓 基于A2A的SmartCampus CUHK校园生活助手 v3.1")
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
    print("Powered by CUHK CS | 基于A2A的SmartCampus校园助手系统 v3.1")
