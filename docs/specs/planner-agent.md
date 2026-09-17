---
title: 日程规划 Agent（PlannerAgent）
status: approved      # draft → approved → in-progress → done
created: 2026-09-17
author: Piova
---

# 日程规划 Agent（PlannerAgent）

## 1. 问题陈述（做什么，为什么）

当前 OrchestratorAgent 已实现「意图识别 + 并行委派 + 聚合」，但其聚合是**并列拼接**——多个意图各自查结果后 `\n\n` 拼接，没有「时间轴」与「依赖推理」。例如「CSCI2100 下课后去图书馆，再坐校巴回逸夫书院」这类**复合日程需求**，需要：先拿到下课时间 → 判断图书馆是否还开着 → 判断是否有末班校巴 → 输出一份**有时间顺序、带冲突告警**的日程。这正是「并行 + 判断 + 多级委派」的完整示范，也是 orchestrator 做不到、而用户上轮明确要求的「在业务中添加循环、并行、判断」。

本方案新增一个**纯编排型 specialist**——PlannerAgent(:5009)，把「日程规划」从 orchestrator 再往下委派一层，形成 **Web → Orchestrator → Planner → Course/Facility/Transport → MCP** 的三级 A2A 链，真正体现 agent→agent 委派的深度。

## 2. 目标 / 非目标

### 目标
- [ ] 新增 `agents/planner_agent.py`（:5009）——A2A server **同时**是 A2A client（委派 3 个 specialist）
- [ ] 规划四步算法：**拆解 → 并行委派 → 冲突判断 → 合成日程**
- [ ] 并行：`asyncio.gather` 并发下派独立子任务到 CourseQueryAssistant / FacilityQueryAssistant / TransportQueryAssistant
- [ ] 判断：对聚合结果做时间/地点**冲突检测**（如下课 vs 图书馆闭馆、末班车 vs 返程）
- [ ] 输出**带时间轴 + 冲突告警**的日程，而非并列拼接
- [ ] orchestrator 注册 `planning` 意图 → PlannerAgent（planner 输出已聚合，orchestrator 侧透传）
- [ ] trace 连续：`_trace_id` 经 orchestrator → planner → specialist → MCP 全链路贯通

### 非目标（Out of Scope）
- **不新增数据源 / 表 / MCP server**——纯复用现有 course / facility / transport 三个 specialist
- 不做确定性结构化冲突检测（specialist 返回的是格式化文本，本期用 LLM 判断冲突；结构化返回留后续）
- 不做日历持久化 / 用户订阅（规划结果仅当次返回）
- 不做多用户日程共享

## 3. 验收标准（Acceptance Criteria）

- **Given** 用户查询「帮我规划周四下午：CSCI2100 下课后去大学图书馆，再坐校巴回逸夫书院」，**When** orchestrator 识别为 `planning` 并下派 PlannerAgent，**Then** Planner 拆解为多个子任务，并行委派 course / library / transport，输出带时间顺序的日程
- **Given** 日程中存在时间冲突（如下课 18:15 但图书馆 18:00 闭馆），**When** Planner 做冲突判断，**Then** 输出明确标注该冲突并给出替代建议
- **Given** 子任务之间相互独立，**When** Planner 委派，**Then** 用 `asyncio.gather` 并行下派（日志/span 可见并发），非串行 for
- **Given** 某 specialist 返回异常/失败，**When** Planner 聚合，**Then** 该子任务降级为「未能获取」占位，其余子任务仍正常输出（整体不 500）
- **Given** 请求带 `X-Trace-Id`，**When** 全链路执行，**Then** orchestrator / planner / specialist 的 span 共享同一 trace_id（跨三级连续）
- **Given** planner 进程未启动，**When** orchestrator 下派 `planning` 意图，**Then** 返回优雅降级文案（复用重试 + 降级口径）
- **Given** 跑通现有 `test/`，**When** 执行，**Then** 无回归

