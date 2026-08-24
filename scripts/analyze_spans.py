#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: analyze_spans.py
项目: SmartCampus — 全链路 span 日志分析
描述: 解析 logs/app.log 中的 span.start / span.end，按 span 名聚合耗时，
      输出各层 mean/P50/P95/P99，用于简历「项目成果」分层耗时分解。
用法: PYTHONPATH=. python scripts/analyze_spans.py [日志文件]
"""
import json
import re
import statistics
import sys
from collections import defaultdict

LOG_FILE = sys.argv[1] if len(sys.argv) > 1 else "logs/app.log"

# span.end 行形如: ... - {"event": "span.end", "trace_id": "...", "span_id": "...", "name": "...", "duration_ms": 12.3, "status": "ok"}
SPAN_END_RE = re.compile(r'"event":\s*"span\.end".*?"name":\s*"([^"]+)".*?"duration_ms":\s*([0-9.]+)')


def pct(data, q):
    s = sorted(data)
    if not s:
        return 0.0
    k = (len(s) - 1) * q
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def main():
    spans = defaultdict(list)
    with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = SPAN_END_RE.search(line)
            if m:
                spans[m.group(1)].append(float(m.group(2)))

    print(f"日志文件: {LOG_FILE}")
    print(f"{'span 名称':<24} {'n':>4} {'mean(ms)':>10} {'P50':>9} {'P95':>9} {'P99':>9}")
    print("-" * 72)
    for name in sorted(spans):
        samples = spans[name]
        print(f"{name:<24} {len(samples):>4} {statistics.mean(samples):>10.2f} "
              f"{pct(samples, 0.5):>9.2f} {pct(samples, 0.95):>9.2f} {pct(samples, 0.99):>9.2f}")

    print("-" * 72)
    # 汇总到 JSON
    out = {name: {"n": len(s), "mean": round(statistics.mean(s), 2),
                  "p50": round(pct(s, 0.5), 2), "p95": round(pct(s, 0.95), 2),
                  "p99": round(pct(s, 0.99), 2)}
           for name, s in spans.items()}
    with open("logs/span_summary.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("结果已写入 logs/span_summary.json")


if __name__ == "__main__":
    main()
