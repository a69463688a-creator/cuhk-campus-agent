# SmartCampus — CUHK 校园生活智能助手

基于 **A2A（Agent-to-Agent）协议** 与 **MCP（Model Context Protocol v2.0）** 的多智能体校园服务系统，专为香港中文大学（CUHK）学生设计，提供课程查询、校园活动、餐厅、图书馆开放时间和新闻等一站式服务。

## 系统架构

```
用户输入（自然语言 / Web UI）
    │
    ▼
┌──────────────────────────────────────────┐
│  app/server.py  —  FastAPI Web 网关 (:8100) │
│  • 意图识别（LLM: DeepSeek-v4-flash）        │
│  • 天气查询（Open-Meteo 直连）                │
│  • 结果总结与推荐                              │
└──────────────────────────────────────────┘
    │ A2A Protocol (python-a2a v0.5.10)
    ▼
┌──────────────────────────────────────────┐
│         A2A Agent 层（2 个 Agent）          │
│                                          │
│  CourseQueryAssistant   :5005            │
│  └─ 课程查询（课程代码/教师/时间/地点）        │
│                                          │
│  FacilityQueryAssistant  :5006           │
│  └─ 活动/新闻/餐厅/图书馆 4 合 1            │
└──────────────────────────────────────────┘
    │ MCP Protocol (streamable-http)
    ▼
┌──────────────────────────────────────────┐
│        MCP Server 层（2 个 Server）         │
│                                          │
│  Course MCP   :8002  → course_info       │
│  Facility MCP :8001  → campus_events      │
│                      → campus_news       │
│                      → canteen           │
│                      → library_hours     │
└──────────────────────────────────────────┘
    │ mysql-connector-python
    ▼
┌──────────────────────────────────────────┐
│     MySQL 8.0  (cuhk_campus / 5 张表)      │
└──────────────────────────────────────────┘
```

## 技术栈

| 层级 | 技术 |
|------|------|
| **LLM** | DeepSeek-v4-flash（LangChain `ChatOpenAI` 兼容接口，tenacity 指数退避重试） |
| **Agent 协议** | `python-a2a` v0.5.10 — Google A2A 协议的 Python 实现 |
| **工具协议** | `mcp` v2.0.0 — `MCPServer` + `streamable-http` 传输 |
| **Web 框架** | FastAPI + Uvicorn + WebSocket 流式响应 |
| **数据库** | MySQL 8.0，utf8mb4，5 张业务表 |
| **爬虫** | requests + BeautifulSoup4 + schedule 定时调度 |
| **部署** | Docker Compose（MySQL + App 双容器） |

## 项目结构

```
SmartCampus/
├── app/                         # 应用核心层
│   ├── server.py                # FastAPI Web 网关（:8100）
│   ├── cli.py                   # CLI 命令行交互入口
│   ├── config.py                # 全局配置（.env 驱动）
│   ├── prompts.py               # LLM Prompt 模板
│   └── logging.py               # 日志系统
│
├── agents/                      # A2A Agent 层
│   ├── course_agent.py          # 课程查询 Agent（:5005）
│   └── facility_agent.py        # 设施查询 Agent（:5006）
│
├── mcp_servers/                 # MCP 工具服务器层
│   ├── course_server.py         # 课程 MCP（:8002）
│   └── facility_server.py       # 设施 MCP（:8001）
│
├── data/                        # 数据访问层
│   ├── database.py              # FacilityService — MySQL 封装
│   └── format.py                # JSON 序列化（DateEncoder）
│
├── spiders/                     # 数据采集爬虫
│   ├── course.py                # 课程数据（GitHub Raw 同步）
│   ├── events.py                # 校园活动（CPR AJAX API）
│   ├── news.py                  # 校园新闻（CPR 新闻中心）
│   ├── canteen.py               # 餐厅信息（CUHK 住宿页面）
│   └── library.py               # 图书馆开放时间（基线数据）
│
├── sql/
│   └── docker_init.sql          # DDL + 种子数据（Docker 自动导入）
│
├── static/                      # Web 前端静态文件
├── run_web.py                   # Web 服务启动入口
├── run_cli.py                   # CLI 启动入口
├── run_spiders.py               # 爬虫统一入口（runall）
├── Dockerfile                   # Docker 镜像构建
├── docker-compose.yml           # Docker 编排
├── docker-entrypoint.py         # 容器启动编排器
├── requirements.txt             # Python 依赖
├── .env.example                 # 环境变量模板
├── CHANGELOG.md                 # 更新日志
└── README.md
```