## 4. 约束与依赖

### 约束
- **无状态**：对话历史由 orchestrator 随任务注入，Planner 不持有记忆
- **复用既有范式**：作为 client 用 `AgentNetwork` / `send_task_async` + `_trace_id` 注入；`handle_task` 同步实现、内部 `asyncio.run`（同 orchestrator / specialist）
- **重试与降级**：`tenacity` 指数退避（子任务委派 2 次），单子任务失败不拖垮整体
- **埋点**：复用 `a2a_agent_calls_total` / `a2a_agent_call_duration_seconds` / `agent_llm_*`，不新增指标
- **LLM**：走 `create_llm()`；规划相关 prompt 统一放 `app/prompts.py`（新增 3 个静态方法）
- **端口**：PlannerAgent = 5009
- **启动顺序**：PlannerAgent 必须在 OrchestratorAgent 之前（orchestrator 会委派它）

### 依赖
- `python-a2a`（`A2AServer`/`AgentNetwork`/`send_task_async`）
- 现有 CourseQueryAssistant(:5005) / FacilityQueryAssistant(:5006) / TransportQueryAssistant(:5008)（依赖 `transport-agent` spec 先落地）
- `app/prompts.py`、`app/llm.py`、`app/logging.py`、`app/observability.py`

## 5. 影响范围

- **新增**：
  - `agents/planner_agent.py` —— PlannerAgent（:5009），四步规划算法 + 三级委派
- **修改**：
  - `app/prompts.py` —— 新增 `planning_decompose_prompt()` / `planning_conflict_prompt()` / `planning_compose_prompt()`；`intent_prompt` 支持列表增 `planning` + 示例
  - `agents/orchestrator_agent.py` —— `INTENT_AGENT_MAP` 增 `"planning": "PlannerAgent"`、`AGENT_URLS` 增 `"PlannerAgent"`、`agent_network.add(...)`、`summarize_response` 增 planner 分支（透传）
  - `app/server.py` —— `/api/sources` 增 `planning` 项
  - `docker-entrypoint.py` —— 增 PlannerAgent(:5009) 启动 + 健康检查（在 orchestrator 之前、specialist 之后）
  - `README.md` / `CHANGELOG.md` —— 架构图、项目结构、端口表、意图路由表、版本条目
- **数据库变更**：无
- **新增 MCP 服务**：无

### PlannerAgent 四步算法

1. **拆解** `decompose(goal)`：LLM 把日程目标拆为子任务列表 `[{description, intent, time_constraint}]`
2. **并行委派**：`asyncio.gather` 按 `intent` 映射到 specialist（course/facility/transport），各自 `send_task_async`
3. **冲突判断** `detect_conflicts(subtasks, results)`：LLM 基于子任务时间约束与各 specialist 返回结果，判断时间/地点冲突（下课时 vs 图书馆闭馆、末班车 vs 返程等）
4. **合成** `compose_schedule(...)`：LLM 输出带时间轴、按顺序、含冲突告警与替代建议的日程

## 6. 测试计划

- [ ] 单测：`decompose` 拆解（mock LLM）、并行委派（mock `AgentNetwork`，断言 gather 并发）、单子任务失败降级
- [ ] 单测：conflict 判断（构造冲突/无冲突样本）、compose 合成格式
- [ ] 回归：`python -m pytest test/ -v` 全绿
- [ ] 集成：`docker compose up -d` 全栈，验证三级委派日程规划；查 `logs/app.log` 确认 trace_id 跨 orchestrator→planner→specialist 连续；复用 `scripts/bench_e2e.py` 记录新增一跳的延迟

## 7. 审批记录

| 阶段 | 状态 | 日期 | 备注 |
|------|------|------|------|
| spec 审批 | ✅ | 2026-09-17 | 用户批准（"批准spec开工"） |
| 实现完成 | ⬜ | | |
| 测试通过 | ⬜ | | |
