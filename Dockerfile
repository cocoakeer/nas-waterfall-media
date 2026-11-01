# ========== 阶段1：前端打包（node构建） ==========
FROM node:20-alpine AS frontend-builder
WORKDIR /app
# 利用docker缓存：先复制依赖再复制源码
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ========== 阶段2：后端运行镜像（最终镜像） ==========
FROM python:3.11-slim
WORKDIR /app

# 安装ffmpeg + 基础工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 复制后端依赖 & 代码
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend

# 复制前端构建产物
COPY --from=frontend-builder /app/dist /frontend/dist

EXPOSE 8000
ENV MEDIA_ROOT=/media
ENV CACHE_DIR=/cache
ENV CONFIG_DIR=/config

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -s http://127.0.0.1:8000/api/list || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
