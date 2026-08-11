#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: logging.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/4
描述: 日志系统初始化
"""
import logging
import os

from app.config import Config
from app.observability import TraceFilter


def setup_logger(name, log_file='logs/app.log'):
    # 创建日志文件夹
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # 获取日志记录器
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    # 防止重复输出的关键！
    logger.propagate = False

    # 定义日志格式 — 包含 trace_id 和 span_id 用于全链路关联
    formatter = logging.Formatter(
        '%(name)s - %(asctime)s - %(levelname)s - [%(trace_id)s:%(span_id)s] - %(message)s'
    )

    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)  # 每个日志处理器可以单独设置日志级别，但是这个日志级别必须高于或等于处理器级别

    # 创建文件处理器
    file_handler = logging.FileHandler(filename=log_file, encoding="utf-8", mode="a")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    # 将处理器添加到日志记录器中
    if not logger.handlers:  # 先进行判断，再进行添加。避免重复添加处理器
        # 注入 TraceFilter 到每个 handler，确保所有日志（含子 logger 传播的）都有 trace_id
        trace_filter = TraceFilter()
        console_handler.addFilter(trace_filter)
        file_handler.addFilter(trace_filter)
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
    else:
        # 如果已有 handler，确保它们也有 TraceFilter
        for handler in logger.handlers:
            if not any(isinstance(f, TraceFilter) for f in handler.filters):
                handler.addFilter(TraceFilter())

    return logger


logger = setup_logger('SmartCampus', Config().log_file)
