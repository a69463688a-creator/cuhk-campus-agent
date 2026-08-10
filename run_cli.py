#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动 CLI 交互界面（入口脚本）"""
import subprocess
import sys

if __name__ == "__main__":
    subprocess.run([sys.executable, "app/cli.py"])
