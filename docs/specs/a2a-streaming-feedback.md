---
title: A2A 流式中间反馈与反问闭环
status: done          # draft → approved → in-progress → done
created: 2026-09-17
author: Piova
---

# A2A 流式中间反馈与反问闭环

## 1. 问题陈述（做什么，为什么）

当前 A2A 链路是**严格单向、同步阻塞**的：Orchestrator（及 Planner）用 `send_task_async` 一次性下派，**阻塞等到最终 artifact** 才返回；WebSocket 前端的「打字」是拿到完整结果后的字符级模拟，并非真实进度。下层 specialist 处理过程中**无法向编排层反馈中间状态**，遇到缺信息时虽已返回 `TaskState.INPUT_REQUIRED`，但编排层把它当普通文本透传（甚至再过一遍 summarize），**没有形成「反问 → 用户补答 → 续跑」的语义闭环**。

本方案补齐「下层能反馈、能反问」的能力，让多级 agent 链路从「黑盒等结果」变为「边处理边可见、可追问」。

## 2. 目标 / 非目标

### 目标
- [x] **子能力 A — input-required 反问闭环**：specialist 缺信息时返回的 `INPUT_REQUIRED` 被编排层**识别为「追问」而非结果**，逐级上抛至前端，前端提示用户补充；用户补答后（复用现有 `conversation_history` 多轮注入）重跑该子任务续跑。
- [x] **子能力 B — 阶段级中间进度流**：specialist / planner / orchestrator 处理过程中，按**阶段（stage）**上报进度（如「正在拆解任务 / 正在查询课程 / 正在检测冲突 / 正在合成日程」），逐级上抛至前端。
- [x] 前端 WebSocket 新增 `progress` 与 `input_required` 两类事件，展示阶段指示与追问气泡。
- [x] 全链路 `_trace_id` 在进度通道上保持连续。

### 非目标（Out of Scope）
- **不做 token 级逐字流式**（LLM 增量输出）——本期只做**阶段级（stage-level）**进度，token 级留后续。
- **不做对等互调 / 网状拓扑**——那是「方向 2」，本期不改下层之间的交互关系。
- **不做 push notification（Webhook 主动推送）**——跨进程进度用 A2A `tasks/get` **轮询**，不做服务端主动回调。
- 不改 MCP 层与数据库 schema，无 Alembic 迁移。

## 3. 验收标准（Acceptance Criteria）

### 子能力 A — 反问闭环
- **Given** 用户查询「有什么课」且 course agent 判定缺课程代码，**When** course agent 返回 `INPUT_REQUIRED`，**Then** orchestrator 不再把追问当结果 summarize，而是以「追问」语义上抛，前端收到 `input_required` 事件并展示「请提供课程代码或名称」。
- **Given** 上一步用户补充「CSCI2100」，**When** web 层把历史注入重新下派，**Then** course agent 带着补答执行查询并返回结果（两轮闭环完成）。
- **Given** planner 并行委派中某 specialist 返回 `INPUT_REQUIRED`，**When** planner 聚合，**Then** 该子任务以「追问」标记透传到最终日程/追问中，不整体失败。

### 子能力 B — 阶段级进度流
- **Given** 用户提交 planning 请求，**When** 全链路执行，**Then** 前端**在处理过程中**（而非结束后）依次收到阶段进度：拆解 → 并行查询（课程/交通/设施）→ 冲突检测 → 合成。
- **Given** 单意图（如交通路线）请求，**When** transport agent 处理，**Then** 前端依次收到「解析意图 → 图搜索/查询」两个阶段。
- **Given** 下层进度上报，**When** 上层轮询，**Then** 进度经 orchestrator/planner 透传上抛，`_trace_id` 连续。
- **Given** 无进度能力的降级（如 specialist 未改造 / 轮询超时），**When** 执行，**Then** 回退到原有「一次性返回最终结果」，不阻塞、不报错。

## 4. 约束与依赖

### 技术选型：阶段级进度用「轮询（tasks/get）」而非 SSE

| 维度 | 轮询（`tasks/get`） | SSE（`tasks/stream`） |
|------|---------------------|----------------------|
| 方向 | 客户端周期性主动请求 | 服务端长连接持续推送 |
| 连接 | 短连接，一问一答 | 一条 `text/event-stream` 长连接 |
| 延迟 | 最晚晚一个轮询间隔 | 事件即达，近零延迟 |
| 资源 | 每次一个短 HTTP，用完释放 | 每条任务占一个常驻 worker 连接 |
| 容错 | 无状态，断了重 poll 即可 | 需处理重连 + `resubscribe` |

**结论：阶段级（低频、粒度粗，几秒才变一次阶段）选轮询；token 级（高频、要求低延迟）选 SSE。**

理由：
1. 阶段几秒一变，轮询间隔 300–500ms 的最坏延迟可忽略，SSE 的零延迟优势用不上。
2. 每个 agent 是 Flask/uvicorn，一条 planning 并发 3 个 specialist；SSE 会占用 3 条长连接直到任务结束，轮询短连接对 worker 池更友好。
3. 轮询幂等、容错简单；且只需改客户端 `call_agent`（send 拿 id → 循环 `get_task`），不用碰库的同步 generator + `stream_with_context` 那套 SSE 生成器。

