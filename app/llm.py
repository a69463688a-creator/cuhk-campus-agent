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


def create_llm(temperature: float | None = None) -> ChatOpenAI:
    """
    基于全局 Config 创建 ChatOpenAI 实例。

    Args:
        temperature: 温度参数，None 时使用 Config.temperature（默认 0.1）。
                     传具体值可覆盖配置，用于需要不同创造性程度的场景。

    Returns:
        配置好的 ChatOpenAI 实例
    """
    conf = Config()
    return ChatOpenAI(
        model=conf.model_name,
        api_key=conf.api_key,
        base_url=conf.base_url,
        temperature=temperature if temperature is not None else conf.temperature,
    )
