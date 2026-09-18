# Changelog

All notable changes to SmartCampus — CUHK 校园生活助手.

---

## [v3.10.0] — 2026-09-18

### 🚀 全链路延迟优化（token 级流式 + 上游提速）

上一期 v3.9.0 补齐「阶段级进度」后，实测发现**最终合成/summarize 只占全链路
0.3~1.5s，瓶颈全在上游**（意图识别、SQL 生成、记忆召回、DeepSeek 429 退避）。
本期分两步：先把最终输出改成 token 级流式（消除感知等待），再治理上游
（限流、缓存、记忆召回、实体归一化）。详见 `docs/specs/llm-latency-optimization.md`
与 `docs/specs/upstream-latency-optimization.md`。

#### 新增（Added）
- `app/llm.py` — `create_llm` 增加 `streaming`（token 级流式）、`max_retries=1`（减少 SDK 内部重试）、`model`（可覆盖模型）三个可选参数
- `app/progress.py` — `ProgressStore` 增加 `append_output` / `get_output` 累积 token 输出；`/progress/<trace_id>` 端点返回 `output`；`await_task_with_progress` 增加 `on_output` 回调；`fetch_progress` 返回 `(stages, output)`
- `agents/course_agent.py` — `_sql_llm_by_code` 按课程代码归一化缓存（`functools.lru_cache`），同课程不同表述命中同一缓存条目
- `agents/transport_agent.py` — `_transport_llm_by_code` 按路线号归一化缓存（带「班次关键词 + 非路线规划」守卫）
- `agents/orchestrator_agent.py` — `_intent_llm_raw` 意图识别结果缓存

#### 变更（Changed）
- `agents/orchestrator_agent.py` / `planner_agent.py` — 最终 summarize / 合成改用 `streaming_llm + astream` 逐 token 上抛；`@retry` 退避 `wait_exponential` → `wait_fixed(0.5)`
- `agents/course_agent.py` / `facility_agent.py` — SQL 生成接入 `_sql_llm_raw` 进程内缓存
- `app/server.py` — `call_orchestrator` 退避 `wait_exponential` → `wait_fixed(0.5)`；`process_query_stream` 上抛 `token` 事件
- `app/prompts.py` — `planning_conflict_prompt` + `planning_compose_prompt` 合并为 `planning_synthesize_prompt`（冲突检测 + 合成一次调用，planning 从 7 次降为 6 次）
- `app/memory.py` — 语义召回快速路径（无长期记忆时跳过 embed）+ `_cosine_topk` 复用预载记忆 + `_ensure_connection` 改用 `ping(reconnect=True)` 静默重连
- `static/index.html` — 直接走 WebSocket 流式渲染 token / 阶段 / 追问；流式气泡为空时清理；网络错误统一提示 + 重试按钮

#### 测试（Tested）
- `test/e2e_verify.py` — 增加 token 流式 / 首 token 延迟 / 总耗时测量口径
- `test/test_streaming_feedback.py` — 反问语义 / 进度轮询 / 降级 / TaskState 规范字符串回归
- 端到端验证：限流治理（日志 `Retrying` 计数 0）、SQL 缓存命中（run1/run2 同时间戳无 deepseek POST）、记忆召回无 `MySQL 连接已断开` 告警

#### 已知边界（Known Limits）
- ≤12s / ≤35s 目标未达成：单意图 13.4s、planning 50.7~61.6s，瓶颈为 **DeepSeek API 单次调用 3~23s 的固有延迟**，代码层已无杠杆（缓存只覆盖意图/SQL，summarize 与拆解/合成每轮仍需调 LLM）。后续方向：减少 LLM 调用次数或响应级缓存，需另立 spec。

---

## [v3.9.0] — 2026-09-17

### 🔄 A2A 流式中间反馈 + 反问闭环

