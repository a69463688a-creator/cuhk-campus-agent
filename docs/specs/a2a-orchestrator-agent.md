---
title: A2A Orchestrator Agent（多 agent 编排改造）
status: in-progress  # draft → approved → in-progress → done
created: 2026-09-17
author: Piova
---

# A2A Orchestrator Agent（多 agent 编排改造）

## 1. 问题陈述（做什么，为什么）

当前系统名义上是「基于 A2A 的多 agent 架构」，但 A2A 只被用成一层单向 RPC 传输，未体现多 agent 交互：

1. **意图识别在网关**：`app/server.py` 的 `recognize_intent()` 由 Web 进程自己调 LLM 做意图识别，与 A2A 无关。
2. **路由硬编码**：`config.py` 的 `conf.intent` dict 写死「意图 → Agent 名」，与 AgentCard 的 `skills`/`description` 完全脱节；`AgentNetwork` 只当端点注册表用。
3. **只有 client→server 单跳**：两个 agent 只「收」任务（`handle_task`），从不作为 client 去调别的 agent，真正的 agent→agent 委派一次都没有。
4. **weather / recommend 连 agent 都不是**：直接写在网关里（直连 Open-Meteo / 直调 LLM）。
5. **多意图串行**：`process_query_stream` 用 for 循环逐个处理意图，多 agent 的并行能力被浪费。

结果：**全部「智能」（意图 + 汇总）堆在网关，agent 退化成被 HTTP 包了一层的 SQL 工具**，无法体现 A2A 协议设计要解决的核心问题——AgentCard 发现、agent→agent 委派、并行编排。

本方案引入一个 **Orchestrator（编排）Agent**，把「意图识别 + 路由 + 委派 + 聚合」从网关剥离成真正的 A2A agent，网关退化为纯 A2A client。改造后链路从「单向单跳」升级为「两级委派 + 并行编排」，真正体现多 agent 交互。

## 2. 目标 / 非目标

### 目标
- [x] 新增 `agents/orchestrator_agent.py`——一个 A2A server（接收网关任务）**同时**是 A2A client（委派 specialist agent），端口 5007
- [x] 把意图识别、路由、结果汇总逻辑从 `app/server.py` 迁入 orchestrator，网关不再调 LLM
- [x] 实现 agent→agent 委派：orchestrator 作为 client 调用 CourseQueryAssistant / FacilityQueryAssistant
- [x] 多意图**并行**下派（`asyncio.gather`），再聚合为单一回答
- [x] weather / recommend 保留在 orchestrator 内部直连 / 直调 LLM（不单独 agent 化）
- [x] 网关退化为纯 A2A client：只保留 HTTP/WS、记忆召回与落库、问候短路、trace_id 注入、metrics
- [x] trace 连续：trace_id 经「网关 → orchestrator → specialist agent → MCP」全链路贯通（orchestrator 同时做「提取」与「注入」）
- [x] 编排 agent 不可达时网关优雅降级（不 500）
- [x] course / facility 两个 agent 与两个 MCP server **零改动**

### 非目标（Out of Scope）
- 不做 AgentCard 动态发现（读 `/.well-known/agent-card.json` 的 skills 自动路由）——本期用 orchestrator 内部映射，动态发现留第二期
- 不做 weather / recommend 的 agent 化
- 不做 specialist agent 之间的互调（如 Course 中途调 Facility）
- 不改 MCP 协议、不改数据库、无 Alembic 迁移
- 不做完整多用户鉴权

## 3. 验收标准（Acceptance Criteria）

- **Given** 一条单意图课程查询，**When** 网关收到请求，**Then** 网关只发一个任务给 orchestrator，orchestrator 委派 CourseQueryAssistant 并聚合结果，网关流式返回，回答质量与改造前一致
- **Given** 一条多意图查询（如「CSCI2100 上课时间 + 今天天气」），**When** orchestrator 处理，**Then** 两个意图并行下派、结果聚合为单一回答
- **Given** weather / recommend 意图，**When** orchestrator 处理，**Then** 在 orchestrator 内部完成，不委派任何 specialist agent
- **Given** 网关请求带 `X-Trace-Id`，**When** 全链路执行，**Then** orchestrator 与 specialist 的 span 日志共享同一 trace_id（跨新的一跳仍连续）
- **Given** orchestrator 进程未启动，**When** 网关转发，**Then** 返回优雅降级文案（含重试），而非 500 / 抛异常
- **Given** 「你好」问候，**When** 网关收到，**Then** 由网关规则直接回复，不触达 orchestrator（免一跳）
- **Given** 改造后跑通现有 `test/` 用例，**When** 执行，**Then** course / facility / MCP 链路无回归

