#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: format.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/2/4
描述: JSON 序列化工具 —— Date / DateTime / Decimal 自定义编码器
"""
import json
from datetime import date, datetime, timedelta
from decimal import Decimal


def default_encoder(obj):
    """格式化单个对象为 JSON 兼容类型"""
    if isinstance(obj, datetime):
        return obj.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(obj, date):
        return obj.strftime('%Y-%m-%d')
    if isinstance(obj, timedelta):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


class DateEncoder(json.JSONEncoder):
    """自定义JSON编码器，处理datetime/date/timedelta/Decimal类型"""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(obj, date):
            return obj.strftime('%Y-%m-%d')
        if isinstance(obj, timedelta):
            return str(obj)
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)
