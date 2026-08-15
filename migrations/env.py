"""
Alembic 迁移环境配置
从项目 Config 读取数据库连接信息，支持在线/离线迁移。
"""
import os
import sys
from logging.config import fileConfig

# 将项目根目录加入 sys.path，确保可以导入 app.config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import engine_from_config, pool
from alembic import context
from app.config import Config as AppConfig

# Alembic Config 对象
config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 从项目配置读取数据库连接信息（环境变量优先）
app_conf = AppConfig()
DB_URL = (
    f"mysql+pymysql://{app_conf.user}:{app_conf.password}"
    f"@{app_conf.host}:{app_conf.port}/{app_conf.database}"
    f"?charset=utf8mb4"
)

# 将 URL 注入 alembic 配置，供 engine_from_config 使用
config.set_main_option("sqlalchemy.url", DB_URL)

# 无 SQLAlchemy 模型，使用原始 SQL 迁移
target_metadata = None


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 脚本而非直接执行"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：直接连接数据库执行迁移"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
