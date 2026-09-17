---
title: SQL 只读校验白名单（防注入）
status: draft        # draft → approved → in-progress → done
created: 2026-02-04
author: Piova
---

# SQL 只读校验白名单（防注入）

## 1. 问题陈述（做什么，为什么）

FacilityQueryAssistant 通过 LLM 把用户自然语言生成为 SQL，再经 MCP 工具 `query_facilities` 在 MySQL 上真实执行。由于 SQL 由 LLM 生成、且最终会落库执行，存在两类风险：

1. **注入风险**：恶意或诱导性输入可能让 LLM 生成 `DROP TABLE` / `DELETE` / 堆叠查询（`SELECT ...; DROP ...`）等破坏性语句。
2. **误操作风险**：即使非恶意，LLM 也可能"幻觉"出写操作，误改数据。

本场景是纯只读查询（查活动 / 新闻 / 餐厅 / 图书馆开放时间），本不需要任何写操作。因此在「LLM 生成 SQL」与「数据库执行」之间加一道**强制只读校验闸门**：任何非 SELECT、或含危险关键字的语句，在执行前被拦截。

## 2. 目标 / 非目标

### 目标
- [ ] 提供 `validate_readonly_sql(sql)` 校验函数，在 `execute_query()` 执行前强制调用
- [ ] 只放行以 `SELECT` 开头的只读查询（忽略前导空白、大小写不敏感）
- [ ] 拦截所有 DDL/DML 危险关键字（DROP / DELETE / UPDATE / INSERT / ALTER / ...）
- [ ] 阻止堆叠查询（禁止分号）
- [ ] 避免误杀：字符串字面量中含危险关键字（如 `SELECT 'DROP TABLE' AS msg`）不被误判

### 非目标（Out of Scope）
- 不覆盖所有 SQL 注入变种（UNION 注入、布尔盲注、时间盲注等）——黑名单是**纵深防御的一层**，不是注入防护的完备解
- 不做参数化查询 / ORM 改造（那是根治手段，超出本次范围）
- 不做权限分级、审计日志

## 3. 验收标准（Acceptance Criteria）

- **Given** SQL 为 `SELECT id, name FROM canteen WHERE status='Open'`，**When** 调用 `validate_readonly_sql`，**Then** 原样返回该 SQL、不抛异常
- **Given** SQL 为 `DROP TABLE canteen`，**When** 调用校验，**Then** 抛 `ValueError`（不以 SELECT 开头）
- **Given** SQL 为 `SELECT * FROM canteen; DROP TABLE canteen`，**When** 调用校验，**Then** 抛 `ValueError`（含分号，堆叠查询）
- **Given** SQL 为 `SELECT 'DROP TABLE' AS msg FROM canteen`，**When** 调用校验，**Then** 放行（字符串字面量中的关键字不误判）
- **Given** SQL 为空字符串或非字符串（如 `None`），**When** 调用校验，**Then** 抛 `ValueError`
- **Given** SQL 为 `  select * from library_hours`（前导空白 + 小写），**When** 调用校验，**Then** 放行（忽略前导空白、大小写不敏感）

## 4. 约束与依赖

### 约束
- 仅允许只读 SELECT
- 校验是纯字符串 / 正则操作，单次耗时 < 1ms，不得影响查询延迟
- 大小写不敏感、容忍前导空白（LLM 输出格式不稳定，需容错）

### 依赖
- 无外部依赖，仅用 Python 标准库 `re`
- 依赖 `data/database.py` 的 `execute_query()` 在 SQL 执行前调用本校验

## 5. 影响范围

- **涉及模块**：`app/security.py`（新增校验逻辑）、`data/database.py`（`execute_query` 调用点）
- **数据库变更**：无
- **新增 MCP 服务**：无（校验发生在 MCP Server 侧的数据库访问层，不改协议）

## 6. 测试计划

- [ ] 单元测试：合法 SELECT 放行；DROP / DELETE / UPDATE / INSERT / ALTER 各关键字拒绝；分号堆叠拒绝
- [ ] 边界测试：空 SQL、非字符串、前导空白、全小写、引号内关键字、转义引号（`\'`）
- [ ] 集成测试：LLM 生成 SQL → MCP `query_facilities` → `execute_query` 全链路，验证恶意 SQL 在落库前被拦截

## 7. 审批记录

| 阶段 | 状态 | 日期 | 备注 |
|------|------|------|------|
| spec 审批 | ⬜ | | |
| 实现完成 | ⬜ | | |
| 测试通过 | ⬜ | | |
