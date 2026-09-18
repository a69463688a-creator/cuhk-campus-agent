---
title: LLM 链路性能优化（token 级流式 + 削减调用）
status: done  # draft → approved → in-progress → done
created: 2026-09-18
author: Piova
---

# LLM 链路性能优化（token 级流式 + 削减调用）

## 1. 问题陈述（做什么，为什么）

端到端实测：planning 请求 **36s（冷）~ 63.8s（热）**，单意图（课程/交通）**13~16s**。根因是**多级串行 LLM 链 + 无流式**：

- planning 走 7 次 LLM 调用、4~5 轮串行（意图 → 拆解 → 3× specialist → 冲突 → 合成）。
- 每次 `ChatOpenAI.invoke()` 同步等**完整输出**，无 token 流式，前端首字延迟 = 整条链耗时。
- 前端拿到结果后再用 `0.02s/字符` 的**假打字**补流式，370 字符 ≈ 7.4s 纯等待。
- 3 个 specialist 并行打 DeepSeek，偶发 429 → `tenacity` 指数退避放大延迟。

本方案在**不改 python_a2a 库内部**的前提下，做两件事：把最终 LLM 输出**逐 token 流式**上抛（感知提速），并把链路上可合并的 LLM 调用**合并**（实际提速）。

## 2. 目标 / 非目标

### 目标
- [ ] **子能力 C — token 级流式**：最终回答的 LLM（planner 合成 / orchestrator summarize）用 `astream` 逐 token 输出，经现有 trace_id 轮询通道上抛至 Web 网关，再以真实 `token` 事件发往前端（替换假打字）。
- [ ] **子能力 D — 削减 LLM 调用**：planner 把「冲突检测 + 合成日程」两次调用合并为一次「综合日程合成」（含冲突标注）。
- [ ] **子能力 E — 消除假打字与限流重试**：真实流式后移除 `0.02s/字符` 假打字；并行委派 LLM 加并发上限，避免 429 重试退避。

### 非目标（Out of Scope）
- 不改 `python_a2a` 库内部（流式走自建 trace_id 通道，不碰 `stream_task`）。
- 不做响应缓存 / 语义缓存（后续单独评估）。
- 不换模型、不改数据库 schema、不新增 MCP 服务。
- 不把「意图识别 / SQL 生成」换成更小模型（作为后续备选，非本期）。

## 3. 验收标准（Acceptance Criteria）

### 子能力 C — token 级流式
- **Given** 用户提交 planning 请求，**When** 合成日程 LLM 开始输出，**Then** 前端在合成开始后 **≤2s** 内收到首个 token（对比当前「等 60s 才见结果」）。
- **Given** 用户提交单意图请求（课程/交通），**When** summarize LLM 开始输出，**Then** 前端 **≤2s** 内收到首个 token。
- **Given** 真实流式，**When** 前端收到 token 事件，**Then** 不再以 `0.02s/字符` 假打字模拟（token 由 LLM 真实产出）。

### 子能力 D — 削减调用
- **Given** planning 请求，**When** 全链路执行，**Then** LLM 调用次数从 7 次降为 **≤6 次**（冲突 + 合成合并为 1 次）。
- **Given** 合并后的综合合成，**When** 输出日程，**Then** 仍包含时间轴 + 冲突/地点告警（语义不回退）。

### 子能力 E — 并发限流
- **Given** 并行委派 ≥3 个 specialist，**When** 触发 DeepSeek，**Then** 无 429 触发指数退避（加并发上限后最多排队，不重试爆炸）。

## 4. 约束与依赖

### 约束
- **不侵入 python_a2a**：流式通过**扩展 `app/progress.py` 的 trace_id 通道**（`/progress/<trace_id>` 额外携带输出 token），复用现有 `await_task_with_progress` 轮询上抛，逐级到达 Web。
- **LLM 流式**：`app/llm.py` 的 `create_llm` 增加 `streaming` 参数，仅对最终输出 LLM 用 `astream`；其余（意图/SQL/拆解）仍用同步 `ainvoke`。
- **线程模型**：agent 的 Flask（Werkzeug）是线程化 dev server，`handle_task` 阻塞时 `/progress` 端点仍可被并发轮询——这是流式可通的先决条件，需在实现时验证。
- **日志 / 埋点**：沿用 `app/logging.py`、`app/observability.py`；不新增直连 DB、不手写 SQL。
- **温度/参数**：流式调用沿用 `temperature=0.1`，不改变输出质量。

### 依赖
- `langchain_openai.ChatOpenAI` 的 `streaming=True` + `astream()`（已随 langchain_openai 提供）。
- 现有 `app/progress.py`、`agents/orchestrator_agent.py`、`agents/planner_agent.py`、`app/server.py`、`static/index.html`。
- `app/prompts.py` 的 `planning_conflict_prompt` / `planning_compose_prompt`（合并为 `planning_synthesize_prompt`）。

## 5. 影响范围