补齐「下层能反馈、能反问」的能力，把多级 agent 链路从「黑盒等结果」变为
「边处理边可见、可追问」：阶段级进度逐级上抛 + input-required 反问闭环。

#### 新增（Added）
- `app/a2a_types.py` — `AgentResult`（区分结果 / 追问，`needs_input` 判定）+ `status_message_text`（TaskStatus.message 多形态提取）
- `app/progress.py` — 阶段常量 `STAGE_*` + 线程安全 `ProgressStore` + `/progress/<trace_id>` 端点 + `await_task_with_progress`（后台阻塞等结果 + 前台轮询上抛）
- `test/test_streaming_feedback.py` — 反问语义 / 进度轮询 / 降级 / TaskState 规范字符串回归 6 项单元测试

#### 变更（Changed）
- `agents/course_agent.py` / `facility_agent.py` / `transport_agent.py` — 处理过程按阶段上报（生成 SQL / 解析意图 / 执行 MCP 查询），override `setup_routes` 注册进度端点
- `agents/planner_agent.py` — 四步各设阶段（拆解 / 委派 / 冲突 / 合成）；委派改轮询；子任务 input-required 以「⚠️ 需要补充信息」透传
- `agents/orchestrator_agent.py` — 意图 / 委派 / 聚合各设阶段；委派改轮询；追问不再过 summarize，逐级上抛
- `app/server.py` — `call_orchestrator` 改轮询；`process_query_stream` 上抛进度与 `needs_input`；WebSocket 新增 `progress` / `input_required` 事件；REST `/api/query` 返回 `needs_input`
- `app/cli.py` — input-required 追问以「💡 」前缀展示
- `static/index.html` — 处理 `progress`（⏳ 阶段提示）与 `input_required`（💡 追问气泡）事件

#### 技术选型
- 阶段级进度用 **轮询（`/progress/<trace_id>`）而非 SSE**：阶段几秒一变，轮询短连接对 worker 池更友好，容错简单；token 级留后续

#### 修复（Fixed）
- `app/server.py` / `agents/orchestrator_agent.py` / `agents/planner_agent.py` / `app/cli.py` — 委派结果状态用 `str(TaskState)` 得 `"TaskState.COMPLETED"`（≠ `"completed"`），导致 completed 被当非 completed 返回空文本 → 改用 `status.state.value` 取规范字符串
- `app/observability.py` — `_NoopMetric` 缺 `dec()`，WebSocket 关闭时 `websocket_connections.dec()` 抛 `AttributeError`（prometheus_client 未装时）→ 补 `dec()`

#### 未改动（Unchanged）
- 无数据库迁移、无新增 MCP 服务

---

## [v3.8.0] — 2026-09-17

### 🚌 校巴交通 Agent + 🗓️ 日程规划 Agent（A2A 差异化扩展）

新增两类差异化 Agent：校巴交通（图搜索规划型）与日程规划（编排规划型），
进一步体现 A2A 多 agent 交互（并行委派、二级委派、判断）。

#### 新增（Added）
- `mcp_servers/transport_server.py` — 交通 MCP（:8003）：`query_transport` / `get_transport_schema` / `find_route`
- `data/transport.py` — `TransportService`：内存构建校巴图 + Dijkstra（站数×1 + 换乘×1000）
- `agents/transport_agent.py` — TransportQueryAssistant（:5008）：路线规划 / 时刻表
- `agents/planner_agent.py` — PlannerAgent（:5009）：拆解 → 并行委派 → 冲突判断 → 合成日程（纯编排，无新数据源）
- `spiders/transport.py` — 校巴路线/站点基线数据（6 条路线）
- `migrations/versions/004_transport_tables.py` — 新增 `bus_routes` / `bus_stops` 两张表
- `app/prompts.py` — 新增 3 个规划 prompt + `planning` 意图 + `summarize_transport_prompt`

