---
title: 持久化分层记忆系统（Layered Persistent Memory）
status: done         # draft → approved → in-progress → done
created: 2026-08-15
author: Piova
---

# 持久化分层记忆系统（Layered Persistent Memory）

## 1. 问题陈述（做什么，为什么）

当前系统的「记忆」是**进程内 `sessions` 字典 + 对话历史序列化注入 prompt**（见 `app/server.py:110`），存在三个硬伤：

1. **不持久**：会话记忆存在内存 RAM 里，进程重启 / 多副本部署即全部丢失，无法跨会话、跨重启复用。
2. **窗口粗暴截断**：用「最近 N 行」硬切（意图识别 6 行、Agent 7 行，`server.py:278/372`），早期关键信息（如"我是 CS 专业学生"）被自然遗忘，且无摘要、无语义召回，**遗忘即永久**。
3. **无长期记忆**：用户偏好、身份、历史事实每次都要重新问，无法"记住"用户。

本方案引入一套**自研的持久化分层记忆系统**：把记忆按生命周期拆成工作 / 情景 / 摘要 / 语义四层，落 MySQL 持久化，并通过「混合检索 + 滚动摘要 + 语义召回」在每次请求时组装出 token 预算内的上下文注入现有 prompt，**在不大改 A2A Agent / MCP 架构的前提下，把"金鱼记忆"升级为"分层长期记忆"**。

### 四层记忆的层级关系（重要澄清）

四层**不是平级的四份独立数据**，而是「一份原料 + 三种提炼形态」：

```
        conversation_messages（Episodic 存储底座 —— 原料库，落库持久化）
                        │
        ┌───────────────┼────────────────┐
        │ 切片           │ 压缩            │ 提炼
        │ (最近 N 条)    │ (超窗旧消息)     │ (抽取事实/偏好)
        ▼               ▼                ▼
     Working         Summary          Semantic
   (直接进prompt)  (直接进prompt)   (向量化后按需检索进prompt)
```

- **Episodic（情景记忆）**：所有对话消息落 `conversation_messages`，是持久化底座，保证「重启不丢」；它不直接进 prompt，而是被下面三层以三种方式消费。
- **Working（工作记忆）**：Episodic 的「最近切片」，直接进 prompt。
- **Summary（摘要记忆）**：Episodic 中「超窗旧消息」经 LLM 压缩，进 prompt。
- **Semantic（语义记忆）**：从对话中「提炼」的跨会话事实/偏好，向量化后按需检索进 prompt。

这一划分对应 MemGPT/Letta 的 core memory（Working/Summary/Semantic，常驻或按需）与 archival memory（Episodic，全量落库）之分。

## 2. 目标 / 非目标

### 目标
- [x] 新增独立 `app/memory.py` 模块，封装 `MemoryManager`，对外提供 `recall()`（召回上下文）与 `save()`（写入记忆）两个核心接口
- [x] 持久化会话消息（情景记忆）到 MySQL，进程重启后记忆不丢
- [x] 滚动摘要：对话超窗后由 LLM 压缩旧对话，控制 token 不无限增长
- [x] 语义记忆：从对话中抽取长期事实 / 偏好，用本地 embedding 向量化，支持跨会话语义召回
- [x] 混合检索：关键词（BM25/FULLTEXT）+ 向量语义两路召回，用 RRF（Reciprocal Rank Fusion）融合排序
- [x] 长期记忆去重与更新：同一事实 / 偏好的再次提及做合并更新，不重复存储
- [x] 替换 `server.py` 中 `sessions` 字典与 `history_text` 构建逻辑，Agent 层 / MCP 层零改动
- [x] 全部 DB 操作用参数化查询，通过 Alembic 迁移建表

### 非目标（Out of Scope）
- 不引入独立向量数据库（Milvus / Chroma / pgvector）——数据量小，用「内存余弦 + 可替换的检索接口」实现，规模上来后再换后端
- 不引入 Mem0 / LangGraph / Zep 等第三方 memory 框架——自研，保证可控与可讲清原理
- 不改 A2A Agent 层、MCP Server 层的协议与实现（它们保持 stateless，历史仍由 Web 层组装注入）
- 不做完整多用户鉴权体系——先按 `session_id` 隔离，表结构预留 `user_id` 字段
- 不做记忆的到期删除 / 遗忘曲线等高级策略——先做 `access_count + recency` 权重，不做到期清理

## 3. 验收标准（Acceptance Criteria）

