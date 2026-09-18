---
title: 上游链路提速（限流治理 + 意图/SQL 提速 + 记忆召回）
status: done  # draft → approved → in-progress → done
created: 2026-09-18
author: Piova
---

# 上游链路提速（限流治理 + 意图/SQL 提速 + 记忆召回）

## 1. 问题陈述（做什么，为什么）

上一期（`llm-latency-optimization`）把最终输出 LLM 改成 token 级流式后，实测发现**最终合成/summarize 只占全链路 0.3~1.5s**，瓶颈全在上游。Ollama embedding 恢复后的干净基线（2026-09-18 实测，9 服务 + 真实 DeepSeek）：

| 场景 | 总耗时 | 上游分解 |
|------|--------|----------|
| 单意图课程 | 21.11s | 记忆召回 ~5s + 意图识别 1.7~10s + SQL 生成 ~4.7s + summarize 0.3s |
| planning 日程 | 43.85s | 意图 ~10s（含重试）+ 拆解 + 3× SQL（~15s）+ 合成 1.5s |

三大上游瓶颈（日志实证）：
1. **DeepSeek 429 限流**：意图识别几乎每次触发重试（`Retrying request ... in 0.4s`），指数退避 min 1s 放大延迟。planning 一次 6 次 LLM 调用（意图+拆解+3×SQL+合成）挤爆限流窗口，导致下一个请求的首个调用也被 429。
2. **SQL 生成 / 意图识别慢**：每次 ~4.7s / 1.7~10s，且无缓存——相同课程代码重复查询也要重新生成 SQL。
3. **记忆召回 ~5s**：日志频繁出现 `[Memory] MySQL 连接已断开，正在重连`；召回串行多轮 MySQL + embed，新会话（无长期记忆）也走完整 embedding 检索路径。

## 2. 目标 / 非目标

### 目标
- [ ] **子能力 A — 限流治理**：消除 DeepSeek 429 触发指数退避（全局节流 + 429 快速重试 + 减少总调用）。
- [ ] **子能力 B — 意图/SQL 提速**：意图识别与 SQL 生成换更小/更快模型（若 API 提供）+ 结果缓存（相同查询命中缓存，不再调 LLM）。
- [ ] **子能力 C — 记忆召回提速**：修复 MySQL 断连重连、减少召回串行往返、无长期记忆时走跳过 embed 的快速路径。

### 非目标（Out of Scope）
- 不改最终输出 LLM（合成/summarize 已 token 级流式，质量不回退）。
- 不改数据库 schema、不新增 MCP 服务。
- 不做响应级语义缓存（缓存最终答案）——后续单独评估。
- 不引入跨进程限流协调（Redis/外部锁）——本期仅进程内节流 + 降低并发。

## 3. 验收标准（Acceptance Criteria）

### 子能力 A — 限流治理
- **Given** 连续多个请求（含 planning 并行委派），**When** 触发 DeepSeek，**Then** 无 429 触发指数退避（日志无 `Retrying`，或退避总时长 ≤1s）。
- **Given** 单意图请求，**When** 意图识别，**Then** 首调即成功、无重试。

### 子能力 B — 意图/SQL 提速
- **Given** 单意图课程查询（冷，无缓存），**When** 全链路，**Then** 意图识别 + SQL 生成合计 ≤3s（当前 ~6.4s）。
- **Given** 相同课程代码/意图的重复查询（热），**When** 触发 SQL 生成/意图识别，**Then** 命中缓存、不再调用 LLM（LLM 调用计数不增）。

### 子能力 C — 记忆召回提速
- **Given** 新会话（无长期记忆）请求，**When** 召回记忆，**Then** ≤1s（当前 ~5s，跳过 embed + 减少 MySQL 往返）。
- **Given** 正常会话请求，**When** 召回，**Then** 无 `MySQL 连接已断开` 告警。

### 总体
- **Given** 单意图课程请求，**When** 全链路，**Then** 总耗时 ≤12s（当前 21.11s）。
- **Given** planning 日程请求，**When** 全链路，**Then** 总耗时 ≤35s（当前 43.85s）。

## 4. 约束与依赖

- **不侵入 python_a2a**：与上期一致，进度/流式仍走自建 trace_id 通道。
- **LLM 工厂**：`app/llm.py` 的 `create_llm` 支持指定 `model`（新增可选参数），意图/SQL 用更小模型时只改调用点，不散落硬编码。
- **限流**：进程内节流（如模块级 `asyncio.Semaphore` 或令牌桶），不依赖外部协调；429 重试策略从指数退避改为快速固定重试。
- **缓存**：进程内 LRU（`functools.lru_cache` 或 dict + TTL），键为归一化后的 query/意图，值为 SQL 字符串/意图结果；SQL 缓存键必须与 schema 版本绑定（schema 缓存 TTL 1h，见 `course_agent._SCHEMA_TTL`）。
- **记忆**：`app/memory.py` 的 `OllamaEmbedder` / `MemoryManager.recall` 为改造点；MySQL 连接复用与重连逻辑沿用现有 `_ensure_connection`，修复其重连时机。
- **模型可用性**：`deepseek-v4-flash` 是否已是该 API 最小模型需在实现时确认（查 `/models` 端点）；若无更小模型，子能力 B 的「换模型」降级为「仅缓存 + prompt 精简」。

