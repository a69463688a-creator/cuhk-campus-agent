#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: facility_agent.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/6
描述: 校园设施查询 A2A Agent 服务器 —— 校园活动/新闻/餐厅/图书馆开放时间（端口 5006）
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

conf = Config()

# 初始化LLM
llm = ChatOpenAI(
    model=conf.model_name,
    base_url=conf.base_url,
    api_key=conf.api_key,
    temperature=0.1
)


# 数据表 schema
table_schema_string = """  # 定义校园信息表的SQL schema字符串，用于Prompt上下文
-- 校园活动表
CREATE TABLE campus_events (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    event_name VARCHAR(200) NOT NULL COMMENT '活动名称',
    organizer VARCHAR(100) NOT NULL COMMENT '主办方',
    venue VARCHAR(100) NOT NULL COMMENT '活动场地',
    start_time DATETIME NOT NULL COMMENT '开始时间',
    end_time DATETIME NOT NULL COMMENT '结束时间',
    category VARCHAR(30) NOT NULL COMMENT '活动类别',
    total_capacity INT NOT NULL DEFAULT 100 COMMENT '总容量',
    registered INT NOT NULL DEFAULT 0 COMMENT '已报名人数',
    description TEXT COMMENT '活动简介',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_event (start_time, event_name, venue)
) COMMENT='校园活动信息表';

-- 校园新闻表
CREATE TABLE campus_news (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    title VARCHAR(200) NOT NULL COMMENT '新闻标题',
    source VARCHAR(100) NOT NULL DEFAULT 'CUHK CPR' COMMENT '来源',
    category VARCHAR(30) DEFAULT 'General' COMMENT '新闻类别',
    publish_date DATETIME NOT NULL COMMENT '发布日期',
    summary TEXT COMMENT '新闻摘要',
    url VARCHAR(500) COMMENT '原文链接',
    image_url VARCHAR(500) COMMENT '封面图URL',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_news (publish_date, title)
) COMMENT='校园新闻表';

-- 校园餐厅表
CREATE TABLE canteen (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    name VARCHAR(80) NOT NULL COMMENT '餐厅名称',
    location VARCHAR(100) NOT NULL COMMENT '所在位置/地址',
    opening_hours VARCHAR(300) COMMENT '营业时间',
    phone VARCHAR(50) COMMENT '联系电话',
    category VARCHAR(30) DEFAULT 'Canteen' COMMENT '类别（Canteen/Cafe/Restaurant/Snack Bar）',
    status VARCHAR(20) DEFAULT 'Open' COMMENT '营业状态（Open/Closed）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_canteen (name, location)
) COMMENT='校园餐厅信息表';

-- 图书馆开放时间表
CREATE TABLE library_hours (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    library_name VARCHAR(100) NOT NULL COMMENT '图书馆名称',
    area VARCHAR(100) DEFAULT 'Main' COMMENT '区域（如 Main/ Learning Garden/ Staffed services）',
    day_of_week VARCHAR(10) NOT NULL COMMENT '星期几（Mon/Tue/Wed/Thu/Fri/Sat/Sun）',
    date DATE COMMENT '具体日期',
    open_time VARCHAR(10) COMMENT '开门时间（如 09:00, 24hrs）',
    close_time VARCHAR(10) COMMENT '关门时间',
    is_closed TINYINT DEFAULT 0 COMMENT '是否闭馆',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_lib_hours (library_name, area, day_of_week, date)
) COMMENT='图书馆开放时间表';
"""

# 生成SQL的提示词
sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是一个专业的CUHK校园信息SQL生成器，需要从对话历史（含用户的问题）中提取用户的意图以及关键信息，然后基于 campus_events、campus_news、canteen、library_hours 表生成SELECT语句。
根据对话历史：
1. 提取用户的意图，意图有4种（campus_event: 校园活动, campus_news: 校园新闻, canteen: 餐厅, library_hours: 图书馆开放时间），输出：{{"type": "campus_event/campus_news/canteen/library_hours"}}；如果无法识别意图，或者意图不在这4种内，则模仿最后1个示例回复即可。
2. 根据用户的意图，生成对应表的 SELECT 语句，仅查询指定字段：
- campus_events: id, event_name, organizer, venue, start_time, end_time, category, total_capacity, registered, description
- campus_news: id, title, source, category, publish_date, summary, url
- canteen: id, name, location, opening_hours, phone, category, status
- library_hours: id, library_name, area, day_of_week, date, open_time, close_time, is_closed
3. 重要：始终生成默认SQL，只有用户意图完全无法识别（如"你好""谢谢"）时才退回 input_required。即使模糊查询也要生成SQL。
4. 按要求输出两行数据即可，不需要输出其他内容。

