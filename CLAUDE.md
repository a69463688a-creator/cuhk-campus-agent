# SmartCampus — CUHK 校园生活助手

## 项目概述
基于 MCP + A2A 协议的智能校园服务聚合平台，集成天气、设施、课程、票务等校园服务。

## 技术栈
- Python 3.12, FastAPI, uvicorn
- Conda 环境: `lang_env`
- 数据库: MySQL + Alembic 迁移
- LLM: LangChain + OpenAI-compatible API
- 协议: MCP (Model Context Protocol), A2A (Agent-to-Agent)

## 项目结构
```
app/          — 核心应用（server.py 主入口, cli.py, config.py）
mcp_servers/  — MCP 服务器（天气、课程、设施、票务等）
agents/       — A2A Agent 定义
spiders/      — 数据爬虫模块
test/         — 测试文件
migrations/   — Alembic 数据库迁移
logs/         — 日志目录
```

## 常用命令
```bash
# 启动 Web 服务
conda run -n lang_env python run_web.py

# 启动 CLI
conda run -n lang_env python run_cli.py

# 运行爬虫
conda run -n lang_env python run_spiders.py

# 运行测试
conda run -n lang_env python -m pytest test/ -v --tb=short

# 数据库迁移
conda run -n lang_env alembic upgrade head

# 启动单个 MCP 服务（示例）
PYTHONPATH=. conda run -n lang_env python mcp_servers/course_server.py
```

## 编码规范
- 使用 Pydantic 做数据校验，不要手写校验逻辑
- 日志统一通过 `app/logging.py` 配置，不要直接用 `print`
- 数据库操作使用参数化查询，严禁字符串拼接 SQL
- MCP 服务器返回标准 JSON-RPC 格式
- 新增 MCP 服务放在 `mcp_servers/` 下，命名规范: `*_server.py`

## 注意事项
- `observability.py` 中的 tracing/metrics 依赖全局初始化，不要在模块顶层调用
- 测试需要 MCP 服务未运行（测试内自行启动 mock），别在跑测试前手动启动服务
- LLM 调用走 `app/llm.py` 的工厂方法，不要直接实例化
- `security.py` 中的输入过滤是中间件层的，别在业务代码里重复做

## 开发流程约定（Spec 工作流）
- 新功能、模块改造、接入新数据源、涉及数据库迁移的需求，**先写 spec 再写代码**
- spec 放在 `docs/specs/<feature-slug>.md`，模板见 `docs/specs/TEMPLATE.md`
- 写完 spec 后**必须停下来征得用户审批**，未批准不得开始实现
- 实现过程中若需偏离 spec，先更新 spec 文档并再次征得批准
- 实现完成后对照 spec 的验收标准逐条核对
