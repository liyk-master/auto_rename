#!/bin/bash
# Docker 镜像构建和推送脚本

set -e

VERSION="${1:-latest}"
REGISTRY="${DOCKER_REGISTRY:-docker.io}"
IMAGE_NAME="${DOCKER_IMAGE:-video-organizer}"
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${VERSION}"

echo "🐳 构建 Docker 镜像: ${FULL_IMAGE}"

# 构建镜像
docker build -t "${FULL_IMAGE}" .

# 如果是 latest，也打上版本号标签
if [ "${VERSION}" != "latest" ]; then
    docker tag "${FULL_IMAGE}" "${REGISTRY}/${IMAGE_NAME}:latest"
    echo "✅ 已标记为 latest"
fi

echo "✅ 构建完成: ${FULL_IMAGE}"

# 询问是否推送
read -p "是否推送到镜像仓库? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🚀 推送镜像..."
    docker push "${FULL_IMAGE}"

    if [ "${VERSION}" != "latest" ]; then
        docker push "${REGISTRY}/${IMAGE_NAME}:latest"
    fi

    echo "✅ 推送完成"
else
    echo "⏭️  跳过推送"
fi

# 显示镜像信息
echo ""
echo "📦 镜像信息:"
docker images "${REGISTRY}/${IMAGE_NAME}" | head -2

# 显示运行命令
echo ""
echo "🚀 运行命令:"
echo "  docker run -d -p 8080:8080 --name video-organizer ${FULL_IMAGE}"
echo ""
echo "或使用 Docker Compose:"
echo "  docker compose up -d"