中文地名 → 英文关键词映射（用于 SQL LIKE）：
  崇基/崇基学院=Chung Chi, 新亚/新亚书院=New Asia, 联合/联合书院=United College,
  善衡=S.H. Ho, 逸夫/逸夫书院=Shaw, 伍宜孙=Wu Yee Sun, 晨兴=Morningside,
  和声=Lee Woo Sing, 敬文=C.W. Chu, 大学图书馆=University Library,
  法律图书馆=Law Library, 医学图书馆=Medical Library, 建筑学图书馆=Architecture Library

默认查询策略（无明确条件时直接用）：
- campus_event: ORDER BY start_time DESC LIMIT 10（最近的10个活动）
- campus_news:  ORDER BY publish_date DESC LIMIT 10（最近的10条新闻）
- canteen:      WHERE status = 'Open'（全部营业中餐厅）
- library_hours:根据当前日期计算星期几（周一=Mon,...周日=Sun），用 day_of_week 过滤；无条件则查全部

示例：
- 对话: user: 最近有什么校园活动 讲座
输出:
{{"type": "campus_event"}}
SELECT id, event_name, organizer, venue, start_time, end_time, category, total_capacity, registered, description FROM campus_events WHERE category = 'Talk' AND start_time >= '2026-08-10'

- 对话: user: 最近有什么活动
输出:
{{"type": "campus_event"}}
SELECT id, event_name, organizer, venue, start_time, end_time, category, total_capacity, registered, description FROM campus_events ORDER BY start_time DESC LIMIT 10

- 对话: user: 最近有什么新闻
输出:
{{"type": "campus_news"}}
SELECT id, title, source, category, publish_date, summary, url FROM campus_news ORDER BY publish_date DESC LIMIT 10

- 对话: user: 有什么餐厅
输出:
{{"type": "canteen"}}
SELECT id, name, location, opening_hours, phone, category, status FROM canteen WHERE status = 'Open'

- 对话: user: 崇基学院有什么餐厅
输出:
{{"type": "canteen"}}
SELECT id, name, location, opening_hours, phone, category, status FROM canteen WHERE (location LIKE '%Chung Chi%' OR name LIKE '%Chung Chi%') AND status = 'Open'

- 对话: user: 大学图书馆今天开门吗（当前日期 2026-08-10 是 Monday → Mon）
输出:
{{"type": "library_hours"}}
SELECT id, library_name, area, day_of_week, date, open_time, close_time, is_closed FROM library_hours WHERE library_name LIKE '%University Library%' AND day_of_week = 'Mon' AND is_closed = 0

- 对话: user: 大学图书馆几点开门
输出:
{{"type": "library_hours"}}
SELECT id, library_name, area, day_of_week, date, open_time, close_time, is_closed FROM library_hours WHERE library_name LIKE '%University Library%'

- 对话: user: 你好
输出:
{{"status": "input_required", "message": "请提供校园信息查询类型（校园活动/新闻/餐厅/图书馆开放时间）和必要信息。"}}

