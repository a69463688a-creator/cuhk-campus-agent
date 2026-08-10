# SmartCampus — CUHK校园生活智能助手

基于 **A2A（Agent-to-Agent）协议** 与 **MCP（Model Context Protocol）** 的多智能体校园服务系统，专为香港中文大学（CUHK）学生设计，提供课程查询、自习室/图书馆座位检索、校园活动发现及在线预约等一站式服务。

## 项目概览

```
用户输入（自然语言）
    │
    ▼
┌──────────────────────────────────────┐
│   Frontend: Streamlit Web / CLI      │
│   • 意图识别（LLM: DeepSeek-v4-flash） │
│   • 多意图并行路由                     │
│   • 结果总结与推荐                     │
└──────────────────────────────────────┘
    │ A2A Protocol
    ▼
┌──────────────────────────────────────┐
│       A2A Agent 层（3 个 Agent）       │
│                                      │
│  CourseQueryAssistant  :5005         │
│  FacilityQueryAssistant :5006        │
│  BookingAssistant      :5007         │
└──────────────────────────────────────┘
    │ MCP Protocol (streamable-http)
    ▼
┌──────────────────────────────────────┐
│       MCP Server 层（3 个 Server）     │
│                                      │
│  Course MCP   :8002  → course_info   │
│  Facility MCP :8001  → study_rooms   │
│                     → library_seats  │
│                     → campus_events  │
│  Booking MCP  :8003  → 预约/报名操作   │
└──────────────────────────────────────┘
    │ MySQL Connector
    ▼
┌──────────────────────────────────────┐
│   MySQL 8.0  (cuhk_campus)           │
│   4 张业务表 + 模拟种子数据              │
└──────────────────────────────────────┘
```

## 技术栈

| 层级 | 技术 |
|------|------|
| **LLM** | DeepSeek-v4-flash（通过 LangChain `ChatOpenAI` 兼容接口） |
| **Agent 协议** | `python-a2a` — Google A2A 协议的 Python 实现 |
| **工具协议** | `mcp` + `FastMCP` — Anthropic MCP，streamable-http 传输 |
| **前端** | Streamlit（Web UI）+ 命令行交互（CLI） |
| **数据库** | MySQL 8.0.12，utf8mb4 |
| **Python** | 3.12+，conda 环境 |

## 项目结构

```
SmartCampus/
├── app.py                     # Streamlit Web 前端（主界面 + Agent Card 面板）
├── main.py                    # CLI 命令行交互入口
├── config.py                  # 全局配置（LLM、MySQL、意图→Agent 映射）
├── main_prompts.py            # LLM Prompt 模板（意图识别/总结/推荐）
├── create_logger.py           # 日志工具
├── requirements.txt           # Python 依赖
│
├── mcp_server/                # MCP 服务器层
│   ├── mcp_weather_server.py  # Course MCP（端口 8002）— 课程查询工具
│   ├── mcp_ticket_server.py   # Facility MCP（端口 8001）— 设施查询工具
│   └── mcp_order_server.py    # Booking MCP（端口 8003）— 预约/报名工具
│
├── a2a_server/                # A2A Agent 层
│   ├── weather_server.py      # CourseQueryAssistant（端口 5005）
│   ├── ticket_server.py       # FacilityQueryAssistant（端口 5006）
│   └── order_server.py        # BookingAssistant（端口 5007）
│
├── query_data/                # 数据访问层
│   └── query1.py              # FacilityService — MySQL 连接与查询封装
│
├── sql/                       # 数据库脚本
│   ├── sql_data.sql           # DDL（4张表：课程/自习室/图书馆/活动）
│   ├── insert.sql             # 课程种子数据（14门CUHK CS真实课程）
│   └── insert2.sql            # 设施种子数据（自习室/图书馆/活动）
│
├── utils/                     # 工具
│   ├── format.py              # JSON 序列化编解码器
│   └── spider_weather.py      # CUHK公开页面数据采集器
│
└── test/                      # 测试脚本
    ├── test_weather_mcp_server.py   # Course MCP 连通性测试
    ├── test_weather_agent_server.py # CourseQueryAssistant 测试
    ├── test_order_agent_server.py   # BookingAssistant 测试
    └── weather_api_test.py          # CUHK 公开页面连通性测试
```

## 核心架构详解

### 1. 意图识别与路由

用户输入经 LLM 进行多意图识别，支持的意图包括：

| 意图 | 描述 | 路由目标 |
|------|------|---------|
| `course` | 课程查询（上课时间/地点/教师） | CourseQueryAssistant |
| `study_room` | 自习室查询 | FacilityQueryAssistant |
| `library_seat` | 图书馆座位查询 | FacilityQueryAssistant |
| `campus_event` | 校园活动查询 | FacilityQueryAssistant |
| `booking` | 自习室预约/座位预约/活动报名 | BookingAssistant |
| `recommend` | 课程/活动推荐 | LLM 直接生成 |

