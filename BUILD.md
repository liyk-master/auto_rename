# GitHub Actions Build

这个项目使用 GitHub Actions 自动构建Docker镜像并部署到远程服务器运行。

## 两种运行方式

### 方式1：直接运行（推荐）
不需要构建可执行文件，直接在远程服务器上运行Docker容器。

### 方式2：GitHub Actions自动部署
代码推送后自动构建Docker镜像并部署。

## 使用Docker运行

### 1. 在远程服务器上安装Docker

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y docker.io docker-compose
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER
```

### 2. 克隆并运行

```bash
# 克隆仓库
git clone https://github.com/liyk-master/auto_rename.git
cd auto_rename

# 编辑配置文件
cp config.ini.example config.ini  # 如果有示例文件
vim config.ini

# 构建并运行
docker-compose up -d

# 查看日志
docker-compose logs -f video-organizer

# 停止运行
docker-compose down
```

### 3. 直接使用Docker命令

```bash
# 构建镜像
docker build -f Dockerfile.run -t video-organizer .

# 运行容器
docker run -d \
  --name video-organizer \
  -v /path/to/your/videos:/app/videos \
  -v $(pwd)/config.ini:/app/config.ini:ro \
  video-organizer

# 查看日志
docker logs -f video-organizer

# 停止
docker stop video-organizer
```

## 远程服务器部署

### 方式1：手动部署

```bash
# 在本地构建镜像并保存
docker build -f Dockerfile.run -t video-organizer .

# 导出为tar文件
docker save -o video-organizer.tar video-organizer

# 上传到远程服务器
scp video-organizer.tar user@remote-server:/path/to/

# 在远程服务器上加载镜像
docker load -i video-organizer.tar

# 运行容器
docker run -d \
  --name video-organizer \
  -v /path/to/videos:/app/videos \
  video-organizer
```

### 方式2：使用Docker Hub（推荐）

```bash
# 在本地登录Docker Hub
docker login

# 打标签
docker tag video-organizer yourusername/video-organizer:latest

# 推送到Docker Hub
docker push yourusername/video-organizer:latest

# 在远程服务器上拉取并运行
docker pull yourusername/video-organizer:latest
docker run -d \
  --name video-organizer \
  -v /path/to/videos:/app/videos \
  yourusername/video-organizer:latest
```

### 方式3：GitHub Actions自动部署

需要配置Docker Hub secrets和SSH密钥，实现代码推送后自动部署。

## 文件说明

| 文件 | 说明 |
|------|------|
| `Dockerfile.run` | 直接运行模式的Dockerfile |
| `docker-compose.yml` | Docker Compose配置 |
| `config.ini` | 配置文件（需要自行创建或修改） |

## 挂载目录说明

```bash
# 视频目录 - 必填
-v /your/video/path:/app/videos

# 配置文件 - 可选
-v $(pwd)/config.ini:/app/config.ini:ro

# 日志目录 - 可选
-v $(pwd)/logs:/app/logs
```

## 检查运行状态

```bash
# 查看容器状态
docker ps

# 查看日志
docker logs video-organizer

# 进入容器调试
docker exec -it video-organizer sh

# 检查资源使用
docker stats video-organizer
```