# Changelog

All notable changes to SmartCampus — CUHK 校园生活助手.

---

## [v3.2.0] — 2026-08-10

### 🐳 Docker 容器化部署 + 代码清理

#### Docker 部署（新增）
- `Dockerfile` — Python 3.11-slim 镜像，`ENV PYTHONPATH=/app`，健康检查
- `docker-compose.yml` — MySQL 8.0 + App 双服务编排，端口 8100/3308（避免与 PaperRag 冲突）
- `docker-entrypoint.py` — 容器启动编排器：MySQL 等待 → MCP → Agent → Web，SIGTERM 优雅关闭
- `.dockerignore` — 排除 `.git`/`.env`/`logs`/测试/旧版文件
- `sql/docker_init.sql` — 合并 DDL + 种子数据的 Docker 初始化脚本

#### MCP v2.0.0 完整适配
- `mcp_servers/course_server.py` — `FastMCP` → `MCPServer`，transport 参数移至 `run()`
- `mcp_servers/facility_server.py` — 同上，同时移除 7 个未使用导入
- `docker-entrypoint.py` — HTTP 健康检查适配 MCP v2.0.0（接受 400/405/406）

#### 数据库修复
- `course_info` 表新增 `created_at` 列（修复数据新鲜度检查 `Unknown column` 错误）
- `campus_news` 表移除未使用的 `image_url` 列
- `agents/facility_agent.py` 嵌入式 schema 同步移除 `image_url`

#### 爬虫 Docker 兼容
- 全部 5 个爬虫 `db_config` 改为读取 `DB_HOST`/`DB_USER`/`DB_PASSWORD`/`DB_NAME` 环境变量
- `--force --once` 模式下退出后不再进入定时循环

#### 代码清理（删除 12 个文件）
- **遗留文件**：`app.py`（Streamlit 旧版）、`config.example.py`（旧配置模板）
- **死测试**：`test/test_order_agent_server.py`（测试已删除的 BookingAgent）、`test/test_weather_mcp_server.py`（MCP v1.x API 不可用）
- **冗余 SQL**：`sql/insert.sql`、`sql/insert2.sql`、`sql/sql_data.sql`（全部被 `docker_init.sql` 包含）
- **残留文件**：`page-snapshot.txt`
- **所有 `__pycache__/` 目录**

#### 死代码移除
- `app/config.py`：`get_mysql_config()` 方法、`url_cuhk` 字段、模块级 `env` 变量、`__main__` 块
- `spiders/course.py`：`from collections import defaultdict`
- `requirements.txt`：`streamlit`、`aiohttp`、`lxml`、`sse-starlette`（减少 4 个无用依赖）

#### 文档
- `README.md` — 全面重写，反映 v3.2 架构
- `CHANGELOG.md` — 本条目

---

## [v3.1.0] — 2026-08-10

### 🏗️ 项目重构：目录结构工业标准化

#### 新目录结构

```
SmartCampus/
├── app/                    # 应用核心层（FastAPI + 配置 + LLM + 日志）
│   ├── __init__.py
│   ├── server.py           # ← web_server.py   FastAPI Web 网关
│   ├── cli.py              # ← main.py         命令行交互入口
│   ├── config.py           # ← config.py       全局配置（.env 驱动）
│   ├── prompts.py          # ← main_prompts.py LLM Prompt 模板
│   └── logging.py          # ← create_logger.py 日志系统
│
├── agents/                 # A2A Agent 层
│   ├── __init__.py
│   ├── course_agent.py     # ← weather_server.py   课程查询 (5005)
│   └── facility_agent.py   # ← ticket_server.py    设施查询 (5006)
│
├── mcp_servers/            # MCP 工具服务器层
│   ├── __init__.py
│   ├── course_server.py    # ← mcp_weather_server.py    课程 MCP (8002)
│   └── facility_server.py  # ← mcp_ticket_server.py     设施 MCP (8001)
│
├── data/                   # 数据层
│   ├── __init__.py
│   ├── database.py         # ← query1.py         MySQL 服务封装
│   └── format.py           # ← format.py         JSON 序列化工具
│
├── spiders/                # 爬虫模块
│   ├── __init__.py
│   ├── course.py           # ← spider_course.py
│   ├── events.py           # ← spider_campus.py
│   ├── news.py             # ← spider_news.py
│   ├── canteen.py          # ← spider_canteen.py
│   └── library.py          # ← spider_library_hours.py
│
├── static/                 # 前端静态文件（不变）
├── sql/                    # 数据库 DDL / 种子数据（不变）
├── test/                   # 测试脚本（更新 import）
├── run_web.py              # Web 启动入口（新增）
├── run_cli.py              # CLI 启动入口（新增）
├── requirements.txt        # 依赖清单（重写为直接依赖）
├── CHANGELOG.md            # 更新日志（本文件）
├── .env / .env.example
└── README.md
```

#### 新增（Added）