系统支持单次查询中包含多个意图（如"查看CSCI2100课程信息，并查一下今天大学图书馆的座位"），自动并行路由到对应 Agent 并聚合结果。

### 2. A2A Agent 工作机制

每个 Agent 是一个独立的 Python 服务，具备以下能力：

- **CourseQueryAssistant (5005)**：接收课程查询 → 调用 Course MCP（8002）获取 course_info 数据 → LLM 将 SQL 结果总结为自然语言
- **FacilityQueryAssistant (5006)**：接收设施查询 → 调用 Facility MCP（8001）获取 study_rooms/library_seats/campus_events 数据 → LLM 总结
- **BookingAssistant (5007)**：接收预约请求 → 先向 FacilityQueryAssistant 查询可用性 → 再调用 Booking MCP（8003）执行预约/报名

Agent 对外暴露 **AgentCard**（技能、描述、地址），由 `python-a2a` 框架管理生命周期。

### 3. MCP Server 设计

MCP 服务器通过 `FastMCP` 框架暴露工具：

- **Course MCP (8002)**：`query_courses(sql)` — 直接执行 SQL 查询 `course_info` 表
- **Facility MCP (8001)**：`query_facilities(sql)` — 支持跨 `study_rooms`、`library_seats`、`campus_events` 三表查询
- **Booking MCP (8003)**：`book_study_room()`、`book_library_seat()`、`register_event()` — 预约操作（当前为模拟模式）

所有 MCP 服务器均具备 MySQL 自动重连机制，处理长时间空闲导致的连接断开问题。

### 4. 数据库设计

数据库 `cuhk_campus` 包含 4 张核心表：

- **course_info**：课程代码、名称、院系、教师、上课时间/地点、学分、容量、类别、简介
- **study_rooms**：教学楼、教室编号、日期、时间段、容量、可用座位、设备（投影仪/空调）
- **library_seats**：图书馆名称、楼层、区域、日期、时间段、总座位、可用座位、电源/静音区标识
- **campus_events**：活动名称、主办方、场地、时间、类别、容量、已报名数、简介

种子数据使用真实的 CUHK 教学楼（YIA、LSK、SC、MMW、HSH）、图书馆（University Library、Chung Chi、New Asia、United College、Law Library）及课程信息（CSCI2100、CSCI3100、CSCI3170、CSCI4180、CSCI4430 等）。

## 快速启动

### 环境要求

- Python 3.12+
- MySQL 8.0+
- Conda（推荐）

### 1. 创建环境并安装依赖

```bash
conda create -n lang_env python=3.12
conda activate lang_env
pip install -r requirements.txt
```

### 2. 初始化数据库

```bash
mysql -u root -p < sql/sql_data.sql
mysql -u root -p -D cuhk_campus < sql/insert.sql
mysql -u root -p -D cuhk_campus < sql/insert2.sql
```

### 3. 配置 API Key

编辑 `config.py`，设置 DeepSeek API Key：
```python
self.api_key = 'your-deepseek-api-key'
```

### 4. 启动服务（共 6 个后台进程 + 1 个前端）

```bash
# 设置项目路径
export PYTHONPATH="E:/Workspace/agent_project/SmartCampus"

# 1) 启动 3 个 MCP Server
nohup python mcp_server/mcp_weather_server.py > logs/mcp_course.log 2>&1 &   # 8002
nohup python mcp_server/mcp_ticket_server.py > logs/mcp_facility.log 2>&1 &  # 8001
nohup python mcp_server/mcp_order_server.py > logs/mcp_booking.log 2>&1 &    # 8003

# 2) 启动 3 个 A2A Agent
nohup python a2a_server/weather_server.py > logs/a2a_course.log 2>&1 &       # 5005
nohup python a2a_server/ticket_server.py > logs/a2a_facility.log 2>&1 &      # 5006
nohup python a2a_server/order_server.py > logs/a2a_booking.log 2>&1 &        # 5007

# 3) 启动 Streamlit 前端
streamlit run app.py   # http://localhost:8501

# 或使用 CLI 模式
python main.py
```

### 5. 验证服务

```bash
# 验证 MCP Server
curl -s http://127.0.0.1:8002/mcp -X POST \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

## 服务端口一览

| 服务 | 端口 | 协议 |
|------|------|------|
| Streamlit Web UI | 8501 | HTTP |
| CourseQueryAssistant (A2A) | 5005 | A2A/JSON |
| FacilityQueryAssistant (A2A) | 5006 | A2A/JSON |
| BookingAssistant (A2A) | 5007 | A2A/JSON |
| Course MCP | 8002 | MCP (streamable-http) |
| Facility MCP | 8001 | MCP (streamable-http) |
| Booking MCP | 8003 | MCP (streamable-http) |

## 许可

本项目为个人学术项目，仅供学习与展示用途。
