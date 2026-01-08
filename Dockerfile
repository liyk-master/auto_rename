# Dockerfile - 使用 PyInstaller + Alpine musl libc，最大化兼容性
FROM python:3.9-alpine

# 安装系统依赖
RUN apk add --no-cache \
    build-base \
    wget \
    patchelf \
    git

# 设置工作目录
WORKDIR /app

# 复制所有文件
COPY . .

# 转换换行符
RUN sed -i 's/\r$//' build.sh && \
    chmod +x build.sh

# 安装依赖
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir pyinstaller && \
    pip install --no-cache-dir -r requirements.txt

# 直接运行 PyInstaller（使用 -B 模式避免交互）
RUN pyinstaller -B \
    --noconfirm \
    --onefile \
    --console \
    --name "VideoOrganizer" \
    --clean \
    --hidden-import=src.video_organizer \
    --add-data "config.ini:." \
    run_organizer.py

# 显示构建结果
RUN ls -lh dist/ && \
    echo "" && \
    echo "构建完成，可执行文件: dist/VideoOrganizer"

# 容器构建完成后自动退出
CMD ["echo", "构建容器已完成，检查 dist/ 目录"]