## 5. 影响范围

- **涉及模块**：
  - `app/llm.py` —— `create_llm` 增加 `model` 可选参数。
  - `agents/orchestrator_agent.py` —— 意图识别改用更小模型 + 结果缓存 + 429 快速重试。
  - `agents/course_agent.py` / `facility_agent.py` / `transport_agent.py` —— SQL 生成改用更小模型 + SQL 缓存 + 429 快速重试。
  - `agents/planner_agent.py` —— 拆解/合成调用处同步限流策略（沿用 Semaphore，视限流调整）。
  - `app/memory.py` —— 召回快速路径（无长期记忆跳过 embed）、修复 MySQL 重连、减少串行往返。
- **数据库变更**：无。
- **新增 MCP 服务**：无。

## 6. 测试计划

- [ ] 单测：SQL 缓存命中（相同 query 不再调 LLM）、缓存键含 schema 版本、归一化键。
- [ ] 单测：意图识别缓存命中。
- [ ] 单测：记忆召回快速路径（无长期记忆时跳过 embed）。
- [ ] 回归：`python -m pytest test/ -v` 全绿。
- [ ] 集成：`test/e2e_verify.py` 全链路，验证（1）单意图 ≤12s / planning ≤35s；（2）日志无 `Retrying`；（3）重复查询命中缓存（LLM 调用计数不增）。

## 7. 审批记录

| 阶段 | 状态 | 日期 | 备注 |
|------|------|------|------|
| spec 审批 | ✅ | 2026-09-18 | 用户批准（"批准"） |
| 实现完成 | ✅ | 2026-09-18 | 子能力 A/B/C 全部落地 |
| 测试通过 | ⚠️ | 2026-09-18 | A/B/C 通过；总体 ≤12s/≤35s 未达成（见 §8） |

## 8. 实测结论（2026-09-18，9 服务 + 真实 DeepSeek）

### 通过项（子能力 A / B / C）
- **A 限流治理 ✅**：全部 6 个进程日志 `Retrying` 计数为 **0**，429 指数退避彻底消除（`wait_fixed(0.5)` + `max_retries=1` 生效）。意图识别首调即成功、无重试。
- **B 缓存 ✅**：SQL/意图/交通意图解析均接入 `functools.lru_cache`。实测相同课程代码重复查询（run1/run2）**SQL 生成 0 次 LLM 调用**（日志同时间戳直接命中缓存，无 deepseek POST）。“换更小模型”降级为“仅缓存”——API 仅提供 `deepseek-flash` / `deepseek-v4-pro`，均为 fast 档，无更小模型。
- **B 缓存（后续）— 实体归一化 key ✅**：原始 `lru_cache` 键为整段 `conversation`，表述不同即 miss。已升级为：course SQL 按**课程代码**归一化（`CSCI2100` 正则，单一代码才归一化，多/无则回退原始串），transport 时刻表按**路线号**归一化（加「班次关键词 + 非路线规划」守卫）。实测 3 种不同表述（"上课时间和教室"/"在哪个教室上课"/"授课老师是谁"）命中同一缓存条目（run1/run2 无 deepseek POST）；transport 两个不同表述的「3号线」查询共享缓存、路线规划不受影响。**facility 未做**：实体→SQL 映射依赖意图（"大学图书馆开门吗"是 library_hours、"大学图书馆附近吃什么"是 canteen），意图本身就是 LLM 输出，正则无法安全归一化。
- **C 记忆召回 ✅**：web 日志 `MySQL 连接已断开/不可用` 告警计数 **0**（`ping(reconnect=True)` 修复静默重连）；新会话召回首进度 ~0.5s（无长期记忆时跳过 embed 的快速路径已实现，但当前库非空无法实测该分支）。

### 未达成项（总体目标）
| 场景 | 目标 | 实测 | 结论 |
|------|------|------|------|
| 单意图课程 | ≤12s | 13.4s / 15~25s（多次） | ❌ 超 |
| planning 日程 | ≤35s | 50.7s / 61.6s | ❌ 超 |

### 根因：DeepSeek API 延迟主导，代码层已无杠杆
- 单次 LLM 调用实测 **3~23s**（transport 路线意图一次 23.5s，course SQL ~4.8s，summarize 5~20s），且抖动极大。
- 单意图链路最少仍含 3 次 LLM（意图 + SQL + summarize），planning 含 6 次（意图 + 拆解 + 3×SQL + 合成）。
- 缓存只覆盖「意图/SQL」两层；最终 summarize（流式，质量不回退）与拆解/合成仍在每轮调 LLM，无法缓存。
- 结论：≤12s/≤35s 需靠**减少 LLM 调用次数**（如意图+拆解合并、简单查询跳过 summarize）或**响应级缓存**（本 spec 明确 out of scope），属后续决策，本期未做。
