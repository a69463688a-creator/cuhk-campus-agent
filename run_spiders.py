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

# 5 个爬虫模块：key → (模块导入路径, 更新函数, 显示名称)
SPIDERS = {
    "news":     ("spiders.news",     "update_campus_news",   "📰 校园新闻"),
    "events":   ("spiders.events",   "update_campus_events", "🎉 校园活动"),
    "canteen":  ("spiders.canteen",  "update_canteen_data",  "🍽️  餐厅信息"),
    "library":  ("spiders.library",  "update_library_hours", "📖 图书馆"),
    "course":   ("spiders.course",   "update_course_data",   "📚 课程数据"),
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
    module_path, func_name, label = SPIDERS[key]
    print(f"\n{'─'*50}")
    print(f"  {label}  [{module_path}]")
    print(f"{'─'*50}")

    try:
        import importlib
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        start = time.time()
        func(force=force)
        elapsed = time.time() - start
        print(f"  {label} ✅ 完成 ({elapsed:.1f}s)")
        return True
    except Exception as e:
        print(f"  {label} ❌ 失败: {e}")
        return False


def main():
    force, targets = parse_args()

    print("=" * 60)
    print("  SmartCampus 爬虫统一入口")
    print(f"  模式: {'🔁 强制刷新' if force else '📌 增量更新'}")
    print(f"  模块: {', '.join(SPIDERS[t][2] for t in targets)}")
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
