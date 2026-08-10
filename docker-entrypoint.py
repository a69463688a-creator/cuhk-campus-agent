#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
docker-entrypoint.py — 容器启动入口
按顺序启动: MCP Servers → A2A Agents → Web Server
"""
import subprocess
import sys
import time
import os
import signal
import urllib.request

PROCS = []


def log(msg: str):
    print(f"[entrypoint] {msg}", flush=True)


def start_service(name: str, cmd: list[str]) -> subprocess.Popen:
    """后台启动一个服务"""
    log(f"启动 {name}: {' '.join(cmd)}")
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", "/app")
    proc = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr, env=env)
    PROCS.append(proc)
    return proc


def wait_for_http(url: str, label: str, timeout: int = 60, interval: int = 2) -> bool:
    """轮询等待 HTTP 端点就绪"""
    log(f"等待 {label} ({url}) ...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=2)
            if resp.status in (200, 400, 405, 406):  # MCP /mcp GET 返回 400/405/406
                log(f"{label} ✅ 就绪 ({resp.status})")
                return True
        except urllib.error.HTTPError as e:
            if e.code in (400, 405, 406):
                log(f"{label} ✅ 就绪 ({e.code})")
                return True
        except Exception:
            pass
        time.sleep(interval)
    log(f"{label} ❌ 超时 ({timeout}s)")
    return False


def cleanup(signum=None, frame=None):
    """优雅关闭所有子进程"""
    log("收到终止信号，关闭所有服务...")
    for proc in PROCS:
        try:
            proc.terminate()
        except Exception:
            pass
    for proc in PROCS:
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    log("所有服务已关闭")
    sys.exit(0)


def wait_for_mysql(host: str, user: str, password: str, database: str, timeout: int = 60):
    """等待 MySQL 就绪"""
    log(f"等待 MySQL ({host}/{database}) ...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=host, user=user, password=password,
                database=database, charset="utf8mb4", connection_timeout=3
            )
            conn.close()
            log("MySQL ✅ 就绪")
            return True
        except Exception:
            time.sleep(3)
    log("MySQL ❌ 超时")
    return False


def main():
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    python = sys.executable

    # ── 0. 等待 MySQL ──
    db_host = os.getenv("DB_HOST", "localhost")
    db_user = os.getenv("DB_USER", "root")
    db_pass = os.getenv("DB_PASSWORD", "123456")
    db_name = os.getenv("DB_NAME", "cuhk_campus")
    if not wait_for_mysql(db_host, db_user, db_pass, db_name):
        log("MySQL 不可用，退出。") ; sys.exit(1)

    # ── 1. MCP Servers ──
    mcp_course   = start_service("Course MCP (8002)",   [python, "mcp_servers/course_server.py"])
    mcp_facility = start_service("Facility MCP (8001)",  [python, "mcp_servers/facility_server.py"])

    if not wait_for_http("http://127.0.0.1:8002/mcp",   "Course MCP"):
        cleanup()
    if not wait_for_http("http://127.0.0.1:8001/mcp",   "Facility MCP"):
        cleanup()

    # ── 2. A2A Agents ──
    agent_course   = start_service("Course Agent (5005)",   [python, "agents/course_agent.py"])
    agent_facility = start_service("Facility Agent (5006)", [python, "agents/facility_agent.py"])

    if not wait_for_http("http://127.0.0.1:5005/.well-known/agent-card.json", "Course Agent", timeout=90):
        cleanup()
    if not wait_for_http("http://127.0.0.1:5006/.well-known/agent-card.json", "Facility Agent", timeout=90):
        cleanup()

    # ── 3. Web Server (前台) ──
    log("启动 Web Server (8100) ...")
    os.execl(python, python, "run_web.py")  # 替换当前进程


if __name__ == "__main__":
    main()
