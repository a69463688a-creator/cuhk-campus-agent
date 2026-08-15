#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: memory.py
项目: SmartCampus — 基于A2A的CUHK校园生活助手
创建日期: 2026/8/15
描述: 持久化分层记忆系统 —— MemoryManager + OllamaEmbedder

分层记忆架构（自研）：
  Episodic（情景记忆）  = conversation_messages 表，所有对话消息落库，持久化底座
    ├─ 切片 → Working（工作记忆）：最近窗口原始消息，直接进 prompt
    ├─ 压缩 → Summary（摘要记忆）：超窗旧消息经 LLM 滚动压缩
    └─ 提炼 → Semantic（语义记忆）：长期事实/偏好，embedding 向量化后按需检索

核心接口：
  recall(session_id, query)  → 组装 token 预算内的上下文（替换旧 history_text）
  save(session_id, role, content)  → 落库（参数化查询）
  consolidate(session_id)    → 后台巩固：滚动摘要 + 长期记忆抽取（去重）

设计要点：
  - 混合检索：向量余弦 + 关键词 LIKE，两路经 RRF（Reciprocal Rank Fusion）融合
  - 长期记忆去重：新事实与已有记忆算余弦，超过阈值则合并更新
  - embedding 走本地 Ollama bge-m3（HTTP /api/embed），失败自动降级关键词召回
  - 所有 SQL 均参数化（%s 占位），严禁字符串拼接
"""
import json
import re

import numpy as np
import mysql.connector
import httpx
from langchain_core.prompts import ChatPromptTemplate

from app.config import Config
from app.logging import logger
from app.llm import create_llm

# ============ LLM Prompt（摘要 / 抽取） ============
_summary_prompt = ChatPromptTemplate.from_template(
    """你是记忆压缩器。把下面的对话压缩成一段简洁摘要，保留关键信息
（用户身份、专业、偏好、已查询内容、重要结论），用中文，100 字以内。

已有摘要（可为空）：{existing_summary}

对话：
{conversation}
"""
)

_extract_prompt = ChatPromptTemplate.from_template(
    """你是记忆抽取器。从下面的对话中抽取值得长期记住的用户事实或偏好
（例如：身份、专业、年级、兴趣、饮食/座位偏好、常去的地点等）。
只输出一个 JSON 数组，每个元素是一条事实的字符串；没有则输出 []。
绝对不要输出 JSON 以外的任何文字。