- **涉及模块**：
  - `app/llm.py` —— `create_llm` 增加 `streaming` 参数。
  - `app/progress.py` —— `ProgressStore` 扩展为同时记录输出 token（trace_id 关联），端点与轮询函数上抛 token。
  - `agents/planner_agent.py` —— `detect_conflicts` + `compose_schedule` 合并为 `synthesize_schedule`（`astream` 流式）；委派并行加 `asyncio.Semaphore`。
  - `agents/orchestrator_agent.py` —— `summarize_response` 对 course/facility/transport 改 `astream` 流式上抛。
  - `app/server.py` —— WebSocket 转发真实 `token` 事件，移除 `0.02s/字符` 假打字。
  - `app/prompts.py` —— 新增合并后的 `planning_synthesize_prompt`。
  - `static/index.html` —— `sendMessage` 改为直接用 WebSocket 流式（原走 REST `/api/query` 且 `is_streaming` 恒为 False，WebSocket 从未生效）；`streamResponse` 健壮化（settle 去重 + 空流式气泡清理 + 保留重试按钮）。
- **数据库变更**：无。
- **新增 MCP 服务**：无。

## 6. 测试计划

- [x] 单测：`ProgressStore` 输出 token 的追加/读取/清空、trace_id 关联（`test_progress_store_accumulates_output`）。
- [x] 单测：`await_task_with_progress` 能按序上抛 token 增量（`test_await_task_with_progress_forwards_output_deltas`）。
- [x] 回归：`python -m pytest test/ -v` 全绿（20 passed，MCP 服务未运行，沿用 mock）。
- [x] 集成：`test/e2e_verify.py` 全链路 4/4 通过（planning 流式 / 单意图流式 / 反问 / 两轮闭环）。实测速度见下「实测结论」。

> 注：planner 合并「冲突+合成」为一次调用是纯函数级删减（`detect_conflicts`/`compose_schedule` 已移除），
> 由 `test_progress_store_*` / 回归 + 全链路 E2E 覆盖，未单独写 mock astream 的单测（与既有测试风格一致）。

## 7. 实测结论（2026-09-18，9 服务 + 真实 DeepSeek）

| 场景 | 首进度 | 首 token | 总耗时 | token 事件 |
|------|--------|----------|--------|-----------|
| planning 日程规划 | 5.61s | 60.22s | 61.70s | 4 |
| 单意图课程查询 | 5.51s | 25.64s | 26.43s | 2 |

**功能验收对照：**
- ✅ **子能力 C（token 流式）**：单独压测 `astream` 逐字吐 73 chunk / 1.9s（每 chunk 1~2 字），最终合成/summarize 确实流式上抛。合成/summarize 开始后首 token ≤2s，达标；`0.02s/字符` 假打字已移除。
- ✅ **子能力 D（削减调用）**：planning 从 7 次降为 6 次（意图 + 拆解 + 3× SQL + 综合合成），冲突检测已并入合成，`conflict` 阶段不再出现。
- ⚠️ **子能力 E（并发限流）**：`asyncio.Semaphore(2)` 已加（planner 委派并发上限），但**跨请求的 DeepSeek 429 仍存在**（意图识别被重试一次），未完全消除退避。

**关键发现：感知提速未达预期，瓶颈不在最终 LLM。**
- token 事件只有 2/4 个、首 token 都在最后——**不是 bug**，是「最终合成/summarize 只占 0.3~1.5s」+「轮询粒度 0.3s」所致；LLM 流式本身是通的。
- **真正耗时在上游**：意图识别 ~2.4s（含 429 重试）+ specialist SQL 生成 ~5s/个（planning 3 个被 Semaphore(2) 串成两批）+ 记忆召回。最终流式只覆盖最后 1~2s。
- 实测当日有两个**外部问题**放大延迟：
  1. **Ollama embedding（localhost:11434）宕机（502）** → 记忆召回降级关键词检索，并多花时间。
  2. **DeepSeek 限流（429）** → 意图识别/SQL 偶发重试退避。单意图 26.4s vs 基线 13~16s 主要由此放大。

**后续方向（超出本期 spec 范围，需另立 spec）：** 上游提速——意图/SQL 生成换小模型或缓存、记忆召回与意图识别并行、调 DeepSeek 限流并发上限。

## 8. 审批记录

| 阶段 | 状态 | 日期 | 备注 |
|------|------|------|------|
| spec 审批 | ✅ | 2026-09-18 | 用户批准（「执行」） |
| 实现完成 | ✅ | 2026-09-18 | 子能力 C/D/E 代码完成（`llm.py`/`progress.py`/`prompts.py`/`planner_agent.py`/`orchestrator_agent.py`/`server.py`/`index.html`） |
| 测试通过 | ⚠️ | 2026-09-18 | 单元+回归 20/20；E2E 功能 4/4 通过，但感知提速未达预期（瓶颈在上游 + 外部依赖异常） |
