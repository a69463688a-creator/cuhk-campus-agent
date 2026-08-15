"""持久化分层记忆 — 3 张记忆表

Revision ID: 003
Revises: 6fc6fe4f3bd4
Create Date: 2026-08-15

使用 CREATE TABLE IF NOT EXISTS 保证幂等（与 001 一致）。

三张表对应分层记忆架构：
  conversation_messages — 情景记忆（Episodic）：完整对话消息，持久化底座
  conversation_summaries — 摘要记忆（Summary）：超窗旧对话的滚动压缩
  long_term_memories — 语义记忆（Semantic）：跨会话长期事实/偏好，含 embedding
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "003"
down_revision = "6fc6fe4f3bd4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建 3 张记忆表（幂等）"""

    # ── 情景记忆：完整对话消息（持久化底座） ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS conversation_messages (
            id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
            session_id VARCHAR(64) NOT NULL COMMENT '会话ID',
            user_id VARCHAR(64) NULL COMMENT '用户ID（预留多用户）',
            role VARCHAR(20) NOT NULL COMMENT '角色：user/assistant',
            content TEXT NOT NULL COMMENT '消息内容',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            KEY idx_session_id (session_id, id)
        ) ENGINE=INNODB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='情景记忆：会话消息'
    """)

    # ── 摘要记忆：滚动摘要（超窗旧对话的压缩） ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS conversation_summaries (
            id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
            session_id VARCHAR(64) NOT NULL COMMENT '会话ID',
            summary TEXT NOT NULL COMMENT '滚动摘要内容',
            start_turn BIGINT NOT NULL DEFAULT 0 COMMENT '摘要覆盖的起始消息ID',
            end_turn BIGINT NOT NULL DEFAULT 0 COMMENT '摘要覆盖的结束消息ID',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
            UNIQUE KEY unique_session (session_id)
        ) ENGINE=INNODB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='摘要记忆：滚动摘要'
    """)

    # ── 语义记忆：长期事实/偏好（含 embedding） ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS long_term_memories (
            id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
            session_id VARCHAR(64) NULL COMMENT '来源会话ID',
            user_id VARCHAR(64) NULL COMMENT '用户ID（预留多用户）',
            content TEXT NOT NULL COMMENT '长期记忆内容（事实/偏好）',
            embedding BLOB NULL COMMENT '内容向量（float32，1024 维）',
            category VARCHAR(30) NULL COMMENT '类别：identity/preference/fact/...',
            importance FLOAT NOT NULL DEFAULT 1.0 COMMENT '重要度',
            access_count INT NOT NULL DEFAULT 0 COMMENT '被召回次数',
            last_accessed_at DATETIME NULL COMMENT '最近被召回时间',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            KEY idx_user_id (user_id),
            KEY idx_session_id (session_id)
        ) ENGINE=INNODB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='语义记忆：长期事实与偏好'
    """)


def downgrade() -> None:
    """回滚：删除 3 张记忆表"""
    op.execute("DROP TABLE IF EXISTS long_term_memories")
    op.execute("DROP TABLE IF EXISTS conversation_summaries")
    op.execute("DROP TABLE IF EXISTS conversation_messages")
