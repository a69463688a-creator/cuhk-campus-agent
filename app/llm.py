#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: llm.py
项目: SmartCampus — CUHK校园生活助手
描述: 统一 LLM 工厂 —— 提供 create_llm() 函数，所有组件通过此函数
      获取 ChatOpenAI 实例，确保配置一致性、避免重复初始化代码。
"""
from langchain_openai import ChatOpenAI
from app.config import Config


def create_llm(
    temperature: float | None = None,
    streaming: bool = False,
    max_retries: int = 1,
    model: str | None = None,
) -> ChatOpenAI:
    """
    基于全局 Config 创建 ChatOpenAI 实例。

    Args:
        temperature: 温度参数，None 时使用 Config.temperature（默认 0.1）。
                     传具体值可覆盖配置，用于需要不同创造性程度的场景。
        streaming:   是否开启 token 级流式（仅最终输出 LLM 用 astream 时置 True；
                     其余意图/SQL/拆解等同步调用保持 False，避免影响既有链路）。
        max_retries: OpenAI SDK 内部重试次数（默认 1，较官方默认 2 更快地让 429
                     交回上层 tenacity 处理，避免多层指数退避叠加）。
        model:       覆盖默认模型（仅当 API 提供更小/更快模型时由调用点指定）。

    Returns:
        配置好的 ChatOpenAI 实例
    """
    conf = Config()
    return ChatOpenAI(
        model=model or conf.model_name,
        api_key=conf.api_key,
        base_url=conf.base_url,
        temperature=temperature if temperature is not None else conf.temperature,
        streaming=streaming,
        max_retries=max_retries,
    )