> 注：两种方案的 server 端改造量相同（都是「同步一次性」→「后台处理 + 中间状态」），差异只在客户端读取侧；本轮选轮询。

### 约束
- **阶段级，非 token 级**：进度粒度 = 业务阶段，复用现有 `span` 命名（`llm_*` / `a2a_call_*` / `agent_handle_task`）对应的阶段。
- **不侵入 python_a2a 库**：库装在 site-packages 不可 commit；改造点落在项目代码（agent 子类 override 入口 / 新增进度模块）。
- **跨进程进度通道 = A2A `tasks/get` 轮询**：客户端从 `send_task_async`（阻塞）改为「send 拿 task_id → 轮询 `get_task(task_id)` 读 `status.message` 中间状态 → final 取 artifact」。
- **后台处理**：要让轮询能读到中间状态，server 侧需把任务处理放入后台线程并先返回 `working` + task_id，处理中逐步更新 `self.tasks[task_id]`（覆盖库默认「同步跑完才存」的入口）。
- **LLM / 埋点 / 日志 / 输入过滤**：沿用 `app/llm.py`、`app/logging.py`、`app/observability.py`；不新增直连 DB、不手写 SQL 拼接、不在业务层重复做输入过滤。
- **超时**：进度轮询总时长沿用 `agent.timeout=180` 上限，避免 planning 长链路过早断开。

### 依赖
- `python-a2a` 的 `self.tasks` 存储、`tasks/get` 端点、client `get_task(task_id)`（均已确认存在）。
- 现有 specialist（course/facility/transport）、PlannerAgent、OrchestratorAgent、web 网关、`static/index.html`。
- `app/config.py`、`app/observability.py`、`app/prompts.py`。

## 5. 影响范围

- **新增**：
  - `app/progress.py` —— 阶段常量（`STAGE_*`）+ 轻量进度格式化；跨进程进度走 A2A `tasks/get`，本模块只承载「阶段文本 + trace_id」的规约。
- **修改（子能力 A）**：
  - `agents/orchestrator_agent.py` —— `call_agent` 识别 `input_required` 状态并上抛；`summarize_response` 对追问不做 LLM summarize（透传）。
  - `agents/planner_agent.py` —— `call_agent` 同上；聚合时对 `input_required` 子任务标记追问。
  - `app/server.py` —— `process_query_stream` 上抛 `needs_input`；WebSocket 新增 `input_required` 事件；REST `/api/query` 返回 `needs_input` 字段。
- **修改（子能力 B）**：
  - `agents/course_agent.py` / `facility_agent.py` / `transport_agent.py` —— 阶段上报（生成 SQL / 执行 MCP 查询两阶段）；任务入口支持后台处理 + 中间状态。
  - `agents/planner_agent.py` —— 四步各设阶段上报；委派改轮询。
  - `agents/orchestrator_agent.py` —— 意图识别 / 委派 / 聚合各设阶段；委派改轮询。
  - `app/server.py` —— `call_orchestrator` 改轮询，把阶段进度经 WebSocket `progress` 事件上抛。
  - `static/index.html` —— 处理 `progress` / `input_required` 事件。
  - `README.md` / `CHANGELOG.md` —— 文档与版本条目。
- **数据库变更**：无。
- **新增 MCP 服务**：无。

## 6. 测试计划

- [x] 单测：`input_required` 语义识别（`test_agent_result_needs_input` / `test_status_message_text_variants`）。
- [x] 单测：阶段进度轮询（`test_await_task_with_progress_forwards_new_stages`，断言回调按序收到各阶段、无重复）。
- [x] 单测：轮询超时/降级（`test_await_task_with_progress_degrades_when_no_progress`，mock 无进度 → 静默回退一次性返回）。
- [x] 回归：`python -m pytest test/ -v` 全绿（17 passed，测试需 MCP 服务未运行，沿用 mock）。
- [x] 集成：本地全链路（MySQL + 9 服务），验证（1）planning 请求前端依次收到 4 阶段；（2）「有什么课→补 CSCI2100」两轮闭环；（3）trace_id 跨进度通道连续（下游阶段带 `[PlannerAgent] [XxxQueryAssistant]` 前缀上抛）。

## 7. 审批记录

| 阶段 | 状态 | 日期 | 备注 |
|------|------|------|------|
| spec 审批 | ✅ | 2026-09-17 | 用户批准（「补充进去 然后开工」，确认阶段级 + 轮询） |
| 实现完成 | ✅ | 2026-09-17 | 子能力 A+B 代码完成（`app/a2a_types.py` / `app/progress.py` / 各 agent / `server.py` / `index.html`） |
| 测试通过 | ✅ | 2026-09-17 | 单元 + 回归 18/18 通过；端到端 9 服务集成验证通过（阶段进度 / 反问 / 两轮闭环 / trace 连续） |
