"""校巴交通 — 2 张表

Revision ID: 004
Revises: 003
Create Date: 2026-09-17

使用 CREATE TABLE IF NOT EXISTS 保证幂等（与 001/003 一致）。
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建 bus_routes / bus_stops 两张校巴表（幂等）"""

    # ── 校巴路线表 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS bus_routes (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
            route_code VARCHAR(10) NOT NULL COMMENT '路线编号(1/2/3/4/5/6A/6B/7/N/H)',
            route_name VARCHAR(100) COMMENT '路线名称',
            start_stop VARCHAR(100) COMMENT '起点站',
            end_stop VARCHAR(100) COMMENT '终点站',
            service_type VARCHAR(30) COMMENT '服务类型: regular/class_change/night/holiday',
            first_bus_time VARCHAR(10) COMMENT '首班车 HH:MM',
            last_bus_time VARCHAR(10) COMMENT '末班车 HH:MM',
            frequency_min INT COMMENT '发车间隔(分钟)',
            note VARCHAR(200) COMMENT '备注',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_route (route_code)
        ) ENGINE=INNODB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='校巴路线表'
    """)

    # ── 校巴站点表 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS bus_stops (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
            route_code VARCHAR(10) NOT NULL COMMENT '路线编号',
            stop_order INT NOT NULL COMMENT '站点序号(升序)',
            stop_name VARCHAR(100) NOT NULL COMMENT '站点中文名',
            stop_name_en VARCHAR(100) COMMENT '站点英文名',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_stop (route_code, stop_order)
        ) ENGINE=INNODB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='校巴站点表'
    """)


def downgrade() -> None:
    """回滚：删除 2 张校巴表"""
    op.execute("DROP TABLE IF EXISTS bus_stops")
    op.execute("DROP TABLE IF EXISTS bus_routes")