- **Given** 一个 session 已有多轮对话，**When** Web 服务重启，**Then** 该 session 的历史消息与摘要仍可从 MySQL 读出（持久化生效）
- **Given** 对话轮数超过摘要触发阈值，**When** 继续对话，**Then** 旧对话被压缩为滚动摘要、注入 prompt 的上下文 token 数不超过预算上限
- **Given** 用户在若干轮前说过"我是 CS 专业学生"，**When** 后续跨会话问"帮我推荐课程"，**Then** 语义记忆召回该事实并出现在注入上下文中（跨会话长期记忆生效）
- **Given** 用户重复表达同一偏好（如两次说"喜欢靠窗座位"），**When** 记忆写入，**Then** 长期记忆表只保留一条合并后的记录（去重生效）
- **Given** 一个同时命中关键词与语义的查询，**When** 执行召回，**Then** 两路结果经 RRF 融合后排序，关键词命中与语义相关项都能进入 top-K
- **Given** 一个普通课程查询，**When** 走完整 `process_query_stream` 流程，**Then** Agent 层与 MCP 层代码无改动、原查询功能回归通过
- **Given** 任意带特殊字符的用户输入，**When** 写入记忆，**Then** DB 写操作使用参数化查询、无 SQL 拼接（注入安全）

## 4. 约束与依赖

### 约束
- **本地 embedding**：DeepSeek 无公开 embedding 接口，采用本地 Ollama 的 `bge-m3` 模型（1024 维 dense 向量，中英多语言），经 Ollama `/api/embed`（批量）或 OpenAI 兼容 `/v1/embeddings` 调用，离线、免费、数据不出域；已知 `bge-m3` 对个别超长/技术文本可能返回 NaN，召回层做容错降级为关键词召回，备选模型 `nomic-embed-text`
- **少改架构**：Agent / MCP 层零改动；改动集中在 `app/memory.py`（新增）、`app/config.py`（加配置）、`app/server.py`（替换 session 逻辑）、一个 Alembic 迁移文件
- **参数化查询**：所有 SQL 走 `%s` 占位符（项目编码规范），embedding 存 BLOB（`numpy.float32.tobytes()`，1024 维约 4KB/条）
- **检索可替换**：向量检索封装成独立接口，当前用内存余弦暴力计算（数据量 < 1 万条，< 5ms），后续可无缝替换为向量库而不改调用方
- **非阻塞**：embedding 计算与 LLM 摘要 / 抽取放异步路径，不得阻塞主查询链路；召回阶段允许降级（embedding 失败则仅关键词召回）

### 依赖
- Python 标准库 + `numpy`（余弦）+ 本地 Ollama 服务（`bge-m3`，经 HTTP 调用，无 torch 重依赖）
- 现有 `mysql.connector` + Alembic（沿用项目既有工程规范）
- 复用 `app/llm.py` 的 `create_llm()` 做摘要与长期记忆抽取的 LLM 调用
- 复用 `app/logging.py`、`app/observability.py`（新增记忆读写埋点）

## 5. 影响范围

- **涉及模块**：
  - 新增 `app/memory.py` —— `MemoryManager` + 四层记忆实现 + embedding 客户端 + 混合检索
  - `app/config.py` —— 新增 memory 配置项（embedding 模型、窗口 token 预算、top-K、摘要触发阈值、去重阈值）
  - `app/server.py` —— `sessions` 字典替换为 `MemoryManager`；`process_query_stream` 的 `history_text` 构建改为 `recall()`；`recognize_intent` / `call_agent` 的上下文改为召回结果；三个 session API 改为走持久化
- **数据库变更**：**是**，新增一个 Alembic 迁移，建 3 张表：
  1. `conversation_messages`（情景记忆）——`id, session_id, user_id(NULLABLE), role, content, created_at`，索引 `(session_id, id)`
  2. `conversation_summaries`（摘要记忆）——`id, session_id, summary, start_turn, end_turn, updated_at`
  3. `long_term_memories`（语义记忆）——`id, session_id, user_id(NULLABLE), content, embedding(BLOB), category, importance, access_count, last_accessed_at, created_at`
- **新增 MCP 服务**：无（不改 MCP 协议，不新增 `*_server.py`）
- **依赖变更**：无新增 Python 重依赖（HTTP 调 Ollama，复用现有 `langchain_openai` 的 `OpenAIEmbeddings` 指向 `/v1` 端点，或直接 `httpx` 调 `/api/embed`）；需本地 Ollama 拉取 `bge-m3`（`ollama pull bge-m3`，约 1.2GB）
- **部署配置变更**（Docker 测试中暴露并补全）：
  - `app/config.py` 新增 `DB_PORT` 配置项（默认 3306，环境变量 `DB_PORT` 覆盖）——原连接无 port 参数，无法连 Docker 映射到 3308 的 MySQL
  - `app/memory.py`、`data/database.py`、`migrations/env.py` 连接时统一使用 `conf.port`
  - `docker-compose.yml` app 服务新增 `EMBEDDING_BASE_URL=http://host.docker.internal:11434`（Ollama 跑在宿主机，容器内经 host 网关访问）

