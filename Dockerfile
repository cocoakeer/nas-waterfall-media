# ========== 阶段1：前端打包（node构建） ==========
FROM node:20-alpine AS frontend-builder
WORKDIR /app
# 复制前端依赖文件
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
# 复制前端全部源码
COPY frontend/ ./
# vite打包，输出dist
RUN npm run build

# ========== 阶段2：后端运行镜像（最终镜像） ==========
FROM python:3.11-slim
WORKDIR /app

# 安装ffmpeg，用于视频缩略图
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 复制后端代码 + 依赖
COPY backend ./backend
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ✅ 关键：从上面前端构建阶段，把dist复制到容器内 /frontend/dist
COPY --from=frontend-builder /app/dist /frontend/dist

EXPOSE 8000
ENV MEDIA_ROOT=/media
ENV CACHE_DIR=/cache
ENV CONFIG_DIR=/config

CMD ["python", "backend/main.py"]