- `run_web.py` / `run_cli.py` — 项目根目录入口脚本，指向 `app/` 下的模块
- `requirements.txt` — 从 127 行冻结版本重写为精简的直接依赖清单
- 各目录 `__init__.py` — 标准 Python 包声明
- `CHANGELOG.md` — 项目更新日志

#### 变更（Changed）

- **修正误导性命名**：
  - `weather_server.py` → `course_agent.py`（原名暗示天气，实际处理课程查询）
  - `ticket_server.py` → `facility_agent.py`（原名暗示工单，实际处理设施查询）
  - `mcp_weather_server.py` → `course_server.py`（同上）
  - `mcp_ticket_server.py` → `facility_server.py`（同上）
  - `query1.py` → `database.py`（原名无业务含义）
  - `create_logger.py` → `logging.py`（动词→名词，更符合模块命名惯例）
  - `main_prompts.py` → `prompts.py`（去掉多余前缀）
- **调整路径**：
  - 爬虫从 `utils/` 移至独立 `spiders/`
  - 格式化工具从 `utils/format.py` 移至 `data/format.py`
  - `app/config.py` 中 `_project_dir` 适配新目录层级
  - `app/server.py` 中 `check_and_refresh_data()` 的脚本路径同步更新
  - `app/server.py` 中 `uvicorn.run()` 从 `"web_server:app"` → `"app.server:app"`
- **全部 23 个 .py 文件的 import 路径同步更新**，零残留旧路径

#### 删除（Removed）

- `a2a_server/order_server.py` — 废弃的预约 Agent（v1 MCP 导入，从未映射到任何意图）
- `mcp_server/mcp_order_server.py` — 废弃的预约 MCP 服务器（连接不存在端口 8003）
- `scripts/scheduled_tasks/` — Windows Task Scheduler 注册脚本（已放弃此方案，改用启动自检）
- 旧目录：`a2a_server/` `mcp_server/` `query_data/` `utils/`
- 根目录散落的旧文件：`config.py` `create_logger.py` `main_prompts.py` `web_server.py` `main.py`

#### 修复（Fixed）

- `test/test_weather_agent_server.py` — import 适配新路径
- `test/test_order_agent_server.py` — import 适配新路径
- `app.py`（Streamlit 旧版）— import 适配新路径（保留作参考）

#### 架构理由

| 设计决策 | 理由 |
|---------|------|
| 5 层分离（app/agents/mcp_servers/data/spiders） | 每层职责单一，符合关注点分离原则 |
| 2 个 Agent 而非 5 个 | 按 MCP 数据源拆分：Course MCP → Course Agent，Facility MCP → Facility Agent（含 4 种意图） |
| 爬虫独立模块 | 爬虫自包含（自带 db_config），可独立运行，与 MCP/Agent 无耦合 |
| 数据层独立 | MySQL 封装 + JSON 序列化被 MCP Server 共用，抽离避免重复 |

---

## [v3.0.1] — 2026-08-10

### 5 项产品化改进

#### 配置安全
- `config.py` 改用 `python-dotenv` 从 `.env` 加载敏感信息
- API Key / DB Password 不再硬编码，移除出 `.gitignore`
- 新增 `.env.example` 作为配置模板

#### 输入校验
- 新增 `QueryRequest` Pydantic 模型
- `field_validator` 清理控制字符、限制长度

#### LLM 重试
- 意图识别：`@retry(stop=3, wait=exponential)` 
- A2A Agent 调用：`@retry(stop=2, wait=exponential)`
- 使用 `tenacity` 库，指数退避 1-8s

#### 健康检查增强
- `GET /health` 检查全部组件：Web Server + 2 个 A2A Agent + MySQL
- 返回 `healthy` / `degraded` 状态

#### 前端错误重试
- 错误消息气泡内嵌 `🔄 点击重试` 按钮
- WebSocket 断开时提供刷新按钮

---

## [v3.0.0] — 2026-08-09

### MCP v2.0 兼容 + 启动自检

#### MCP v2.0.0 适配
- `streamablehttp_client` → `streamable_http_client`（import 路径修正）
- 3-tuple `(read, write, _)` → 2-tuple `(read, write)`（解包修正）
- 两个 A2A Agent 均已修复

#### 启动自检
- 启动时自动检查 5 张数据表的 `MAX(created_at)`
- 高频数据（新闻/活动 > 24h）自动刷新
- 低频数据（餐厅/图书馆/课程 > 168h）仅提示

#### 其他
- 爬虫新增 `--once` 模式：更新完成后 `sys.exit(0)`，不进入定时循环
- LLM 调用从同步 `chain.invoke()` 改为异步 `chain.ainvoke()`
- 移除 BookingAssistant（端口 5007），系统从 3 Agent 精简为 2 个

---

## 版本约定

- **主版本号**：架构重大变更（如数据源重构、目录重构）
- **次版本号**：功能新增（如健康检查、重试机制）
- **修订号**：Bug 修复（如 MCP 兼容性、导入路径修正）

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。
