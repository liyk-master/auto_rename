# Dockerfile - 使用 build.sh 进行打包
FROM python:3.12-bookworm

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    unzip \
    patchelf \
    git \
    # 字体和渲染支持
    libfontconfig1 \
    libfreetype6 \
    # 音频支持
    libasound2 \
    libpulse0 \
    && rm -rf /var/lib/apt/lists/*

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 设置工作目录
WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# 复制源代码
COPY src/ ./src/

# 复制配置文件模板
COPY config.ini .
COPY run_organizer.py .

# 复制打包脚本
COPY build.sh .

# 设置执行权限
RUN chmod +x build.sh

# 使用 build.sh 进行打包
CMD ["./build.sh"]
