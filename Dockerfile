# ========== 阶段1：前端打包（node构建） ==========
FROM node:20-alpine AS frontend-builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ========== 阶段2：后端运行镜像（最终镜像） ==========
FROM python:3.11-slim
WORKDIR /app

# 安装ffmpeg(视频缩略) + curl(健康检查用)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend

COPY --from=frontend-builder /app/dist /frontend/dist

EXPOSE 8000
ENV MEDIA_ROOT=/media
ENV CACHE_DIR=/cache
ENV CONFIG_DIR=/config

# 修改：访问根路径，不走鉴权接口；镜像已经安装curl
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -s -f http://127.0.0.1:8000/ > /dev/null || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
