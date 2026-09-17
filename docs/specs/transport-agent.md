---
title: 校巴/交通 Agent（TransportQueryAssistant）
status: approved      # draft → approved → in-progress → done
created: 2026-09-17
author: Piova
---

# 校巴/交通 Agent（TransportQueryAssistant）

## 1. 问题陈述（做什么，为什么）

当前系统覆盖课程 / 活动 / 新闻 / 餐厅 / 图书馆 / 天气，但缺少中大校园最高频的刚需——**校园交通（免费校巴）**。CUHK 校园面积 137.3 公顷、依山而建，校巴是学生日常通勤与「转堂」（课间 15 分钟）的必备工具，[交通处](https://www.transport.cuhk.edu.hk/sc/) 管理约 10 条路线（1/2/3/4/5/6A/6B/7/N/H 线）。

更重要的架构动因：现有 CourseQueryAssistant / FacilityQueryAssistant 两个 specialist 都是**同一种「检索型」**套路——「LLM 生成 SQL → MCP 查库 → 格式化」，这正是上一轮讨论中「两个 agent 没有区分性」的根因。交通 Agent 引入**「路线规划 + 时间窗判断」**（图搜索 + 发车推算），是第一个真正体现「非 SQL 判断逻辑」的 specialist，与现有 agent 形成类型差异。

## 2. 目标 / 非目标

### 目标
- [ ] 新增 2 张表 `bus_routes`（路线 + 首末班 + 发车间隔）/ `bus_stops`（站点序列），Alembic 迁移 `004`
- [ ] 新增 `mcp_servers/transport_server.py`（:8003），提供 `query_transport` / `get_transport_schema` / **`find_route`（图搜索路线规划）**
- [ ] 新增 `data/transport.py`——`TransportService`：SQL 查询 + schema + **`find_route` 图搜索算法**（可单测）
- [ ] 新增 `spiders/transport.py`——基线数据 + 定期校验（复用 `library.py` 的「baseline 常量」模式）
- [ ] 新增 `agents/transport_agent.py`（:5008）——A2A agent，区分「路线规划」与「时刻表查询」两类意图
- [ ] 路线规划走 `find_route`（判断逻辑），时刻表查询走 SQL + Python 推算「下一班车」
- [ ] orchestrator 注册 `transport` 意图 → TransportQueryAssistant

### 非目标（Out of Scope）
- 不做**实时 ETA**（CU Bus App 的到站预测）——仅静态时刻表 + 频次推算
- 不做**收费穿梭小巴**（「富贵巴」$5.5）的票价/班次精确查询
- 不做交通处网页 PDF/JS 的动态解析——用基线数据（同 `library.py`），标注「手动/定期校验」
- 不做用户定位、步行导航

## 3. 验收标准（Acceptance Criteria）

- **Given** 用户查询「从大学站到逸夫书院坐几号校巴」，**When** 交通 Agent 处理，**Then** 走 `find_route` 图搜索，返回候选路线（含路线编号 + 上车站 + 下车站 + 换乘点）
- **Given** 用户查询「N 线几点末班车」或「3 号线下一班几点」，**When** 交通 Agent 处理，**Then** 走 SQL 查询 + Python 频次推算，返回下一班/末班时间（已过末班则明确提示）
- **Given** 两个站点无直达、需换乘，**When** `find_route` 执行，**Then** 返回含换乘点的多段行程，且优先「最少换乘」其次「最少站数」
- **Given** 用户查询「大学站」与英文站名 `University Station`，**When** `find_route` 执行，**Then** 站点名归一化后命中同一站点
- **Given** 交通 Agent 收到任务且带 `_trace_id`，**When** 全链路执行，**Then** trace_id 经「orchestrator → transport agent → transport MCP → DB」连续（`db_execute_query` span 同 trace_id）
- **Given** transport 意图经 orchestrator 识别，**When** 下派，**Then** 路由到 TransportQueryAssistant 并聚合回答，回答质量与改造前其他意图一致
- **Given** 跑通现有 `test/`，**When** 执行，**Then** course / facility / orchestrator 无回归

## 4. 约束与依赖

### 约束
- **数据校验**：MCP 工具入参用 Pydantic 校验（`find_route` 的 origin/destination 非空、长度限制）
- **SQL 安全**：`query_transport` 复用 `app/security.validate_readonly_sql`，严禁字符串拼接；`find_route` 不用 SQL，直接走内存图搜索（无注入面）
- **日志**：统一 `app/logging.py` 的 `logger`，禁止 `print`
- **埋点**：复用 `app/observability.py` 的 `span` / `agent_llm_*` / `mcp_tool_*` / `db_query_duration_seconds`；`_meta` 传 trace_id（同 course/facility）
- **LLM**：走 `app/llm.py` 的 `create_llm()`，不直接实例化
- **端口**：Transport MCP = 8003（续 8001/8002），Transport Agent = 5008（续 5005/5006/5007）
- **Agent 无状态**：对话历史由调用方注入（同现有 specialist）

### 依赖
- `mcp` / `python-a2a` / `langchain_core` / `tenacity` / `mysql-connector-python`（均已在 `requirements.txt`）
- `app/config.py`（新增 `mcp_transport_url`）、`app/security.py`、`app/observability.py`
- `spiders/base.py`（`BaseSpider` 模板方法）
- Alembic（`migrations/`，当前 head = `003`）

## 5. 影响范围

- **新增**：
  - `mcp_servers/transport_server.py` —— Transport MCP（:8003）
  - `data/transport.py` —— `TransportService`（execute_query / get_all_schemas / find_route 图搜索 / 站名归一化）
  - `spiders/transport.py` —— 校巴基线数据爬虫
  - `agents/transport_agent.py` —— TransportQueryAssistant（:5008）
  - `migrations/versions/004_transport_tables.py` —— 2 张新表
- **修改**：
  - `app/config.py` —— 新增 `self.mcp_transport_url = os.getenv("MCP_TRANSPORT_URL", "http://127.0.0.1:8003/mcp")`
  - `agents/orchestrator_agent.py` —— `INTENT_AGENT_MAP` 增 `"transport"`、`AGENT_URLS` 增 `"TransportQueryAssistant"`、`agent_network.add(...)`、`summarize_response` 增 transport 分支
  - `app/prompts.py` —— `intent_prompt` 支持列表增 `transport` + 示例；新增 `summarize_transport_prompt()`
  - `app/server.py` —— `/api/sources` 增 `transport` 项
  - `docker-entrypoint.py` —— 增 Transport MCP(8003) + Transport Agent(5008) 启动与健康检查（在 orchestrator 之前）
  - `docker-compose.yml` —— 增 `MCP_TRANSPORT_URL` 环境变量
  - `README.md` / `CHANGELOG.md` —— 架构图、项目结构、端口表、意图路由表、版本条目
- **数据库变更**：新增 2 张表（`bus_routes` / `bus_stops`），Alembic 迁移 `004`
- **新增 MCP 服务**：`transport_server.py`

### 数据模型（2 张表）

```sql
bus_routes (
  id INT AUTO_INCREMENT PRIMARY KEY,
  route_code VARCHAR(10) NOT NULL COMMENT '路线编号(1/2/3/4/5/6A/6B/7/N/H)',
  route_name VARCHAR(100) COMMENT '路线名称',
  start_stop VARCHAR(100) COMMENT '起点站',
  end_stop VARCHAR(100) COMMENT '终点站',
  service_type VARCHAR(30) COMMENT '服务类型: regular/class_change/night/holiday',
  first_bus_time VARCHAR(10) COMMENT '首班车 HH:MM',
  last_bus_time VARCHAR(10) COMMENT '末班车 HH:MM',
  frequency_min INT COMMENT '发车间隔(分钟)',
  note VARCHAR(200) COMMENT '备注',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY unique_route (route_code)
)

bus_stops (
  id INT AUTO_INCREMENT PRIMARY KEY,
  route_code VARCHAR(10) NOT NULL,
  stop_order INT NOT NULL COMMENT '站点序号(升序)',
  stop_name VARCHAR(100) NOT NULL COMMENT '站点中文名',
  stop_name_en VARCHAR(100) COMMENT '站点英文名',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY unique_stop (route_code, stop_order)
)
```

### `find_route` 算法（判断逻辑核心）

#### 建图（每次调用时由 `bus_stops` 现算，不落库）

1. **加载**：`SELECT * FROM bus_stops`（约 150 行，亚毫秒级）
2. **分组排序**：按 `route_code` 分组，组内按 `stop_order` 升序
3. **连边**：同路线相邻两站连**双向**边（校巴往返都停），边权 = 1
4. **换乘点**：同一归一化站名出现在 ≥2 条路线 = 枢纽节点（无需额外标记，邻接表里多条出边即换乘）

#### 建图示例（3 条路线，展示换乘）

`bus_stops` 原始行：

| id | route_code | stop_order | stop_name | stop_name_en |
|----|-----------|-----------|-----------|--------------|
| 1 | 1 | 1 | 大學站 | University Station |
| 2 | 1 | 2 | 崇基書院 | Chung Chi College |
| 3 | 1 | 3 | 本部 | Central Campus |
| 4 | 3 | 1 | 本部 | Central Campus |
| 5 | 3 | 2 | 新亞書院 | New Asia College |
| 6 | 3 | 3 | 逸夫書院 | Shaw College |
| 7 | 2 | 1 | 大學站 | University Station |
| 8 | 2 | 2 | 聯合書院 | United College |
| 9 | 2 | 3 | 逸夫書院 | Shaw College |

分组排序 → 相邻连边：

```
1号线: 大學站 ↔ 崇基書院,  崇基書院 ↔ 本部
3号线: 本部 ↔ 新亞書院,    新亞書院 ↔ 逸夫書院
2号线: 大學站 ↔ 聯合書院,  聯合書院 ↔ 逸夫書院
```

「本部」同时出现在 1/3 号线、「大學站」出现在 1/2 号线、「逸夫書院」出现在 3/2 号线 → 换乘枢纽。归一化后得到内存邻接表：

```python
adj = {
    "university-station": [("chung-chi-college", "1"), ("united-college", "2")],
    "chung-chi-college":  [("university-station", "1"), ("central-campus", "1")],
    "central-campus":     [("chung-chi-college", "1"), ("new-asia-college", "3")],
    "new-asia-college":   [("central-campus", "3"), ("shaw-college", "3")],
    "shaw-college":       [("new-asia-college", "3"), ("united-college", "2")],
    "united-college":     [("university-station", "2"), ("shaw-college", "2")],
}
```

`find_route("大學站", "逸夫書院")` → Dijkstra：2号线直达（2 站，cost 2）胜过 1号线→本部换乘 3号线（4 站 + 1 换乘，cost 1004）。

#### 站名归一化

中文/英文/别名 → 统一 key，用模块级常量 `STOP_ALIASES`（规模小、静态，不进 DB）：
```python
STOP_ALIASES = {
    "大學站": "university-station", "大学站": "university-station",
    "University Station": "university-station",
    "本部": "central-campus", "Central Campus": "central-campus",
    ...
}
```

#### cost 模型与搜索

- **走一站（边权）= 1**：对「行程时间」的代理——2 表模型只存站点序列（`stop_order`），无分段时间数据，故用「站数」近似耗时（假定每段路等长）
- **换乘一次（惩罚）P = 1000**：代表等车 + 换乘不便；须满足 `P > 全网最大站数`（约 150 节点，1000 留足余量）
- **total_cost = Σ(站数) × 1 + Σ(换乘次数) × 1000**
- **用 Dijkstra**（最小化 total_cost）→ 自动「先最少换乘、再最少站数」；纯 BFS（每边 = 1）只会求最少站数，无法区分「直达 20 站」与「换乘 5 站」
- **可扩展**：将来给 `bus_stops` 加 `travel_min`（该段行驶分钟数）列，即可把边权从 1 换成真实分钟；图结构与算法骨架不变

#### 返回

候选行程 `[{route_code, board_stop, alight_stop, 站数}, ...]` + 换乘点列表

## 6. 测试计划

- [ ] 单测 `find_route`：直达 / 一次换乘 / 无路径 / 中英文站名归一化 / 最少换乘优先
- [ ] 单测「下一班车」推算：正常时段 / 跨末班车（返回「已过末班车」提示）
- [ ] 单测 `validate_readonly_sql`：`query_transport` 拒绝非 SELECT / 注入
- [ ] 回归：`python -m pytest test/ -v` 全绿，course / facility / orchestrator 无回归
- [ ] 集成：`docker compose up -d` 全栈，验证「从大学站到逸夫书院」路线规划 +「3 号线下一班」时刻查询；查 `logs/app.log` 确认 trace_id 连续

## 7. 审批记录

| 阶段 | 状态 | 日期 | 备注 |
|------|------|------|------|
| spec 审批 | ✅ | 2026-09-17 | 用户批准（"批准spec开工"） |
| 实现完成 | ⬜ | | |
| 测试通过 | ⬜ | | |
