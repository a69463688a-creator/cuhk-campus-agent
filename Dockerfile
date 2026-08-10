# SmartCampus — CUHK 校园生活助手 Docker 镜像
# 构建: docker build -t smartcampus .
FROM python:3.11-slim

WORKDIR /app

# 系统依赖（curl 用于健康检查）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 源代码
COPY . .

# 暴露端口
EXPOSE 8100

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:8100/health || exit 1

# 入口
ENTRYPOINT ["python", "docker-entrypoint.py"]
