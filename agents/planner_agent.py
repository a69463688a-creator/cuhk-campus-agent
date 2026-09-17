#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: planner_agent.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/9/17
描述: 日程规划 Agent（PlannerAgent）—— 端口 5009

A2A 双角色：
  - server：接收 OrchestratorAgent 下派的「planning」任务
  - client：并行委派 Course / Facility / Transport 三个 specialist

四步算法：拆解 → 并行委派 → 冲突判断 → 合成日程。
与 orchestrator 的区别：输出「带时间轴 + 冲突告警」的日程，而非并列拼接。
"""
import json
import asyncio
import time
import re
import uuid

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from python_a2a import (
    A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState,
    AgentNetwork, Message, TextContent, MessageRole, Task,
)

from app.config import Config
from app.logging import logger
from app.llm import create_llm
from app.prompts import SmartCampusPrompts
from app.a2a_types import AgentResult, status_message_text
from app.progress import (
    progress_store, register_progress_endpoint, await_task_with_progress,
    STAGE_DECOMPOSE, STAGE_DELEGATE, STAGE_CONFLICT, STAGE_COMPOSE,
)
from app.observability import (
    span, set_trace_id, get_trace_id,
    a2a_agent_calls_total, a2a_agent_call_duration_seconds,
    agent_llm_calls_total, agent_llm_duration_seconds,
)

conf = Config()
llm = create_llm()

# 子任务 intent → specialist agent（与 orchestrator 的 INTENT_AGENT_MAP 对齐，但不含 planner 自身）
PLANNER_SPECIALISTS = {
    "course": "CourseQueryAssistant",
    "campus_event": "FacilityQueryAssistant",
    "campus_news": "FacilityQueryAssistant",
    "canteen": "FacilityQueryAssistant",
    "library_hours": "FacilityQueryAssistant",
    "transport": "TransportQueryAssistant",
}

AGENT_URLS = {
    "CourseQueryAssistant": "http://localhost:5005",
    "FacilityQueryAssistant": "http://localhost:5006",
    "TransportQueryAssistant": "http://localhost:5008",
}

specialist_network = AgentNetwork(name="CUHK Campus Planner Specialist Network")
for name, url in AGENT_URLS.items():
    specialist_network.add(name, url)


def _strip_json(s: str) -> str:
    return re.sub(r'^```json\s*|\s*```$', '', s.strip()).strip()


# ============ 第一步：拆解 ============
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((Exception,)),
    before_sleep=lambda rs: logger.warning(f"LLM 拆解重试 {rs.attempt_number}/3..."),
)
async def decompose_goal(conversation: str) -> list:
    chain = SmartCampusPrompts.planning_decompose_prompt() | llm
    start = time.perf_counter()
    status = "ok"
    try:
        with span("llm_planning_decompose"):
            out = (await chain.ainvoke({"conversation": conversation})).content.strip()
            out = _strip_json(out)
            logger.info(f"拆解: {out}")
            return json.loads(out).get("subtasks", [])
    except Exception:
        status = "error"
        raise
    finally:
        agent_llm_duration_seconds.labels(agent_name="PlannerAgent").observe(time.perf_counter() - start)
        agent_llm_calls_total.labels(agent_name="PlannerAgent", status=status).inc()


# ============ 第三步：冲突判断 ============
async def detect_conflicts(conversation: str, subtasks: list, results: list) -> str:
    chain = SmartCampusPrompts.planning_conflict_prompt() | llm
    start = time.perf_counter()
    with span("llm_planning_conflict"):
        out = (await chain.ainvoke({
            "conversation": conversation,
            "subtasks": json.dumps(subtasks, ensure_ascii=False),
            "results": json.dumps(results, ensure_ascii=False),
        })).content.strip()
    agent_llm_duration_seconds.labels(agent_name="PlannerAgent").observe(time.perf_counter() - start)
    agent_llm_calls_total.labels(agent_name="PlannerAgent", status="ok").inc()
    return out


# ============ 第四步：合成日程 ============
async def compose_schedule(conversation: str, subtasks: list, results: list, conflicts: str) -> str:
    chain = SmartCampusPrompts.planning_compose_prompt() | llm
    start = time.perf_counter()
    with span("llm_planning_compose"):
        out = (await chain.ainvoke({
            "conversation": conversation,
            "subtasks": json.dumps(subtasks, ensure_ascii=False),
            "results": json.dumps(results, ensure_ascii=False),
            "conflicts": conflicts,
        })).content.strip()
    agent_llm_duration_seconds.labels(agent_name="PlannerAgent").observe(time.perf_counter() - start)
    agent_llm_calls_total.labels(agent_name="PlannerAgent", status="ok").inc()
    return out


# ============ Specialist 委派 ============
@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((Exception,)),
    before_sleep=lambda rs: logger.warning(f"Specialist 委派重试 {rs.attempt_number}/2..."),
)
async def call_agent(agent_name: str, query_str: str) -> AgentResult:
    start = time.perf_counter()
    status = "error"
    try:
        agent = specialist_network.get_agent(agent_name)
        agent.timeout = 180  # specialist 内部含 LLM，偶发限流时 >30s，默认超时过短
        trace_id = get_trace_id()
        message = Message(content=TextContent(text=query_str), role=MessageRole.USER)
        message_dict = message.to_dict()
        message_dict["_trace_id"] = trace_id
        task = Task(id="task-" + str(uuid.uuid4()), message=message_dict)

        def _on_progress(stage: dict):
            # specialist 阶段转发到 planner 本进程 progress_store（同一 trace_id）
            progress_store.record(trace_id, stage.get("stage", ""), f"[{agent_name}] {stage.get('label', '')}")

        with span("a2a_call_agent", {"agent_name": agent_name}):
            # 后台阻塞等最终结果 + 前台轮询 specialist 进度端点
            raw_response = await await_task_with_progress(
                agent.send_task_async(task),
                AGENT_URLS[agent_name],
                trace_id,
                on_progress=_on_progress,
            )
            state = str(raw_response.status.state)
            logger.info(f"{agent_name} 响应状态: {state}")
            status = state

            if state == 'completed':
                return AgentResult("completed", raw_response.artifacts[0]['parts'][0]['text'])

            # input-required / failed 等：从 status.message 提取追问或错误文本
            return AgentResult(state, status_message_text(raw_response.status.message))
    finally:
        elapsed = time.perf_counter() - start
        a2a_agent_calls_total.labels(agent_name=agent_name, status=status).inc()
        a2a_agent_call_duration_seconds.labels(agent_name=agent_name).observe(elapsed)


# ============ Agent 卡片 ============
agent_card = AgentCard(
    name="PlannerAgent",
    description="CUHK 日程规划 Agent：拆解复合日程需求，并行委派课程/设施/交通 specialist，检测时间冲突并合成日程",
    url="http://localhost:5009",
    version="1.0.0",
    capabilities={"streaming": True, "memory": False},
    skills=[
        AgentSkill(
            name="plan campus schedule",
            description="把复合日程需求拆解为子任务并行委派，检测时间/地点冲突，输出带时间轴的日程",
            examples=["帮我规划周四下午：下课后去图书馆，再坐校巴回逸夫书院"]
        )
    ]
)


# ============ A2A Server ============
class PlannerServer(A2AServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)

    def setup_routes(self, app):
        """注册自定义进度端点（在库默认路由之上）。"""
        super().setup_routes(app)
        register_progress_endpoint(app, self)

    async def _delegate_one(self, subtask: dict) -> AgentResult:
        """委派单个子任务到对应 specialist。"""
        intent = subtask.get("intent", "")
        description = subtask.get("description", "")
        agent_name = PLANNER_SPECIALISTS.get(intent)
        if not agent_name:
            return AgentResult("failed", f"（未映射到 specialist：{intent}）")
        return await call_agent(agent_name, description)

    async def _plan(self, conversation: str) -> str:
        """四步规划主流程：拆解 → 并行委派 → 冲突判断 → 合成。"""
        trace_id = get_trace_id()
        with span("planner_handle_task", {"agent": "PlannerAgent"}):
            progress_store.record(trace_id, STAGE_DECOMPOSE, "拆解日程目标…")
            subtasks = await decompose_goal(conversation)

            # 并行委派（gather 并发，单子任务失败不拖垮整体）
            progress_store.record(trace_id, STAGE_DELEGATE, "并行查询课程/设施/交通…")
            delegated = await asyncio.gather(
                *[self._delegate_one(t) for t in subtasks],
                return_exceptions=True,
            )

            results = []
            for t, r in zip(subtasks, delegated):
                if isinstance(r, Exception):
                    logger.error(f"子任务失败: {t.get('description', '')[:40]} - {r}")
                    results.append({"description": t.get("description", ""), "intent": t.get("intent", ""), "result": "未能获取"})
                elif r.needs_input:
                    logger.info(f"子任务需补充信息: {t.get('description', '')[:40]} -> {r.text[:40]}")
                    results.append({"description": t.get("description", ""), "intent": t.get("intent", ""), "result": f"⚠️ 需要补充信息：{r.text}"})
                else:
                    results.append({"description": t.get("description", ""), "intent": t.get("intent", ""), "result": r.text})

            progress_store.record(trace_id, STAGE_CONFLICT, "检测时间/地点冲突…")
            conflicts = await detect_conflicts(conversation, subtasks, results)
            progress_store.record(trace_id, STAGE_COMPOSE, "合成日程…")
            return await compose_schedule(conversation, subtasks, results, conflicts)

    def handle_task(self, task):
        # 从 A2A 消息提取 trace_id，实现跨进程链路关联（与 specialist 对称）
        trace_id = (task.message or {}).get("_trace_id", "")
        if trace_id:
            set_trace_id(trace_id)

        content = (task.message or {}).get("content", {})
        text = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"规划任务: {text[:80]}")

        try:
            answer = asyncio.run(self._plan(text))
            task.artifacts = [{"parts": [{"type": "text", "text": answer}]}]
            task.status = TaskStatus(state=TaskState.COMPLETED)
        except Exception as e:
            logger.error(f"规划失败: {e}")
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message={"role": "agent", "content": {"text": f"规划失败: {str(e)} 请重试。"}},
            )
        return task


if __name__ == "__main__":
    planner = PlannerServer()
    print("\n=== 服务器信息 ===")
    print(f"名称: {planner.agent_card.name}")
    print(f"描述: {planner.agent_card.description}")
    print(f"版本: {planner.agent_card.version}")
    print("\n委派的 specialist agents:")
    for name, url in AGENT_URLS.items():
        print(f"- {name}: {url}")
    run_server(planner, host="127.0.0.1", port=5009)