## 4. 约束与依赖

### 约束
- **orchestrator 无状态**：与现有 agent 一致，对话历史由调用方（网关）组装后随任务消息注入，orchestrator 不持有记忆；记忆（MemoryManager）仍留在网关层
- **复用现有组件**：LLM 走 `app/llm.py` 的 `create_llm()`；意图/汇总 prompt 复用 `app/prompts.py`；埋点复用 `app/observability.py`
- **沿用既有 A2A 调用范式**：orchestrator 作为 client 复用 `AgentNetwork` / `send_task_async`（同 `server.py` 现状）；`handle_task` 为同步实现，内部用 `asyncio.run(gather(...))` 并行调 specialist（同 `cli.py` 与 specialist 的既有 `asyncio.run` 范式）
- **trace 传播对称**：orchestrator 入站任务提取 `_trace_id`（同 specialist `handle_task`），出站任务注入 `_trace_id`（同 `server.py` 的 `call_agent`）
- **重试与降级**：沿用 `tenacity` 指数退避（意图识别 3 次、agent 调用 2 次），与现有 `server.py` 口径一致
- **端口**：orchestrator 用 5007（历史上 BookingAssistant 释放的端口）

### 依赖
- `python-a2a`（`A2AServer`/`run_server`/`AgentNetwork`/`Message`/`Task`）
- `app/config.py`、`app/llm.py`、`app/prompts.py`、`app/logging.py`、`app/observability.py`
- 现有 CourseQueryAssistant(:5005) / FacilityQueryAssistant(:5006) 两 agent 及两个 MCP server（不修改）
- Open-Meteo 天气 API（orchestrator 内部直连，逻辑从 `server.py` 迁移）

## 5. 影响范围

- **新增**：
  - `agents/orchestrator_agent.py` —— Orchestrator Agent（A2A server + client），含意图识别、内部映射（意图 → agent）、并行委派、聚合、weather/recommend 内部处理、trace 提取/注入
- **修改**：
  - `app/server.py` —— 删除 `recognize_intent` / `call_agent` / `summarize_response` / `fetch_weather` / `format_weather_for_prompt` 及 weather/recommend 分支；`process_query_stream` 改为「记忆召回 → 问候短路 → 发送任务给 orchestrator → 保存回复」；保留 `_get_memory`/`check_greeting`/trace 中间件/metrics
  - `app/config.py` —— 删除 `intent` dict（迁移到 orchestrator 内部常量）；新增 `ORCHESTRATOR_URL`（默认 `http://127.0.0.1:5007`）
  - `app/cli.py` —— 改为向 orchestrator 发送任务（复用其自身 in-memory history），消除与网关重复的路由/汇总逻辑
  - `docker-entrypoint.py` —— 增加 Orchestrator Agent(:5007) 启动 + 健康检查（位于 MCP 之后、Web 之前）
  - `docker-compose.yml` —— 无新增 service（单容器编排，orchestrator 由 entrypoint 拉起），补注释说明
  - `README.md` / `CHANGELOG.md` —— 架构图与端口表更新（新增 5007）
- **数据库变更**：无
- **新增 MCP 服务**：无

## 6. 测试计划

- [ ] 单元测试：orchestrator 意图路由（mock specialist）、多意图并行下派、weather/recommend 内部处理、聚合逻辑、trace_id 注入（mock `AgentNetwork`）
- [ ] 降级测试：orchestrator 不可达时网关返回优雅文案
- [ ] 回归测试：`python -m pytest test/ -v` 全绿，course/facility/MCP 无改动回归
- [ ] 集成/E2E：`docker compose up -d` 全栈，验证单意图 + 多意图 + 天气/推荐查询；查 `logs/app.log` 确认 trace_id 跨网关→orchestrator→specialist 连续
- [ ] 端到端延迟：复用 `scripts/bench_e2e.py`，对比改造前后 mean/P95（记录新增一跳的开销）

## 7. 审批记录

| 阶段 | 状态 | 日期 | 备注 |
|------|------|------|------|
| spec 审批 | ✅ | 2026-09-17 | 用户口头批准（"执行spec"） |
| 实现完成 | ✅ | 2026-09-17 | 全部目标已实现；py_compile + import 校验 + 记忆单测 11/11 通过 |
| 测试通过 | ⬜ | | |