#### 变更（Changed）
- `agents/orchestrator_agent.py` — 意图路由新增 `transport` / `planning`
- `app/config.py` — 新增 `MCP_TRANSPORT_URL`
- `app/server.py` — `/api/sources` 新增校巴交通 / 日程规划
- `docker-entrypoint.py` — 新增 Transport MCP/Agent + Planner Agent 启动
- `docker-compose.yml` — 补 `MCP_TRANSPORT_URL`

#### 修复（Fixed）
- `data/transport.py` — 换乘段上车站丢失（`n_stops=0`），换乘站现同时作为前段下车站与后段上车站
- A2A 客户端默认 30s 读超时过短 → 委派处 `agent.timeout=180`（`orchestrator_agent.py` / `planner_agent.py` / `server.py`）

#### 未改动（Unchanged）
- `course` / `facility` 两个 MCP server 与 Agent 零改动

---

## [v3.7.0] — 2026-09-17

### 🤖 A2A Orchestrator Agent（多 agent 编排改造）

把「意图识别 + 路由 + 委派 + 聚合」从 Web 网关剥离为独立的 OrchestratorAgent，
A2A 从「单向单跳」升级为「两级委派 + 并行编排」，真正体现多 agent 交互。

#### 新增（Added）
- `agents/orchestrator_agent.py` — OrchestratorAgent(:5007)，A2A server + client 双角色
- 多意图 `asyncio.gather` 并行委派 specialist agent，再聚合为单一回答

#### 变更（Changed）
- `app/server.py` — 退化为纯 A2A client：删除意图识别/天气/推荐/汇总逻辑，网关不再调 LLM
- `app/config.py` — 删除 `intent` dict，新增 `ORCHESTRATOR_URL`（默认 `http://127.0.0.1:5007`）
- `app/cli.py` — 改为委派 OrchestratorAgent，消除与网关重复的路由/汇总逻辑
- `docker-entrypoint.py` — 新增 Orchestrator Agent(:5007) 启动 + 健康检查（MCP 之后、Web 之前）
- `docker-compose.yml` — 补注释说明（orchestrator 由 entrypoint 拉起，无新增 service）
- `README.md` — 架构图、项目结构、端口表、本地启动步骤更新

#### 未改动（Unchanged）
- `agents/course_agent.py` / `agents/facility_agent.py` 与两个 MCP server 零改动
- 无数据库迁移、无新增 MCP 服务

---

## [v3.5.1] — 2026-08-13

### 🔗 补全全链路 Trace 传播（Agent → MCP → DB）

#### 修复（Fixed）

- **Agent → MCP 链路 trace_id 未接线**：`observability.py` 声称「跨进程传播通过 MCP `_meta` 字段传递」，
  但实际未实现——Agent 调用 `call_tool` 时未携带 trace_id，MCP 服务器也未提取，导致 MCP 侧的
  `db_execute_query` span 生成全新 trace_id，与上游 Web/Agent 链路断开。
  - `agents/course_agent.py` — `_call_mcp_sync` / `_fetch_schema_async` 通过 `call_tool(meta={"trace_id": ...})` 下发
  - `agents/facility_agent.py` — 同上
  - `mcp_servers/course_server.py` — 工具函数新增 `ctx: Context` 参数，新增 `_inject_trace_id()` 从请求 `_meta` 提取并注入
  - `mcp_servers/facility_server.py` — 同上
- **mcp 2.0.0 依赖缺失**：`pydantic 2.13.x` 与 `typing-inspection 0.4.1` 不兼容、缺 `opentelemetry-api`，
  导致 `import mcp` 直接崩溃。修复：升级 `typing-inspection → 0.4.4`、补装 `opentelemetry-api → 1.44.0`。

#### 验证（Verified）

- 端到端测试：MCP 客户端经 `_meta` 下发 trace_id，`logs/app.log` 中工具日志与 `db_execute_query`
  span 的 `trace_id` 完全一致（此前为随机新 trace_id）。course（8002）与 facility（8001）两条链路均通过。

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
