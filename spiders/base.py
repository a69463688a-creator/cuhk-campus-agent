#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: base.py
项目: SmartCampus — CUHK校园生活助手
描述: 爬虫抽象基类 —— 使用模板方法模式消除 5 个爬虫的重复代码。
      子类只需定义配置属性 + fetch()/store()，基类处理调度、新鲜度检查和 CLI。

用法示例:
    class MySpider(BaseSpider):
        name = "My Spider"
        data_source = "https://example.com"
        stale_hours = 24
        schedule_time = "06:00"
        schedule_rule = "day"
        table_name = "my_table"

        def fetch(self): ...
        def store(self, conn, cursor, items): ...

    if __name__ == "__main__":
        MySpider.main()
"""
import os
import sys
import time
import abc
from datetime import datetime
from typing import Any, List, Optional

import mysql.connector
import schedule
import pytz


class BaseSpider(abc.ABC):
    """
    爬虫抽象基类，模板方法模式。

    子类必须定义（类属性）:
        name: str             — 人类可读的爬虫名称
        data_source: str       — 数据来源 URL 或描述
        stale_hours: int       — 数据过期阈值（24 或 168）
        table_name: str        — 目标数据库表名

    子类必须实现（抽象方法）:
        fetch(self) -> list    — 从数据源拉取数据，返回列表
        store(self, conn, cursor, items) -> int  — 写入数据库，返回写入行数

    子类可选覆盖（类属性）:
        schedule_time: str     — 调度时间，默认 "06:00"
        schedule_rule: str     — 调度规则，默认 "day"（可选 "monday", "sunday"）
        timestamp_column: str  — 时间戳列名，默认 "created_at"
        update_filter: str     — get_latest_fetch_time 的额外 WHERE 条件，默认 ""
    """

    # ── 子类必须定义 ──
    name: str = ""
    data_source: str = ""
    stale_hours: int = 24
    table_name: str = ""

    # ── 子类可选覆盖 ──
    schedule_time: str = "06:00"
    schedule_rule: str = "day"       # "day" | "monday" | "sunday"
    timestamp_column: str = "created_at"
    update_filter: str = ""          # 额外 WHERE 条件，如 "description LIKE '%spider%'"

    # ── 基类提供 ──
    TZ = pytz.timezone("Asia/Shanghai")

    @property
    def db_config(self) -> dict:
        """数据库连接配置（从环境变量读取）。"""
        return {
            "host": os.getenv("DB_HOST", "localhost"),
            "user": os.getenv("DB_USER", "root"),
            "password": os.getenv("DB_PASSWORD", "123456"),
            "database": os.getenv("DB_NAME", "cuhk_campus"),
            "charset": "utf8mb4",
        }

    # ── 数据库连接 ──

    def connect_db(self):
        """建立 MySQL 连接。"""
        return mysql.connector.connect(**self.db_config)

    # ── 抽象方法 ──

    @abc.abstractmethod
    def fetch(self) -> List[Any]:
        """
        从数据源拉取数据。
        返回: 待写入的数据列表，格式由子类定义。
        """
        ...

    @abc.abstractmethod
    def store(self, conn, cursor, items: List[Any]) -> int:
        """
        将数据写入数据库。
        返回: 实际写入的行数。
        """
        ...

    # ── 可覆盖的方法 ──

    def get_latest_fetch_time(self, cursor) -> Optional[datetime]:
        """
        查询目标表中最近一次更新的时间戳。
        子类可通过覆盖 timestamp_column / update_filter 来定制，
        也可以完全重写此方法。
        """
        sql = f"SELECT MAX({self.timestamp_column}) FROM {self.table_name}"
        if self.update_filter:
            sql += f" WHERE {self.update_filter}"
        cursor.execute(sql)
        result = cursor.fetchone()
        return result[0] if result[0] else None

    # ── 共享逻辑（子类无需覆盖） ──

    def should_update(self, latest_time: Optional[datetime], force: bool = False) -> bool:
        """判断是否需要更新数据。"""
        if force:
            return True
        if not latest_time:
            return True
        now = datetime.now(self.TZ)
        if latest_time.tzinfo is None:
            latest_time = latest_time.replace(tzinfo=self.TZ)
        return (now - latest_time).total_seconds() / 3600 >= self.stale_hours

    def update_data(self, force: bool = False) -> Optional[int]:
        """
        模板方法：连接 → 检查新鲜度 → 拉取 → 写入 → 关闭。
        子类通常无需覆盖；如需自定义流程（如分科目迭代），可覆盖此方法。
        返回写入行数，或 None 表示跳过。
        """
        conn = self.connect_db()
        cursor = conn.cursor()

        try:
            latest = self.get_latest_fetch_time(cursor)
            if not self.should_update(latest, force):
                print(f"[INFO] {self.name} 数据已是最新（上次更新: {latest}），跳过。")
                return None

            print(f"[INFO] 开始抓取 {self.name} 数据...")
            items = self.fetch()
            if not items:
                print(f"[WARN] {self.name} 未获取到数据，本次跳过。")
                return 0

            count = self.store(conn, cursor, items)
            print(f"[INFO] {self.name} 成功写入 {count} 条记录。")
            return count
        finally:
            cursor.close()
            conn.close()

    def setup_scheduler(self):
        """启动 schedule 定时调度。"""
        rule_map = {
            "day": schedule.every().day,
            "monday": schedule.every().monday,
            "sunday": schedule.every().sunday,
        }
        rule = rule_map.get(self.schedule_rule, schedule.every().day)
        rule.at(self.schedule_time).do(self.update_data)

        print(f"[Scheduler] {self.name} 定时任务已启动: "
              f"每{self.schedule_rule} {self.schedule_time} (Asia/Shanghai)")
        while True:
            schedule.run_pending()
            time.sleep(60)

    def print_banner(self, force: bool, once: bool):
        """打印启动横幅。"""
        stale_desc = f">{self.stale_hours}h" if self.stale_hours <= 24 else f">{self.stale_hours // 24}天"
        mode = "强制更新" if force else f"增量更新（{stale_desc} 才拉取）"
        if once:
            mode += " | 单次执行模式"
        print("=" * 60)
        print(f"  CUHK {self.name}")
        print(f"  数据源: {self.data_source}")
        print(f"  模式: {mode}")
        print("=" * 60)

    @classmethod
    def main(cls):
        """
        标准 CLI 入口。解析 --force / --once 参数，执行更新并启动调度。
        子类可直接在 __main__ 中调用: MySpider.main()
        """
        force = "--force" in sys.argv
        once = "--once" in sys.argv

        spider = cls()
        spider.print_banner(force=force, once=once)
        spider.update_data(force=force)

        if once:
            print(f"[INFO] --once 模式，{spider.name} 更新完成，退出。")
            sys.exit(0)

        spider.setup_scheduler()