对话：
{conversation}
"""
)


class OllamaEmbedder:
    """本地 Ollama embedding 客户端（bge-m3，1024 维）"""

    def __init__(self, base_url: str, model: str, dim: int):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim

    def embed(self, texts) -> list[list[float]]:
        """批量向量化。返回 list[list[float]]，维度与 dim 一致。"""
        if isinstance(texts, str):
            texts = [texts]
        if not texts:
            return []
        resp = httpx.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": texts},
            timeout=30.0,
        )
        resp.raise_for_status()
        embeddings = resp.json().get("embeddings", [])
        # bge-m3 已知对个别超长/技术文本返回 NaN，此处显式拦截以便上层降级
        for emb in embeddings:
            if any(v != v for v in emb):  # NaN != NaN
                raise ValueError("embedding 含 NaN（bge-m3 已知问题）")
        return embeddings

    def embed_one(self, text: str) -> list[float]:
        """单条向量化。"""
        return self.embed([text])[0]


class MemoryManager:
    """持久化分层记忆管理器。

    封装 conversation_messages / conversation_summaries / long_term_memories
    三张表的读写，对外提供 recall / save / consolidate / get_history / clear。
    """

    # 工作记忆窗口最多取最近多少条原始消息（最终以 token 预算为准）
    _WORKING_LIMIT = 30
    # 摘要时保留最近多少条原始消息不被压缩
    _KEEP_RECENT = 8
    # 长期记忆抽取的频率控制（每 consolidate N 次抽一次，降低 LLM 调用）
    _EXTRACT_EVERY = 3
    # 抽取时回看最近多少条消息
    _EXTRACT_LOOKBACK = 8

    def __init__(self, conf: Config):
        self.conf = conf
        self.embedder = OllamaEmbedder(
            conf.embedding_base_url, conf.embedding_model, conf.embedding_dim
        )
        self.llm = create_llm()
        self.conn = None
        self._extract_counter: dict[str, int] = {}
        try:
            self._connect()
        except Exception as e:
            logger.warning(f"[Memory] 初始连接失败（将懒重连）: {e}")
            self.conn = None

    # ============ 连接管理 ============
    def _connect(self):
        self.conn = mysql.connector.connect(
            host=self.conf.host,
            port=self.conf.port,
            user=self.conf.user,
            password=self.conf.password,
            database=self.conf.database,
            charset="utf8mb4",
        )

    def _ensure_connection(self):
        try:
            if self.conn is None or not self.conn.is_connected():
                logger.warning("[Memory] MySQL 连接已断开，正在重连...")
                self._connect()
        except Exception:
            logger.warning("[Memory] MySQL 连接检查失败，正在重连...")
            self._connect()

    # ============ 对外核心接口 ============
    def warmup(self):
        """预热 embedding 模型，消除首次调用冷启动延迟（约 2.5s）。"""
        try:
            self.embedder.embed_one("预热")
            logger.info("[Memory] embedding 模型已预热")
        except Exception as e:
            logger.warning(f"[Memory] embedding 预热失败（召回将降级关键词）: {e}")

    def recall(self, session_id: str, query: str, token_budget: int | None = None) -> str:
        """召回分层记忆上下文（替换旧 history_text）。

        组装优先级：Working（工作窗口） > Semantic（语义记忆） > Summary（摘要）。
        返回分段文本，供 recognize_intent / call_agent 直接消费。
        """
        budget = token_budget or self.conf.memory_window_tokens
        parts: list[tuple[str, str]] = []
        remaining = budget

        # 1) 工作记忆（近期对话窗口，最高优先）
        rows = self._get_recent_messages(session_id, limit=self._WORKING_LIMIT)
        if rows:
            working = self._format_working(rows)
            working = self._cap_tokens(working, remaining)
            if working:
                parts.append(("[近期对话]", working))
                remaining -= self._estimate_tokens(working)

        # 2) 语义记忆（混合检索 + RRF 融合）
        semantic = self._semantic_recall(query, top_k=self.conf.memory_semantic_top_k)
        if semantic:
            sem_text = "\n".join(f"- {m}" for m in semantic)
            sem_text = self._cap_tokens(sem_text, remaining)
            if sem_text:
                parts.append(("[相关长期记忆]", sem_text))
                remaining -= self._estimate_tokens(sem_text)

        # 3) 摘要记忆（滚动摘要，预算不足时最先被裁）
        if remaining > 0:
            summary = self._get_latest_summary(session_id)
            if summary:
                summary = self._cap_tokens(summary, remaining)
                if summary:
                    parts.append(("[对话摘要]", summary))

        return "\n\n".join(f"{header}\n{body}" for header, body in parts)

    def save(self, session_id: str, role: str, content: str) -> None:
        """持久化一条消息（情景记忆落库，参数化查询）。"""
        if not content:
            return
        self._ensure_connection()
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO conversation_messages (session_id, role, content) VALUES (%s, %s, %s)",
            (session_id, role, content),
        )
        self.conn.commit()
        cursor.close()

    def consolidate(self, session_id: str) -> None:
        """后台巩固：滚动摘要 + 长期记忆抽取（含去重）。"""
        try:
            self._maybe_summarize(session_id)
        except Exception as e:
            logger.warning(f"[Memory] 滚动摘要失败: {e}")
        try:
            self._maybe_extract_long_term(session_id)
        except Exception as e:
            logger.warning(f"[Memory] 长期记忆抽取失败: {e}")

    def get_history(self, session_id: str) -> list[dict]:
        """读取会话完整历史（供 /api/history）。"""
        self._ensure_connection()
        cursor = self.conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT role, content, created_at FROM conversation_messages "
            "WHERE session_id=%s ORDER BY id ASC",
            (session_id,),
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {"role": r["role"], "content": r["content"], "timestamp": str(r["created_at"])}
            for r in rows
        ]

    def clear(self, session_id: str) -> None:
        """清除会话历史（消息 + 摘要）；长期记忆为跨会话资产，不随会话清除。"""
        self._ensure_connection()
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM conversation_messages WHERE session_id=%s", (session_id,))
        cursor.execute("DELETE FROM conversation_summaries WHERE session_id=%s", (session_id,))
        self.conn.commit()
        cursor.close()

    # ============ 工作记忆（Episodic 切片） ============
    def _get_recent_messages(self, session_id: str, limit: int) -> list[dict]:
        self._ensure_connection()
        cursor = self.conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT role, content FROM conversation_messages "
            "WHERE session_id=%s ORDER BY id DESC LIMIT %s",
            (session_id, limit),
        )
        rows = cursor.fetchall()
        cursor.close()
        rows.reverse()  # 旧 → 新
        return rows

    @staticmethod
    def _format_working(rows: list[dict]) -> str:
        """把消息列表格式化为 User:/Assistant: 文本（与旧 history_text 格式兼容）。"""
        lines = []
        for r in rows:
            prefix = "User" if r["role"] == "user" else "Assistant"
            lines.append(f"{prefix}: {r['content']}")
        return "\n".join(lines)

    # ============ 摘要记忆 ============
    def _maybe_summarize(self, session_id: str) -> None:
        total = self._count_messages(session_id)
        if total <= self.conf.memory_summary_trigger_turns:
            return
        old_rows = self._get_old_messages(session_id, exclude_recent=self._KEEP_RECENT)
        if not old_rows:
            return
        existing = self._get_latest_summary(session_id)
        conversation = self._format_working(old_rows)
        chain = _summary_prompt | self.llm
        out = chain.invoke({
            "conversation": conversation,
            "existing_summary": existing if existing else "（无已有摘要）",
        }).content.strip()
        self._upsert_summary(session_id, out, end_turn=old_rows[-1]["id"])
        logger.info(f"[Memory] 滚动摘要已更新（覆盖至消息 #{old_rows[-1]['id']}）")

    def _count_messages(self, session_id: str) -> int:
        self._ensure_connection()
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM conversation_messages WHERE session_id=%s", (session_id,)
        )
        n = cursor.fetchone()[0]
        cursor.close()
        return n

    def _get_old_messages(self, session_id: str, exclude_recent: int) -> list[dict]:
        """取「已摘要位置之后、最近 exclude_recent 条之前」的旧消息（增量）。"""
        self._ensure_connection()
        last_end = self._get_summary_end_turn(session_id)
        cursor = self.conn.cursor(dictionary=True)
        if last_end:
            cursor.execute(
                "SELECT id, role, content FROM conversation_messages "
                "WHERE session_id=%s AND id > %s ORDER BY id ASC",
                (session_id, last_end),
            )
        else:
            cursor.execute(
                "SELECT id, role, content FROM conversation_messages "
                "WHERE session_id=%s ORDER BY id ASC",
                (session_id,),
            )
        rows = cursor.fetchall()
        cursor.close()
        if len(rows) <= exclude_recent:
            return []
        return rows[:-exclude_recent]

    def _get_summary_end_turn(self, session_id: str) -> int:
        self._ensure_connection()
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT end_turn FROM conversation_summaries WHERE session_id=%s", (session_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        return row[0] if row else 0

    def _get_latest_summary(self, session_id: str) -> str:
        self._ensure_connection()
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT summary FROM conversation_summaries "
            "WHERE session_id=%s ORDER BY end_turn DESC LIMIT 1",
            (session_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        return row[0] if row else ""

    def _upsert_summary(self, session_id: str, summary: str, end_turn: int) -> None:
        self._ensure_connection()
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO conversation_summaries (session_id, summary, start_turn, end_turn) "
            "VALUES (%s, %s, 0, %s) "
            "ON DUPLICATE KEY UPDATE summary=%s, end_turn=%s",
            (session_id, summary, end_turn, summary, end_turn),
        )
        self.conn.commit()
        cursor.close()

    # ============ 语义记忆（长期事实/偏好） ============
    def _maybe_extract_long_term(self, session_id: str) -> None:
        self._extract_counter[session_id] = self._extract_counter.get(session_id, 0) + 1
        if self._extract_counter[session_id] < self._EXTRACT_EVERY:
            return
        self._extract_counter[session_id] = 0

        rows = self._get_recent_messages(session_id, limit=self._EXTRACT_LOOKBACK)
        if not rows:
            return
        conversation = self._format_working(rows)
        chain = _extract_prompt | self.llm
        out = chain.invoke({"conversation": conversation}).content.strip()
        out = re.sub(r'^```(?:json)?\s*|\s*```$', '', out).strip()
        facts = json.loads(out)
        if not isinstance(facts, list):
            return
        for fact in facts:
            if isinstance(fact, str) and fact.strip():
                self._upsert_memory(fact.strip(), session_id)
        logger.info(f"[Memory] 抽取长期记忆 {len(facts)} 条")

    def _upsert_memory(self, content: str, session_id: str) -> None:
        """写入长期记忆：与已有记忆做余弦去重，超过阈值则合并更新。"""
        vec = None
        try:
            vec = self.embedder.embed_one(content)
        except Exception as e:
            logger.warning(f"[Memory] 长期记忆向量化失败（仍落库，无 embedding）: {e}")

        best_id, best_sim = None, -1.0
        if vec is not None:
            q = np.asarray(vec, dtype=np.float32)
            qn = np.linalg.norm(q)
            if qn > 0:
                for row in self._load_all_memories_with_embedding():
                    try:
                        e = np.frombuffer(row["embedding"], dtype=np.float32)
                    except Exception:
                        continue
                    if e.shape[0] != q.shape[0]:
                        continue
                    en = np.linalg.norm(e)
                    if en == 0:
                        continue
                    sim = float(np.dot(q, e) / (qn * en))
                    if sim > best_sim:
                        best_sim, best_id = sim, row["id"]

        if best_id is not None and best_sim >= self.conf.memory_dedup_threshold:
            self._update_memory(best_id, content, vec)
        else:
            self._insert_memory(content, vec, session_id)

    def _insert_memory(self, content: str, vec, session_id: str) -> None:
        blob = self._serialize(vec) if vec is not None else None
        self._ensure_connection()
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO long_term_memories (session_id, content, embedding) "
            "VALUES (%s, %s, %s)",
            (session_id, content, blob),
        )
        self.conn.commit()
        cursor.close()

    def _update_memory(self, memory_id: int, content: str, vec) -> None:
        blob = self._serialize(vec) if vec is not None else None
        self._ensure_connection()
        cursor = self.conn.cursor()
        if blob is not None:
            cursor.execute(
                "UPDATE long_term_memories SET content=%s, embedding=%s WHERE id=%s",
                (content, blob, memory_id),
            )
        else:
            cursor.execute(
                "UPDATE long_term_memories SET content=%s WHERE id=%s",
                (content, memory_id),
            )
        self.conn.commit()
        cursor.close()

    @staticmethod
    def _serialize(vec: list[float]) -> bytes:
        """float32 序列化为 BLOB（1024 维 ≈ 4KB）。"""
        return np.asarray(vec, dtype=np.float32).tobytes()

    def _load_all_memories_with_embedding(self) -> list[dict]:
        self._ensure_connection()
        cursor = self.conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, content, embedding FROM long_term_memories WHERE embedding IS NOT NULL"
        )
        rows = cursor.fetchall()
        cursor.close()
        return rows

    # ============ 混合检索（向量 + 关键词，RRF 融合） ============
    def _semantic_recall(self, query: str, top_k: int) -> list[str]:
        vec_hits = []
        try:
            q_vec = self.embedder.embed_one(query)
            vec_hits = self._cosine_topk(q_vec, top_k)
        except Exception as e:
            logger.warning(f"[Memory] 向量召回失败，降级关键词: {e}")

        kw_hits = self._keyword_search(query, top_k)
        return self._rrf_fuse(vec_hits, kw_hits, top_k)

    def _cosine_topk(self, q_vec: list[float], top_k: int) -> list[tuple[int, str, float]]:
        q = np.asarray(q_vec, dtype=np.float32)
        qn = np.linalg.norm(q)
        if qn == 0:
            return []
        scored = []
        for row in self._load_all_memories_with_embedding():
            try:
                e = np.frombuffer(row["embedding"], dtype=np.float32)
            except Exception:
                continue
            if e.shape[0] != q.shape[0]:
                continue
            en = np.linalg.norm(e)
            if en == 0:
                continue
            sim = float(np.dot(q, e) / (qn * en))
            scored.append((row["id"], row["content"], sim))
        scored.sort(key=lambda x: x[2], reverse=True)
        return scored[:top_k]

    def _keyword_search(self, query: str, top_k: int) -> list[tuple[int, str]]:
        tokens = re.findall(r'[一-鿿]{2,}|[A-Za-z0-9]{2,}', query)
        if not tokens:
            return []
        tokens = tokens[:5]
        self._ensure_connection()
        cond = " OR ".join(["content LIKE %s"] * len(tokens))
        params = [f"%{t}%" for t in tokens]
        sql = (
            f"SELECT id, content FROM long_term_memories "
            f"WHERE {cond} ORDER BY access_count DESC, created_at DESC LIMIT %s"
        )
        cursor = self.conn.cursor(dictionary=True)
        cursor.execute(sql, params + [top_k])
        rows = cursor.fetchall()
        cursor.close()
        return [(r["id"], r["content"]) for r in rows]

    def _rrf_fuse(
        self,
        vec_hits: list[tuple[int, str, float]],
        kw_hits: list[tuple[int, str]],
        top_k: int,
        k: int = 60,
    ) -> list[str]:
        """Reciprocal Rank Fusion：score(doc) = Σ 1/(k + rank)。"""
        scores: dict[int, float] = {}
        content_map: dict[int, str] = {}
        for rank, (mid, content, _sim) in enumerate(vec_hits):
            scores[mid] = scores.get(mid, 0) + 1.0 / (k + rank + 1)
            content_map[mid] = content
        for rank, (mid, content) in enumerate(kw_hits):
            scores[mid] = scores.get(mid, 0) + 1.0 / (k + rank + 1)
            content_map[mid] = content

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        self._touch_memories([mid for mid, _ in ranked])
        return [content_map[mid] for mid, _ in ranked]

    def _touch_memories(self, ids: list[int]) -> None:
        """更新被召回记忆的访问计数与最近访问时间（用于新鲜度权重）。"""
        if not ids:
            return
        self._ensure_connection()
        placeholders = ",".join(["%s"] * len(ids))
        cursor = self.conn.cursor()
        cursor.execute(
            f"UPDATE long_term_memories "
            f"SET access_count=access_count+1, last_accessed_at=NOW() "
            f"WHERE id IN ({placeholders})",
            ids,
        )
        self.conn.commit()
        cursor.close()

    # ============ token 预算近似 ============
    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """粗略 token 估算：以字符数近似（中文 1 字符 ≈ 1 token）。"""
        return len(text)

    @staticmethod
    def _cap_tokens(text: str, budget: int) -> str:
        """按预算截断，保留尾部（最近的对话更重要）。"""
        if budget <= 0:
            return ""
        if len(text) <= budget:
            return text
        return text[-budget:]