表结构：{table_schema_string}
对话历史: {conversation}
当前日期: {current_date} (Asia/Shanghai)
    """
)


# 定义查询函数
async def get_facility_info(sql):
    try:
        # 启动 MCP server，通过streamable建立连接
        async with streamable_http_client("http://127.0.0.1:8001/mcp") as (read, write):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                try:
                    await session.initialize()
                    # 工具调用
                    result = await session.call_tool("query_facilities", {"sql": sql})
                    result_data = json.loads(result) if isinstance(result, str) else result
                    logger.info(f"设施查询结果：{result_data}")
                    return result_data.content[0].text
                except Exception as e:
                    logger.error(f"设施 MCP 查询出错：{str(e)}")
                    return {"status": "error", "message": f"设施 MCP 查询出错：{str(e)}"}
    except Exception as e:
        logger.error(f"连接或会话初始化时发生错误: {e}")
        return {"status": "error", "message": "连接或会话初始化时发生错误"}

# Agent 卡片定义
agent_card = AgentCard(
    name="FacilityQueryAssistant",
    description="基于 LangChain 提供CUHK校园信息查询服务的助手",
    url="http://localhost:5006",
    version="2.0.0",
    capabilities={"streaming": True, "memory": True},
    skills=[
        AgentSkill(
            name="execute campus query",
            description="根据客户端提供的输入执行校园信息查询，返回数据库结果，支持自然语言输入",
            examples=["最近有什么讲座", "校园新闻", "崇基学院餐厅", "大学图书馆开放时间"]
        )
    ]
)


# 设施查询服务器类
class FacilityQueryServer(A2AServer):
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
            lines = output.split('\n')
            type_line = lines[0].strip()
            if type_line.startswith('```json'):
                type_line = lines[1].strip()
                sql_lines = lines[3:-1] if lines[-1].strip() == '```' else lines[3:]
            else:
                sql_lines = lines[1:] if len(lines) > 1 else []

            # 提取 type 和 SQL
            if type_line.startswith('{"type":'):
                query_type = json.loads(type_line)["type"]
                sql_query = ' '.join([line.strip() for line in sql_lines if line.strip() and not line.startswith('```')])
                logger.info(f"分类类型: {query_type}, 生成的 SQL: {sql_query}")
                return {"status": "sql", "type": query_type, "sql": sql_query}
            elif type_line.startswith('{"status": "input_required"'):
                return json.loads(type_line)
            else:
                logger.error(f"无效的 LLM 输出格式: {output}")
                return {"status": "input_required", "message": "无法解析查询类型或SQL，请提供更明确的信息。"}
        except Exception as e:
            logger.error(f"SQL 生成失败: {str(e)}")
            return {"status": "input_required", "message": "查询无效，请提供查询校园信息的相关信息。"}

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
            query_type = gen_result["type"]
            logger.info(f"执行 SQL 查询: {sql_query} (类型: {query_type})")

            # 3 调用MCP
            facility_result = asyncio.run(get_facility_info(sql_query))

            # 4 格式化结果
            response = json.loads(facility_result) if isinstance(facility_result, str) else facility_result
            logger.info(f"MCP 返回: {response}")
            if response.get("status") == "success":
                data = response.get("data", [])
                response_text = ""
                for d in data:
                    if query_type == "campus_event":
                        response_text += f"{d['start_time']} | {d['event_name']} | {d['organizer']} | {d['venue']} | {d['category']} | 已报名:{d['registered']}/{d['total_capacity']}\n"
                    elif query_type == "campus_news":
                        response_text += f"[{d['publish_date']}] {d['title']} | 来源:{d['source']} | 类别:{d['category']}\n摘要: {d.get('summary', '')}\n链接: {d.get('url', '')}\n\n"
                    elif query_type == "canteen":
                        response_text += f"{d['name']} | {d['location']} | {d['category']} | 营业时间: {d.get('opening_hours', '请参考店内')} | 状态: {d['status']}\n"
                    elif query_type == "library_hours":
                        if d.get('is_closed'):
                            response_text += f"{d['library_name']} {d['area']} | {d['day_of_week']} ({d.get('date','')}) | 闭馆\n"
                        elif d.get('open_time') == '24hrs':
                            response_text += f"{d['library_name']} {d['area']} | {d['day_of_week']} ({d.get('date','')}) | 24小时开放\n"
                        else:
                            response_text += f"{d['library_name']} {d['area']} | {d['day_of_week']} ({d.get('date','')}) | {d.get('open_time','')} - {d.get('close_time','')}\n"
                if not response_text:
                    response_text = "无结果。如需其他条件，请补充。"

                task.artifacts = [{"parts": [{"type": "text", "text": response_text}]}]
                task.status = TaskStatus(state=TaskState.COMPLETED)
            elif response.get("status") == "no_data":
                response_text = response.get("message", "请提供更详细的查询条件。")
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
    facility_server = FacilityQueryServer()
    print("\n=== 服务器信息 ===")
    print(f"名称: {facility_server.agent_card.name}")
    print(f"描述: {facility_server.agent_card.description}")
    print("\n技能:")
    for skill in facility_server.agent_card.skills:
        print(f"- {skill.name}: {skill.description}")
    run_server(facility_server, host="127.0.0.1", port=5006)
