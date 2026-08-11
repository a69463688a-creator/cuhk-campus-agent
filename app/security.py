#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: security.py
项目: SmartCampus — CUHK校园生活助手
描述: SQL 安全校验 —— 确保 LLM 生成的 SQL 仅包含只读 SELECT 语句，
      在 MCP Server 的 execute_query() 执行前调用，防止注入和误操作。
"""
import re

# 禁止的 SQL 关键字（仅允许 SELECT 只读查询）
_FORBIDDEN_KEYWORDS = [
    'DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 'TRUNCATE',
    'CREATE', 'EXEC', 'EXECUTE', 'GRANT', 'REVOKE', 'LOAD',
    'RENAME', 'REPLACE', 'MERGE', 'CALL', 'IMPORT', 'EXPORT',
    'LOCK', 'UNLOCK', 'FLUSH', 'SHUTDOWN', 'KILL',
]


def _remove_quoted_strings(sql: str) -> str:
    """
    移除 SQL 中单引号和双引号包裹的字符串字面量，
    避免在字符串内容中误判禁止关键字（如 SELECT 'DROP TABLE' AS msg）。
    """
    # 移除单引号字符串（处理 '' 转义和 \' 转义）
    result = re.sub(r"'(?:[^'\\]|\\.)*'", "''", sql)
    # 移除双引号字符串
    result = re.sub(r'"(?:[^"\\]|\\.)*"', '""', result)
    return result


def validate_readonly_sql(sql: str) -> str:
    """
    校验 SQL 是否为安全的只读 SELECT 语句。

    校验规则：
      1. 必须以 SELECT 开头（忽略前导空白，大小写不敏感）
      2. 不得包含任何禁止的 DDL/DML 关键字
      3. 不得包含分号（阻止堆叠查询注入）

    Args:
        sql: 待校验的 SQL 字符串

    Returns:
        通过校验的原始 SQL 字符串（方便链式调用）

    Raises:
        ValueError: 校验不通过时抛出，包含具体原因
    """
    if not sql or not isinstance(sql, str):
        raise ValueError("SQL 查询为空或类型无效")

    stripped = sql.strip()

    # ── 检查 1: 必须以 SELECT 开头 ──
    if not re.match(r'^\s*SELECT\b', stripped, re.IGNORECASE):
        raise ValueError(
            f"仅允许 SELECT 查询，当前查询以 '"
            f"{stripped[:60]}{'...' if len(stripped) > 60 else ''}' 开头"
        )

    # ── 检查 2: 移除字符串字面量后检查禁止关键字 ──
    cleaned = _remove_quoted_strings(stripped)
    for keyword in _FORBIDDEN_KEYWORDS:
        if re.search(rf'\b{keyword}\b', cleaned, re.IGNORECASE):
            raise ValueError(
                f"SQL 中包含禁止的关键字 '{keyword}'"
            )

    # ── 检查 3: 禁止堆叠查询（分号） ──
    if ';' in cleaned:
        raise ValueError("禁止堆叠查询（不允许使用分号分隔多条语句）")

    return sql
