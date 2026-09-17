#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: a2a_types.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/9/17
描述: A2A 委派结果的轻量传递结构。

解决「单向透传」问题：specialist 缺信息时返回 TaskState.INPUT_REQUIRED（追问），
编排层需区分「正常结果」与「追问」，逐级上抛而非当普通文本 summarize。
state 直接取 python_a2a TaskState 的字符串值（见 models/task.py）：
  - "completed"        正常结果
  - "input-required"   缺信息，需上游补充（注意值带连字符）
  - "failed" / 其他     异常/失败
"""
from typing import Any, NamedTuple


class AgentResult(NamedTuple):
    """委派结果。state: python_a2a TaskState 字符串值；text: 结果文本或追问文本。"""
    state: str
    text: str

    @property
    def needs_input(self) -> bool:
        """是否为「追问」：需要上游（用户）补充信息后重跑。"""
        return self.state == "input-required"


def status_message_text(message: Any) -> str:
    """从 TaskStatus.message 提取文本，兼容 dict / str / None 多种形态。

    specialist 返回 INPUT_REQUIRED / FAILED 时，追问或错误文本放在
    status.message = {"role": "agent", "content": {"text": "..."}}。
    """
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, dict):
            return content.get("text", "") or ""
        if isinstance(content, str):
            return content
        return str(message)
    if isinstance(message, str):
        return message
    return str(message) if message else ""