## 6. 测试计划

- [x] 单元测试：`MemoryManager.save()` 落库、`recall()` 组装上下文、滚动摘要触发与覆盖、语义去重与更新
- [x] 检索测试：混合检索 + RRF 融合排序正确；embedding 失败时降级为关键词召回
- [x] 持久化测试：写入后新建 `MemoryManager` 实例（模拟重启）仍能召回
- [x] 注入安全测试：特殊字符输入走参数化查询，无拼接
- [x] 回归测试：跑通 `test/` 现有用例，确认 Agent / MCP 链路无回归

## 7. 审批记录

| 阶段 | 状态 | 日期 | 备注 |
|------|------|------|------|
| spec 审批 | ✅ | 2026-08-15 | 用户批准（自研分层记忆 + 本地 Ollama bge-m3） |
| 实现完成 | ✅ | 2026-08-15 | 四层记忆 + 混合检索 + 003 迁移 + server 接入 + DB_PORT |
| 测试通过 | ✅ | 2026-08-15 | 11 单元测试 + benchmark + Docker 全栈 E2E 全通过 |

## 8. 实现与验证结果（2026-08-15）

### 8.1 交付清单

| 文件 | 说明 |
|------|------|
| `app/memory.py` | `MemoryManager`（四层记忆）+ `OllamaEmbedder`（bge-m3 HTTP 客户端）+ 混合检索（RRF） |
| `migrations/versions/003_memory_tables.py` | 建 3 张记忆表（幂等 `CREATE TABLE IF NOT EXISTS`） |
| `app/config.py` | memory 配置 + `DB_PORT` |
| `app/server.py` | `sessions` 字典 → `MemoryManager`，`recall()` 替换硬截断 |
| `data/database.py` / `migrations/env.py` | 连接统一使用 `conf.port` |
| `requirements.txt` | 新增 `numpy` |
| `test/test_memory.py` | 11 个单元测试 |
| `scripts/benchmark_memory.py` | 端到端 benchmark（产出量化参数） |
| `docker-compose.yml` | app 服务补 `EMBEDDING_BASE_URL` |

### 8.2 单元测试

`python -m pytest test/test_memory.py -v` → **11 passed**：RRF 融合排序、余弦 top-k、关键词参数化、token 截断、序列化往返、去重合并/新增、recall 组装、save 参数化防注入、clear 保留长期记忆。

### 8.3 Benchmark 量化参数（真实 MySQL 8.0 + Ollama bge-m3）

| 类别 | 指标 | 实测值 |
|------|------|--------|
| 性能 | embedding 单条 / 批量均摊 | 723ms / ~40ms·条⁻¹ |
| 性能 | 落库 INSERT / 吞吐 | 13ms / ~76 条·s⁻¹ |
| 性能 | recall 全链路 / 纯检索逻辑 | 778ms / 16ms |
| 检索 | 向量 Hit@1 / Hit@5 / MRR | 56% / **100%** / 0.78 |
| 检索 | 关键词 Hit@5（专名型 query） | 50%（兜底课程号/人名） |
| 检索 | RRF 融合 Hit@5 | **100%** |
| 去重 | 重复事实相似度 | 0.86–0.99（新事实最高 0.74，不误合并） |
| 去重 | 阈值 0.85 去重率 | **100%**（零误合并） |
| 存储 | 单条 embedding BLOB | 4KB（1024×float32） |

> 检索质量结论：bge-m3 向量在 40 条小库下 Hit@5 已满分，RRF 相对向量无增益；其价值在于关键词路对专有名词（课程号/人名）的兜底召回、embedding 降级时的鲁棒性，以及库规模化后对罕见 token 的精确召回。

### 8.4 Docker 全栈 E2E（完整项目在容器内测试）

- `docker compose up -d` 拉起 `mysql` + `app`，两容器 healthy；entrypoint 依次拉起 MCP×2 → A2A Agent×2 → Web
- entrypoint 容器内自动跑 Alembic 迁移 → `alembic_version=003`，3 张记忆表齐全
- **跨容器 embedding 打通**：容器内经 `host.docker.internal:11434` 访问宿主机 Ollama bge-m3，`[Memory] embedding 模型已预热`
- 端到端验证：`save` 落库 → `recall` 语义召回（「CSCI2100 是什么课」top1 命中「用户主修课程包括 CSCI2100 数据结构」）→ `consolidate` LLM 抽取 2 条事实、1 条去重合并 + 1 条新落库
- Web API：`/health` 4 组件 ok、`/api/history` 读取落库消息（含 timestamp）、`/api/query` 返回 200 且对话自动落库
