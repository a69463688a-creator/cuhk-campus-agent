#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动 Web 服务器（入口脚本）"""
import os
import sys
import uvicorn

if __name__ == "__main__":
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 8080))
    print(f"\n{'='*60}")
    print(f"  SmartCampus Web 服务器 v3.1")
    print(f"  访问地址: http://localhost:{port}")
    print(f"  API 文档:  http://localhost:{port}/docs")
    print(f"{'='*60}\n")
    uvicorn.run("app.server:app", host=host, port=port, reload=False)
