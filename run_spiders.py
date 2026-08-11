#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: run_spiders.py
项目: SmartCampus
描述: 爬虫统一入口 — 批量 / 指定模块更新所有数据源
用法:
    python run_spiders.py                  # 全部增量更新
    python run_spiders.py --force          # 全部强制刷新
    python run_spiders.py canteen news     # 只更新指定模块
    python run_spiders.py --force course   # 强制刷新指定模块
"""
import sys
import time

from spiders.news import NewsSpider
from spiders.events import EventsSpider
from spiders.canteen import CanteenSpider
from spiders.library import LibrarySpider
from spiders.course import CourseSpider

# 5 个爬虫：key → (类, 显示名称)
SPIDERS = {
    "news":    (NewsSpider,    "校园新闻"),
    "events":  (EventsSpider,  "校园活动"),
    "canteen": (CanteenSpider, "餐厅信息"),
    "library": (LibrarySpider, "图书馆"),
    "course":  (CourseSpider,  "课程数据"),
}

ALL_KEYS = list(SPIDERS.keys())


def parse_args():
    """解析命令行参数，返回 (force, targets)"""
    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    targets = [a.lower() for a in args if a.lower() in SPIDERS]
    # 没指定 → 全跑
    if not targets:
        targets = ALL_KEYS
    return force, targets


def run_one(key: str, force: bool) -> bool:
    """运行单个爬虫，返回是否成功"""
    cls, label = SPIDERS[key]
    spider = cls()
    print(f"\n{'─'*50}")
    print(f"  {label}  [{spider.name}]")
    print(f"{'─'*50}")

    try:
        start = time.time()
        result = spider.update_data(force=force)
        elapsed = time.time() - start
        if result is not None:
            print(f"  {label} 完成 ({elapsed:.1f}s) — {result} 条记录")
        else:
            print(f"  {label} 跳过 ({elapsed:.1f}s) — 数据已是最新")
        return True
    except Exception as e:
        print(f"  {label} 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    force, targets = parse_args()

    print("=" * 60)
    print("  SmartCampus 爬虫统一入口")
    print(f"  模式: {'强制刷新' if force else '增量更新'}")
    print(f"  模块: {', '.join(SPIDERS[t][1] for t in targets)}")
    print("=" * 60)

    start_all = time.time()
    ok = 0
    fail = 0

    for key in targets:
        if run_one(key, force):
            ok += 1
        else:
            fail += 1

    elapsed = time.time() - start_all
    print(f"\n{'='*60}")
    print(f"  总计: {ok} 成功 / {fail} 失败 | 耗时 {elapsed:.1f}s")
    print(f"{'='*60}")

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
