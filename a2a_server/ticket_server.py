#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: facility_server.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/6
描述: 校园设施查询 A2A Agent 服务器 —— 自习室/图书馆座位/校园活动（端口 5006）
"""
import json
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from python_a2a import A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from datetime import datetime
import pytz

from config import Config
from create_logger import logger

conf = Config()

# 初始化LLM
llm = ChatOpenAI(
    model=conf.model_name,
    base_url=conf.base_url,
    api_key=conf.api_key,
    temperature=0.1
)


# 数据表 schema
table_schema_string = """  # 定义校园设施表的SQL schema字符串，用于Prompt上下文
CREATE TABLE study_rooms (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    building VARCHAR(80) NOT NULL COMMENT '教学楼名称',
    room_number VARCHAR(20) NOT NULL COMMENT '教室编号',
    room_date DATE NOT NULL COMMENT '开放日期',
    start_time TIME NOT NULL COMMENT '开放开始时间',
    end_time TIME NOT NULL COMMENT '开放结束时间',
    capacity INT NOT NULL COMMENT '总座位数',
    available_seats INT NOT NULL COMMENT '剩余可用座位',
    has_projector TINYINT DEFAULT 0 COMMENT '是否有投影仪',
    has_ac TINYINT DEFAULT 1 COMMENT '是否有空调',
    status VARCHAR(20) DEFAULT 'available' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_room (building, room_number, room_date, start_time)
) COMMENT='自习室信息表';

-- 图书馆座位表
CREATE TABLE library_seats (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    library_name VARCHAR(80) NOT NULL COMMENT '图书馆名称',
    floor INT NOT NULL COMMENT '楼层',
    zone VARCHAR(40) NOT NULL COMMENT '区域',
    seat_date DATE NOT NULL COMMENT '日期',
    time_slot VARCHAR(20) NOT NULL COMMENT '时间段',
    total_seats INT NOT NULL COMMENT '该区域总座位数',
    available_seats INT NOT NULL COMMENT '剩余可用座位',
    has_power TINYINT DEFAULT 1 COMMENT '是否有电源插座',
    is_quiet_zone TINYINT DEFAULT 0 COMMENT '是否静音区',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_seat (library_name, floor, zone, seat_date, time_slot)
) COMMENT='图书馆座位信息表';

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
"""

# 生成SQL的提示词
sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是一个专业的CUHK校园设施SQL生成器，需要从对话历史（含用户的问题）中提取用户的意图以及关键信息，然后基于study_rooms、library_seats、campus_events表生成SELECT语句。
根据对话历史：
1. 提取用户的意图，意图有3种（study_room: 自习室, library_seat: 图书馆座位, campus_event: 校园活动），输出：{{"type": "study_room/library_seat/campus_event"}}；如果无法识别意图，或者意图不在这3种内，则模仿最后1个示例回复即可。
2. 根据用户的意图，生成对应表的 SELECT 语句，仅查询指定字段：
- study_rooms: id, building, room_number, room_date, start_time, end_time, capacity, available_seats, has_projector, has_ac, status
- library_seats: id, library_name, floor, zone, seat_date, time_slot, total_seats, available_seats, has_power, is_quiet_zone
- campus_events: id, event_name, organizer, venue, start_time, end_time, category, total_capacity, registered, description
3. 如果用户在查询设施信息时，缺少必要信息，则输出：{{"status": "input_required", "message": "请提供设施类型（如自习室、图书馆座位、校园活动）和必要信息（如教学楼、日期等）。"}} ，如示例所示；如果对话历史中信息齐全，则输出纯SQL即可。
其中，每种意图必要的信息有：
- study_room: 【building (教学楼), room_date (日期)】
- library_seat: library_name (图书馆名), seat_date (日期)。
- campus_event: category (类别), start_time (日期范围)。
4. 按要求输出两行数据或一行数据即可，不需要输出其他内容。


示例：
- 对话: user: YIA教学楼 2026-08-10 自习室
输出:
{{"type": "study_room"}}
SELECT id, building, room_number, room_date, start_time, end_time, capacity, available_seats, has_projector, has_ac, status FROM study_rooms WHERE building = 'Yasumoto International Academic Park' AND room_date = '2026-08-10'

- 对话: user: University Library 2026-08-10 座位
输出:
{{"type": "library_seat"}}
SELECT id, library_name, floor, zone, seat_date, time_slot, total_seats, available_seats, has_power, is_quiet_zone FROM library_seats WHERE library_name = 'University Library' AND seat_date = '2026-08-10'

- 对话: user: 最近有什么校园活动 竞赛
输出:
{{"type": "campus_event"}}
SELECT id, event_name, organizer, venue, start_time, end_time, category, total_capacity, registered, description FROM campus_events WHERE category = 'Competition' AND start_time >= '2026-08-10'

- 对话: user: 自习室
输出:
{{"status": "input_required", "message": "请提供教学楼名称和日期，例如 'YIA教学楼 2026-08-10'。"}}

- 对话: user: 你好
输出:
{{"status": "input_required", "message": "请提供校园设施查询类型（自习室/图书馆座位/校园活动）和必要信息。"}}

表结构：{table_schema_string}
对话历史: {conversation}
当前日期: {current_date} (Asia/Shanghai)
    """
)


