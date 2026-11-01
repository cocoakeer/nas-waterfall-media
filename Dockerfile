# ========== 阶段1：编译前端 ==========
FROM node:20-alpine AS frontend-builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ========== 阶段2：后端最终镜像 ==========
FROM python:3.11-slim
WORKDIR /app

# 安装系统依赖（ffmpeg用于视频信息读取）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 安装python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY backend/ ./backend/

# ✅ 重点：从上一个构建阶段复制前端打包好的dist，映射到 /app/static
COPY --from=frontend-builder /app/dist ./static

# 环境变量
ENV NAS_MEDIA_PATH=/media
ENV SLIDESHOW_DEFAULT_INTERVAL=3000
ENV PORT=8000

EXPOSE 8000
CMD ["python", "backend/main.py"]