## 数据库设计

数据库 `cuhk_campus` 包含 5 张表：

| 表名 | 用途 | 数据来源 |
|------|------|---------|
| `course_info` | 课程代码、名称、教师、时间、地点、学分、容量 | 爬虫（GitHub 课程规划器） |
| `campus_events` | 活动名称、主办方、场地、时间、类别、报名 | 爬虫（CPR AJAX API） |
| `campus_news` | 新闻标题、来源、类别、发布日期、摘要、URL | 爬虫（CPR 新闻中心） |
| `canteen` | 餐厅名称、位置、营业时间、电话、类别、状态 | 爬虫（CUHK 住宿页面） |
| `library_hours` | 图书馆名称、区域、星期、日期、开放/关闭时间 | 内置基线数据（8 个图书馆） |

## 意图路由

| 意图 | 描述 | 路由目标 |
|------|------|---------|
| `course` | 课程查询（代码/教师/时间/地点） | CourseQueryAssistant |
| `campus_event` | 校园活动查询 | FacilityQueryAssistant |
| `campus_news` | 校园新闻查询 | FacilityQueryAssistant |
| `canteen` | 餐厅信息查询 | FacilityQueryAssistant |
| `library_hours` | 图书馆开放时间查询 | FacilityQueryAssistant |
| `weather` | 天气查询 | 直连 Open-Meteo API |

## 服务端口

| 服务 | 端口 | 协议 |
|------|------|------|
| Web 前端 | 8100 | HTTP (FastAPI) |
| CourseQueryAssistant | 5005 | A2A/JSON |
| FacilityQueryAssistant | 5006 | A2A/JSON |
| Course MCP | 8002 | MCP (streamable-http) |
| Facility MCP | 8001 | MCP (streamable-http) |
| MySQL | 3308→3306 | MySQL Protocol |

> 端口 8100/3308 避免与 [PaperRag](https://github.com/a69463688a-creator/) 项目（8080/3307）冲突。

---

## 快速启动

### Docker（推荐）

```bash
# 1. 创建 .env 文件
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY 和 DB_PASSWORD

# 2. 一键启动
docker compose up -d

# 3. 初始化爬虫数据（首次）
docker exec -e PYTHONPATH=/app smartcampus-app python spiders/library.py --force --once

# 4. 访问
# Web UI:  http://localhost:8100
# API 文档: http://localhost:8100/docs
# 健康检查: http://localhost:8100/health
```

### 本地开发

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 初始化数据库
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS cuhk_campus CHARACTER SET utf8mb4"
mysql -u root -p -D cuhk_campus < sql/docker_init.sql

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填入真实值

# 4. 启动（需 5 个终端窗口）
python mcp_servers/course_server.py      # 终端 1: Course MCP :8002
python mcp_servers/facility_server.py    # 终端 2: Facility MCP :8001
python agents/course_agent.py            # 终端 3: Course Agent :5005
python agents/facility_agent.py          # 终端 4: Facility Agent :5006
python run_web.py                        # 终端 5: Web Server :8100
```

### CLI 交互模式

```bash
python run_cli.py
```

### 手动运行爬虫

```bash
# 统一入口
python run_spiders.py --all              # 全部爬取
python run_spiders.py --spider news      # 指定爬虫

# 单独运行
python spiders/news.py --force --once    # 强制更新 + 单次执行
python spiders/events.py --force --once
python spiders/canteen.py --force --once
python spiders/library.py --force --once
python spiders/course.py --force --once
```

---

## API 接口

| 端点 | 方法 | 描述 |
|------|------|------|
| `/` | GET | Web 前端页面 |
| `/health` | GET | 综合健康检查 |
| `/api/query` | POST | 非流式查询 `{"query": "..."}` |
| `/api/stream` | WebSocket | 流式查询 |
| `/api/create_session` | POST | 创建会话 |
| `/api/history/{session_id}` | GET | 获取对话历史 |
| `/api/sources` | GET | 数据源状态 |

---

## 数据新鲜度

系统启动时自动检查 5 张表的数据新鲜度：

| 数据表 | 刷新阈值 | 自动刷新 |
|--------|---------|---------|
| campus_events | 24h | ✅ |
| campus_news | 24h | ✅ |
| canteen | 168h (7天) | ❌ 手动 |
| library_hours | 168h (7天) | ❌ 手动 |
| course_info | 168h (7天) | ❌ 手动 |

---

## 许可

本项目为个人学术项目，仅供学习与展示用途。
