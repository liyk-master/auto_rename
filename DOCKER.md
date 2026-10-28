# Docker 部署指南

## 快速开始

### 1. 使用 Docker Compose（推荐）

```bash
# 克隆仓库
git clone https://github.com/liyk-master/auto_rename.git
cd auto_rename

# 创建数据目录
mkdir -p data logs strm

# 编辑 docker-compose.yml，修改挂载路径：
# - /path/to/downloads:/downloads  （你的下载目录）
# - /path/to/media:/media           （你的媒体库目录）

# 启动服务（Web + 文件监控）
docker compose up -d

# 查看日志
docker compose logs -f

# 访问 Web 管理界面
# http://localhost:8080
# 首次启动会在日志中显示随机管理员密码
```

### 2. 仅启动 Web 管理界面（不监控文件）

```bash
docker compose --profile web-only up -d video-organizer-web-only
```

### 3. 开发模式（源码挂载，改完 restart 即生效）

```bash
# 首次：构建镜像 + 启动（镜像里的源码会被 ./src 挂载覆盖）
docker compose --profile dev up -d video-organizer-dev --build
# 之后改代码只需重启进程，不用 build
docker compose restart video-organizer-dev
```

## 使用 Docker 命令

### 构建镜像

```bash
docker build -t video-organizer:latest .
```

### 运行容器

```bash
docker run -d \
  --name video-organizer \
  --restart unless-stopped \
  -p 8080:8080 \
  -v $(pwd)/data/config.ini:/app/config.ini \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/strm:/app/strm \
  -v /path/to/downloads:/downloads \
  -v /path/to/media:/media \
  -e TZ=Asia/Shanghai \
  video-organizer:latest
```

### 查看日志

```bash
docker logs -f video-organizer
```

### 进入容器

```bash
docker exec -it video-organizer sh
```

### 停止和删除

```bash
docker stop video-organizer
docker rm video-organizer
```

## 配置说明

### 目录挂载

| 容器路径 | 宿主机路径 | 说明 |
|---------|-----------|------|
| `/app/config.ini` | `./data/config.ini` | 配置文件（首次启动自动生成）|
| `/app/data` | `./data` | 数据目录（秒传信息、数据库等）|
| `/app/logs` | `./logs` | 日志目录 |
| `/app/strm` | `./strm` | STRM 文件输出目录 |
| `/downloads` | 你的下载目录 | 监控的下载目录 |
| `/media` | 你的媒体库目录 | 整理后的输出目录 |

### 环境变量

| 变量 | 默认值 | 说明 |
|-----|--------|------|
| `TZ` | `Asia/Shanghai` | 时区 |
| `PYTHONUNBUFFERED` | `1` | Python 输出不缓冲 |
| `LOG_LEVEL` | `INFO` | 日志级别（DEBUG/INFO/WARNING/ERROR）|

### 端口

- `8080` - Web 管理界面

## 首次配置

### 1. 获取管理员密码

首次启动时，容器会生成随机管理员密码并输出到日志：

```bash
docker compose logs | grep "管理员密码"
```

### 2. 修改配置

访问 `http://localhost:8080`，使用管理员密码登录后，在"配置管理"页面修改：

- `[monitoring]` - 监控目录设置为 `/downloads`
- `[monitoring]` - 输出目录设置为 `/media`
- `[tmdb]` - 填入你的 TMDB API Key
- `[yun139]` / `[cloud189]` / `[emos]` - 配置云盘上传（可选）

或直接编辑 `./data/config.ini` 文件，然后重启容器：

```bash
docker compose restart
```

### 3. 配置下载器监控（可选）

如果使用 aria2 或 qBittorrent：

```ini
[downloader.aria2]
enabled = True
url = http://aria2:6800/jsonrpc
secret = your_secret

[downloader.qbittorrent]
enabled = True
url = http://qbittorrent:8080
username = admin
password = admin
```

**注意**：如果下载器也在 Docker 中运行，使用容器名或网络 IP，而不是 `localhost`。

## 路径映射

如果你的下载器在 Docker 中运行，需要配置路径映射：

```ini
[monitoring]
path_mappings = {
    "/downloads": "/media/downloads"
}
```

例如，qBittorrent 容器中的路径是 `/downloads/video.mkv`，在宿主机是 `/media/downloads/video.mkv`。

## 常见问题

### 1. 权限问题

容器使用 `appuser` (UID 1000) 运行，确保挂载目录有读写权限：

```bash
sudo chown -R 1000:1000 data logs strm
```

或修改 Dockerfile 中的 UID：

```dockerfile
RUN useradd -m -u YOUR_UID appuser
```

### 2. 配置文件不生效

