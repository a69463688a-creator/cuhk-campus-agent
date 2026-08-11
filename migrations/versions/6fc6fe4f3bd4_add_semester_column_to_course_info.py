"""add semester column to course_info

Revision ID: 6fc6fe4f3bd4
Revises: 002
Create Date: 2026-08-11 15:46:30.255350
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6fc6fe4f3bd4'
down_revision: Union[str, Sequence[str], None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """给 course_info 表增加 semester 字段"""
    op.add_column(
        "course_info",
        sa.Column(
            "semester",
            sa.String(20),
            nullable=True,
            comment="学期标识（如 2026-27-T1）",
        ),
    )


def downgrade() -> None:
    """回滚：删除 semester 字段"""
    op.drop_column("course_info", "semester")