# 定义查询函数
async def get_facility_info(sql):
    try:
        # 启动 MCP server，通过streamable建立连接
        async with streamablehttp_client("http://127.0.0.1:8001/mcp") as (read, write, _):
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
    description="基于 LangChain 提供CUHK校园设施查询服务的助手",
    url="http://localhost:5006",
    version="1.0.4",
    capabilities={"streaming": True, "memory": True},
    skills=[
        AgentSkill(
            name="execute facility query",
            description="根据客户端提供的输入执行校园设施查询，返回数据库结果，支持自然语言输入",
            examples=["YIA教学楼 2026-08-10 自习室", "University Library 明天 座位",
                      "最近有什么CS相关的校园活动"]
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
            current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')  # 获取当前日期，格式化为字符串
            output = chain.invoke({"conversation": conversation, "current_date": current_date, "table_schema_string": self.schema}).content.strip()
            logger.info(f"原始 LLM 输出: {output}")

            # 处理结果，返回字典
            lines = output.split('\n')
            type_line = lines[0].strip()
            if type_line.startswith('```json'):  # 检查是否以```json开头
                type_line = lines[1].strip()  # 取下一行为类型行
                sql_lines = lines[3:-1] if lines[-1].strip() == '```' else lines[3:]  # 提取SQL行，跳过代码块标记
            else:
                sql_lines = lines[1:] if len(lines) > 1 else []  # 取剩余行为SQL行

            # 提取 type 和 SQL
            if type_line.startswith('{"type":'):  # 如果以{"type":开头
                query_type = json.loads(type_line)["type"]  # 解析并提取类型
                sql_query = ' '.join([line.strip() for line in sql_lines if line.strip() and not line.startswith('```')])  # 连接SQL行，过滤空行和代码块
                logger.info(f"分类类型: {query_type}, 生成的 SQL: {sql_query}")
                return {"status": "sql", "type": query_type, "sql": sql_query}  # 返回SQL状态字典，包括类型
            elif type_line.startswith('{"status": "input_required"'):  # 检查是否为追问JSON
                return json.loads(type_line)
            else:  # 无效格式
                logger.error(f"无效的 LLM 输出格式: {output}")
                return {"status": "input_required", "message": "无法解析查询类型或SQL，请提供更明确的信息。"}  # 返回默认追问
        except Exception as e:
            logger.error(f"SQL 生成失败: {str(e)}")
            return {"status": "input_required", "message": "查询无效，请提供查询校园设施的相关信息。"}  # 返回追问JSON

    # 处理任务：提取输入，生成SQL，调用MCP，格式化结果
    def handle_task(self, task):
        # 1 提取输入
        content = (task.message or {}).get("content", {})  # 从消息中获取内容
        # 提取conversation，即客户端发起的任务中的query语句
        conversation = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"对话历史及用户问题: {conversation}")

        try:
            # 2 基于用户问题生成SQL查询
            gen_result = self.generate_sql_query(conversation)
            # 检查是否需要追问，如果是则添加追问消息后返回任务
            if gen_result["status"] == "input_required":
                task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                         message={"role": "agent", "content": {"text": gen_result["message"]}})
                return task

            # 否则则提取SQL查询，并进行MCP调用
            sql_query = gen_result["sql"]
            query_type = gen_result["type"]
            logger.info(f"执行 SQL 查询: {sql_query} (类型: {query_type})")

            # 3 调用MCP
            facility_result = asyncio.run(get_facility_info(sql_query))

            # 4 格式化结果
            response = json.loads(facility_result) if isinstance(facility_result, str) else facility_result
            logger.info(f"MCP 返回: {response}")
            # 检查响应状态
            if response.get("status") == "success":
                data = response.get("data", [])  # 提取数据列表
                response_text = ""  # 初始化响应文本
                for d in data:  # 遍历每个数据项
                    if query_type == "study_room":  # 自习室类型
                        response_text += f"{d['building']} {d['room_number']} | {d['room_date']} {d['start_time']}-{d['end_time']} | 可用:{d['available_seats']}/{d['capacity']} | 投影仪:{'有' if d['has_projector'] else '无'} | 空调:{'有' if d['has_ac'] else '无'} | 状态:{d['status']}\n"
                    elif query_type == "library_seat":  # 图书馆座位类型
                        response_text += f"{d['library_name']} F{d['floor']} {d['zone']} | {d['seat_date']} {d['time_slot']} | 可用:{d['available_seats']}/{d['total_seats']} | 电源:{'有' if d['has_power'] else '无'} | {'静音区' if d['is_quiet_zone'] else '非静音区'}\n"
                    elif query_type == "campus_event":  # 校园活动类型
                        response_text += f"{d['start_time']} | {d['event_name']} | {d['organizer']} | {d['venue']} | {d['category']} | 已报名:{d['registered']}/{d['total_capacity']}\n"
                if not response_text:  # 检查文本是否为空
                    response_text = "无结果。如需其他条件，请补充。"

                # 设置任务产物为文本部分，并设置任务状态为完成
                task.artifacts = [{"parts": [{"type": "text", "text": response_text}]}]
                task.status = TaskStatus(state=TaskState.COMPLETED)
            elif response.get("status") == "no_data":
                response_text = response.get("message", "请提供更详细的查询条件。")

                # 设置任务状态为输入所需，添加追问消息
                task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                         message={"role": "agent", "content": {"text": response_text}})
            else:
                response_text = response.get("message", "查询失败，请重试或提供更多细节。")

                # 设置任务状态为失败，添加错误信息
                task.status = TaskStatus(state=TaskState.FAILED,
                                         message={"role": "agent", "content": {"text": response_text}})
            return task
        except Exception as e:  # 捕获异常
            logger.error(f"查询失败: {str(e)}")

            # 设置任务状态为失败，添加错误信息
            task.status = TaskStatus(state=TaskState.FAILED,
                                     message={"role": "agent",
                                              "content": {"text": f"查询失败: {str(e)} 请重试或提供更多细节。"}})
            return task

if __name__ == "__main__":
    # 创建并运行服务器
    # 实例化设施查询服务器
    facility_server = FacilityQueryServer()
    # 打印服务器信息
    print("\n=== 服务器信息 ===")
    print(f"名称: {facility_server.agent_card.name}")
    print(f"描述: {facility_server.agent_card.description}")
    print("\n技能:")
    for skill in facility_server.agent_card.skills:
        print(f"- {skill.name}: {skill.description}")
    # 运行服务器
    run_server(facility_server, host="127.0.0.1", port=5006)