- 确保配置文件路径正确挂载
- 修改配置后需要重启容器：`docker compose restart`

### 3. 无法访问 Web 界面

- 检查防火墙是否开放 8080 端口
- 检查容器是否正常运行：`docker compose ps`
- 查看日志：`docker compose logs -f`

### 4. 找不到下载的文件

- 检查目录挂载是否正确
- 如果下载器在 Docker 中，检查路径映射配置
- 查看日志：`docker compose logs | grep "找不到"`

### 5. 云盘上传失败

- 检查网络连接
- 验证云盘账号配置是否正确
- 查看详细错误：`docker compose logs | grep "上传"`

## 更新

### 只改了 Python 代码：不用重新构建

把源码目录挂进容器（`docker-compose.yml` 的 `video-organizer-dev`、线上 `docker-compose.yml.tmp`
都已经这么配了），容器跑的就是宿主机上的 `src/`：

```yaml
    volumes:
      - ./src:/app/src        # 关键：覆盖镜像里 COPY 进去的源码
```

```bash
# 改完代码只需重启进程，秒级生效，完全不碰 build
docker compose restart video-organizer
# 看日志确认起来了
docker compose logs -f --tail=50 video-organizer
```

仅当**依赖或 Dockerfile 变化**（`requirements.txt` 加了包）时才需要重建：

```bash
docker compose build video-organizer && docker compose up -d video-organizer
```

> 不要用 `:ro` 挂 `./src`：数据库文件在 `src/video_organizer/data/video_organizer.db`，
> 只读挂载会让程序无法写库。

### 构建慢（`apk add ...` 600s+ / pip 拉不下来）

`Dockerfile.run` 已从 `python:3.12-alpine` 换成 **`python:3.12-slim` 多阶段**：alpine 是 musl，
依赖没有预编译 wheel 就得现场编译，所以必须先 `apk add build-base gcc`，而这一步在国内源上
经常 600 秒起；换成 glibc 的 slim 后绝大多数依赖直接下 manylinux wheel，编译与 apk 全部消失。

如果还是要重建依赖层，再加两个开关（`docker-compose.yml` 的 `build.args`）：

```yaml
    build:
      context: .
      dockerfile: Dockerfile.run
      args:
        # Docker 预定义 build arg，不用在 Dockerfile 里声明；让 apt/pip 走代理
        HTTP_PROXY: http://192.168.1.2:7890
        HTTPS_PROXY: http://192.168.1.2:7890
        # 换国内源（代理可用时一般不需要）
        # APT_MIRROR: mirrors.aliyun.com
        # PIP_INDEX: https://pypi.tuna.tsinghua.edu.cn/simple
```

另外 `Dockerfile.run` 的 pip 层用了 BuildKit cache mount：`pip` 下载过的包会留在构建器里，
即使依赖层被 invalidate 也不会重新下载（`docker builder prune` 才会清掉）。
需要 Docker 23+（BuildKit 默认开启）；老版本加 `DOCKER_BUILDKIT=1 docker compose build`。

构建日志里如果看到 `load metadata for docker.io/docker/dockerfile`，说明 Dockerfile 首行有
`syntax=` 指令在拉外部 frontend，网络不通时删掉该行即可（本项目已不再使用）。

### 其他提速点

- `.dockerignore` 已经排掉 `logs/ data/ strm/ build/ dist/ .git/`，构建上下文从几百 MB 降到几 MB
- 依赖层与代码层分离：`COPY requirements.txt` → `pip install` → 再 `COPY src/`，只改代码时依赖层命中缓存
- `docker compose down` 不影响构建缓存；真要让磁盘回到干净状态用 `docker system prune`

### 备份数据

```bash
# 备份配置和数据
tar -czf backup-$(date +%Y%m%d).tar.gz data/ logs/
```

## 性能优化

### 调整资源限制

在 `docker-compose.yml` 中添加：

```yaml
services:
  video-organizer:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          memory: 512M
```

### 使用 tmpfs 加速（可选）

```yaml
services:
  video-organizer:
    tmpfs:
      - /tmp:size=1G
```

## 多实例部署

如果需要同时管理多个下载目录：

```bash
# 实例 1
docker compose -p organizer1 -f docker-compose.yml up -d

# 实例 2 - 修改端口和挂载目录
docker compose -p organizer2 -f docker-compose-2.yml up -d
```

## 监控和维护

### 健康检查

```bash
docker inspect video-organizer | grep -A 10 Health
```

### 资源使用

```bash
docker stats video-organizer
```

### 日志轮转

建议配置日志轮转，在 `docker-compose.yml` 中添加：

```yaml
services:
  video-organizer:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```
