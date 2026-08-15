#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: test_memory.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/8/15
描述: 持久化分层记忆系统单元测试

不依赖真实 MySQL / Ollama：通过 mock 隔离外部依赖，
聚焦可独立验证的核心逻辑：
  - 混合检索 RRF 融合、向量余弦排序
  - token 预算截断、embedding 序列化往返
  - 长期记忆去重（合并更新 vs 新增）
  - recall 上下文组装、save 参数化查询（防注入）
"""
import numpy as np
from types import SimpleNamespace
from unittest import mock

from app.memory import MemoryManager


def make_manager():
    """构造绕过 __init__ 的 MemoryManager，注入 mock 依赖。"""
    m = MemoryManager.__new__(MemoryManager)
    m.conf = SimpleNamespace(
        memory_window_tokens=2000,
        memory_semantic_top_k=5,
        memory_dedup_threshold=0.9,
        memory_summary_trigger_turns=10,
    )
    m.embedder = mock.Mock()
    m.llm = mock.Mock()
    m.conn = mock.Mock()
    m._extract_counter = {}
    return m


# ============ 混合检索 ============
def test_rrf_fusion_ranking():
    """RRF 融合：两路都命中的文档排第一。"""
    m = make_manager()
    m._touch_memories = mock.Mock()
    vec_hits = [(1, "记忆A", 0.9), (2, "记忆B", 0.8)]
    kw_hits = [(2, "记忆B"), (3, "记忆C")]

    result = m._rrf_fuse(vec_hits, kw_hits, top_k=3)
    # 记忆B 在向量路 + 关键词路都命中，RRF 累加得分最高
    assert result[0] == "记忆B"
    assert set(result) == {"记忆A", "记忆B", "记忆C"}


def test_cosine_topk_ranks_by_similarity():
    """向量余弦：同向向量排最前。"""
    m = make_manager()
    m._load_all_memories_with_embedding = mock.Mock(return_value=[
        {"id": 1, "content": "相关记忆",
         "embedding": np.asarray([1.0, 0.0], dtype=np.float32).tobytes()},
        {"id": 2, "content": "无关记忆",
         "embedding": np.asarray([0.0, 1.0], dtype=np.float32).tobytes()},
    ])
    hits = m._cosine_topk([1.0, 0.0], top_k=2)
    assert hits[0][1] == "相关记忆"   # 余弦 1.0
    assert hits[1][1] == "无关记忆"   # 余弦 0.0


def test_keyword_search_parameterized():
    """关键词检索：LIKE 条件用参数化占位，不拼接用户输入。"""
    m = make_manager()
    fake_cursor = mock.Mock()
    fake_cursor.fetchall.return_value = [{"id": 1, "content": "用户是CS专业学生"}]
    m.conn.cursor = mock.Mock(return_value=fake_cursor)

    m._keyword_search("CS专业", top_k=5)
    sql = fake_cursor.execute.call_args[0][0]
    assert "LIKE %s" in sql
    # 用户输入走参数，而非拼进 SQL
    assert "CS专业" not in sql


# ============ token 预算 & 序列化 ============
def test_cap_tokens_keeps_tail():
    """截断保留尾部（最近的对话更重要）。"""
    assert MemoryManager._cap_tokens("abcdef", 3) == "def"
    assert MemoryManager._cap_tokens("abc", 5) == "abc"
    assert MemoryManager._cap_tokens("abc", 0) == ""


def test_serialize_roundtrip():
    """embedding float32 序列化为 BLOB 后可无损还原。"""
    vec = [1.0, 2.0, 3.0, -0.5]
    blob = MemoryManager._serialize(vec)
    back = np.frombuffer(blob, dtype=np.float32)
    assert np.allclose(back, np.asarray(vec, dtype=np.float32))


def test_format_working_compat():
    """工作记忆格式化与旧 history_text 的 User:/Assistant: 格式兼容。"""
    rows = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    assert MemoryManager._format_working(rows) == "User: hi\nAssistant: hello"


# ============ 长期记忆去重 ============
def test_upsert_dedup_updates_existing():
    """相似事实（余弦 ≥ 阈值）走合并更新，不重复存储。"""
    m = make_manager()
    m.embedder.embed_one = mock.Mock(return_value=[1.0, 0.0, 0.0])
    m._load_all_memories_with_embedding = mock.Mock(return_value=[
        {"id": 10, "content": "用户是CS专业",
         "embedding": np.asarray([1.0, 0.0, 0.0], dtype=np.float32).tobytes()}
    ])
    m._update_memory = mock.Mock()
    m._insert_memory = mock.Mock()

    m._upsert_memory("用户是CS专业学生", "s1")
    m._update_memory.assert_called_once()
    m._insert_memory.assert_not_called()


def test_upsert_new_inserts():
    """不相似的新事实走插入。"""
    m = make_manager()
    m.embedder.embed_one = mock.Mock(return_value=[1.0, 0.0, 0.0])
    m._load_all_memories_with_embedding = mock.Mock(return_value=[
        {"id": 10, "content": "用户喜欢咖啡",
         "embedding": np.asarray([0.0, 1.0, 0.0], dtype=np.float32).tobytes()}
    ])
    m._update_memory = mock.Mock()
    m._insert_memory = mock.Mock()

    m._upsert_memory("用户是CS专业", "s1")
    m._insert_memory.assert_called_once()
    m._update_memory.assert_not_called()


# ============ recall 组装 ============
def test_recall_assembles_context():
    """recall 按优先级组装工作窗口 + 语义记忆 + 摘要。"""
    m = make_manager()
    m._get_recent_messages = mock.Mock(return_value=[
        {"role": "user", "content": "查 CSCI2100"},
        {"role": "assistant", "content": "周一上课"},
    ])
    m._semantic_recall = mock.Mock(return_value=["用户是CS专业学生"])
    m._get_latest_summary = mock.Mock(return_value="之前聊过图书馆开放时间")

    result = m.recall("s1", "那 CSCI4430 呢")
    assert "[近期对话]" in result
    assert "[相关长期记忆]" in result
    assert "[对话摘要]" in result
    assert "用户是CS专业学生" in result
    # 组装顺序：工作窗口在前、摘要在后
    assert result.index("[近期对话]") < result.index("[对话摘要]")


# ============ 持久化 & 参数化 ============
def test_save_uses_parameterized_query():
    """save 落库用 %s 占位参数化，恶意输入不拼进 SQL。"""
    m = make_manager()
    fake_cursor = mock.Mock()
    m.conn.cursor = mock.Mock(return_value=fake_cursor)

    malicious = "hello'; DROP TABLE conversation_messages; --"
    m.save("s1", "user", malicious)

    sql, params = fake_cursor.execute.call_args[0]
    assert sql == ("INSERT INTO conversation_messages (session_id, role, content) "
                   "VALUES (%s, %s, %s)")
    assert params == ("s1", "user", malicious)
    assert "DROP TABLE" not in sql


def test_clear_keeps_long_term():
    """clear 只清消息与摘要，长期记忆为跨会话资产需保留。"""
    m = make_manager()
    fake_cursor = mock.Mock()
    m.conn.cursor = mock.Mock(return_value=fake_cursor)

    m.clear("s1")
    # 应执行两条 DELETE（消息 + 摘要），不应触碰 long_term_memories
    executed_sqls = [c[0][0] for c in fake_cursor.execute.call_args_list]
    assert any("conversation_messages" in s for s in executed_sqls)
    assert any("conversation_summaries" in s for s in executed_sqls)
    assert not any("long_term_memories" in s for s in executed_sqls)
