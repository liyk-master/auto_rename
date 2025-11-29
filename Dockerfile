# 视频文件自动重命名和组织工具 - Docker容器配置

# 使用官方Python运行时作为基础镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# 安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY src/ ./src/
COPY config_template.ini .

# 创建配置和日志目录
RUN mkdir -p /app/config /app/logs

# 将配置模板复制到配置目录
RUN cp config_template.ini /app/config/

# 设置卷挂载点
VOLUME ["/app/config", "/app/logs", "/watch", "/output"]

# 设置默认命令
CMD ["python", "src/video_organizer/main.py", "--config", "/app/config/config.ini"]

# 暴露元数据信息
LABEL maintainer="Your Name" \
      description="视频文件自动重命名和组织工具" \
      version="1.0.0"
