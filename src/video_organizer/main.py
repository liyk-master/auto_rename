import os
import sys
import signal
import threading
from pathlib import Path
from typing import Optional, Dict, Any

# 添加项目根目录到Python路径
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


# 导入配置加载器
from .core.config_loader import load_config, save_default_config

# 导入监控器和处理器
from .core.filesystem_monitor import FileSystemMonitor
from .core.video_file_handler import VideoFileHandler
from .core.downloader_monitor import DownloaderMonitorFactory

# 导入日志工具
from .utils.logging_utils import get_logger, setup_logging

# 导入命令行工具
from .utils.cli_parser import get_cli_parser
from .utils.cli_output import get_cli_output

# 导入 Web 服务
from .web.services.state import get_state_manager

# 应用版本信息
__version__ = "1.0.0"


# 创建命令行输出实例
cli_output = get_cli_output()


def signal_handler(sig: int, frame) -> None:
    """
    信号处理器

    Args:
        sig: 信号编号
        frame: 当前栈帧
    """
    logger = get_logger(__name__)
    logger.info(f"接收到信号 {sig}，正在停止服务...")
    cli_output.print_info("接收到退出信号，正在停止服务...")
    sys.exit(0)


def setup_signal_handlers() -> None:
    """
    设置信号处理器
    """
    signal.signal(signal.SIGINT, signal_handler)  # 处理Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # 处理终止信号


def initialize_monitor(
    config: dict, cli_options: Optional[Dict[str, Any]] = None
) -> Optional[FileSystemMonitor]:
    """
    初始化文件系统监控器

    Args:
        config: 配置字典
        cli_options: 命令行选项

    Returns:
        文件系统监控器实例或None
    """
    logger = get_logger(__name__)

    try:
        # 获取监控配置
        monitoring_config = config.get("monitoring", {})

        # 默认值
        watch_dir = ""
        output_dir = ""
        supported_extensions = []
        poll_interval = 1
        use_polling = False
        polling_interval = 5

        # 先尝试从命令行选项获取配置
        if cli_options:
            watch_dir = cli_options.get("watch_dir", watch_dir)
            output_dir = cli_options.get("output_dir", output_dir)
            poll_interval = cli_options.get("poll_interval", poll_interval)
            use_polling = cli_options.get("use_polling", use_polling)
            polling_interval = cli_options.get("polling_interval", polling_interval)

        # 如果命令行没有提供，则从配置文件获取
        if not watch_dir:
            watch_dir = monitoring_config.get("watch_dir", "")
        if not output_dir:
            output_dir = monitoring_config.get("output_dir", "")
        if not supported_extensions:
            supported_extensions = monitoring_config.get("supported_extensions", [])
        if poll_interval == 1:
            poll_interval = monitoring_config.get("poll_interval", 1)
        if not use_polling:
            use_polling = monitoring_config.get("use_polling", False)
        if polling_interval == 5:
            polling_interval = monitoring_config.get("polling_interval", 5)

        # 在下载器监控模式下，不再强制要求监控目录
        if not watch_dir:
            cli_output.print_info("监控目录未配置，当前使用下载器监控模式")
            logger.info("监控目录未配置，当前使用下载器监控模式")
        elif not os.path.exists(watch_dir):
            cli_output.print_info(
                f"监控目录不存在: {watch_dir}，当前使用下载器监控模式"
            )
            logger.info(f"监控目录不存在: {watch_dir}，当前使用下载器监控模式")

        # 输出目录不再强制要求，只在配置时尝试创建
        if output_dir and not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
                cli_output.print_success(f"创建输出目录: {output_dir}")
                logger.info(f"创建输出目录: {output_dir}")
            except Exception as e:
                cli_output.print_info(f"创建输出目录失败: {e}，当前使用下载器监控模式")
                logger.info(f"创建输出目录失败: {e}，当前使用下载器监控模式")

        # FileSystemMonitor会自己创建和初始化必要的组件，包括event_handler

        # 从配置中获取Emos配置
        emos_config = config.get("emos", {})

        # 从配置中获取下载器配置
        downloader_configs = config.get("downloaders", [])

        # 创建并启动文件系统监控器
        monitor = FileSystemMonitor(
            watch_path=watch_dir,
            processed_path=output_dir,
            tmdb_api_key=config.get("tmdb", {}).get("api_key", ""),
            ai_service_url=None,
            supported_extensions=supported_extensions,
            use_polling=use_polling,
            polling_interval=polling_interval,
            naming_rules=config.get("naming_rules"),
            emos_config=emos_config,
            processing_config=config.get("processing"),
            downloader_configs=downloader_configs,
            config=config,  # 传递配置对象，用于路径映射等功能
        )

        # 父监控器引用已在FileSystemMonitor内部设置

        cli_output.print_success("文件系统监控器初始化成功")
        logger.info(
            "文件系统监控器初始化成功",
            extra={
                "watch_dir": watch_dir,
                "output_dir": output_dir,
                "extensions": str(supported_extensions),
                "mode": "polling" if use_polling else "event_listening",
            },
        )

        return monitor

    except KeyError as e:
        cli_output.print_error(f"配置中缺少必要的键", error=e)
        logger.error(f"配置中缺少必要的键: {e}")
        return None
    except Exception as e:
        cli_output.print_error(f"初始化监控器失败", error=e)
        logger.exception("初始化监控器失败")
        return None


def force_process_file(file_path: str, config: dict) -> bool:
    """
    强制处理指定文件

    Args:
        file_path: 文件路径
        config: 配置字典

    Returns:
        bool: 是否处理成功
    """
    logger = get_logger(__name__)

    try:
        # 从配置中获取输出目录和命名规则
        monitoring_config = config.get("monitoring", {})
        output_dir = monitoring_config.get("output_dir", "")
        supported_extensions = monitoring_config.get("supported_extensions", [])

        # DEBUG: 打印监控配置中的路径映射
        print(
            f"DEBUG: force_process_file - Config mappings: {monitoring_config.get('path_mappings')}"
        )

        naming_rules = config.get("naming_rules")
        tmdb_config = config.get("tmdb")
        emos_config = config.get("emos", {})
        p123_config = config.get("p123", {})
        cloud189_config = config.get("cloud189", {})
        yun139_config = config.get("yun139", {})

        # DEBUG: 打印 TMDB 配置
        print(f"DEBUG: TMDB config: {tmdb_config}")
        if tmdb_config:
            print(f"DEBUG: TMDB API key exists: {'Yes' if tmdb_config.get('api_key') else 'No'}")

        # 验证文件存在
        if not os.path.exists(file_path):
            cli_output.print_error(f"文件不存在: {file_path}")
            return False

        # 如果没有配置输出目录，使用文件所在目录
        if not output_dir:
            output_dir = os.path.dirname(file_path)
            cli_output.print_info(f"未配置输出目录，使用文件所在目录: {output_dir}")

        # 验证输出目录
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            cli_output.print_success(f"创建输出目录: {output_dir}")

        # 创建文件处理器
        handler = VideoFileHandler(
            output_dir=output_dir,
            supported_extensions=supported_extensions,
            naming_rules=naming_rules,
            tmdb_config=tmdb_config,
            emos_config=emos_config,
            p123_config=p123_config,
            cloud189_config=cloud189_config,
            yun139_config=yun139_config,
            processing_config=config.get("processing"),
            path_mappings=monitoring_config.get("path_mappings"),
            telegram_config=config.get("telegram"),
            config=config,
            emya_db_config=config.get("emya_db"),  # 传递 emya 数据库配置
        )

        # 初始化并添加下载器（用于任务清理）
        # 注意：这里我们只初始化下载器用于删除任务，不需要回调处理
        downloader_configs = config.get("downloaders", [])
        if downloader_configs:
            cli_output.print_info(
                f"正在初始化 {len(downloader_configs)} 个下载器以支持任务清理..."
            )
            for dl_config in downloader_configs:
                try:
                    # 复制配置并将支持的扩展名添加进去，因为Factory需要
                    dl_config_ext = dl_config.copy()
                    dl_config_ext["supported_extensions"] = tuple(supported_extensions)

                    # 创建监控器，传入空回调因为我们只用它来执行删除操作
                    monitor = DownloaderMonitorFactory.create_monitor(
                        dl_config.get("type"), lambda path, m=None: None, dl_config_ext
                    )

                    if monitor:
                        handler.add_downloader(monitor)
                        # cli_output.print_info(f"已加载下载器: {dl_config.get('type')}")
                except Exception as e:
                    logger.error(f"初始化下载器失败: {e}")

        # 收集待处理文件
        files_to_process = []
        if os.path.isdir(file_path):
            cli_output.print_info(f"正在扫描目录: {file_path}")
            for root, dirs, files in os.walk(file_path):
                for file in files:
                    # 检查扩展名
                    if any(file.lower().endswith(ext) for ext in supported_extensions):
                        full_path = os.path.join(root, file)
                        files_to_process.append(full_path)
            cli_output.print_info(f"找到 {len(files_to_process)} 个视频文件")
        else:
            files_to_process.append(file_path)

        if not files_to_process:
            cli_output.print_warning("未找到可处理的视频文件")
            return True

        # 批量处理文件
        success_count = 0
        total_files = len(files_to_process)

        for index, current_file in enumerate(files_to_process, 1):
            cli_output.print_info(
                f"[{index}/{total_files}] 开始处理文件: {current_file}"
            )
            if handler.force_process_file(current_file):
                success_count += 1
                cli_output.print_success(f"已加入队列: {current_file}")
            else:
                cli_output.print_error(f"处理失败: {current_file}")

        cli_output.print_separator()
        cli_output.print_info(f"处理统计: 成功加入队列 {success_count}/{total_files}")

        if success_count > 0:
            # 等待上传队列完成
            if handler._use_queue and handler._queue_running:
                cli_output.print_info("等待后台处理完成 (按Ctrl+C可强制退出)...")
                try:
                    # 循环检查队列是否为空，这样可以响应中断
                    import time

                    while (
                        not handler._upload_queue.empty()
                        or handler._processing_files
                        or handler._uploading_files
                    ):
                        time.sleep(0.5)

                    # 额外等待一点时间确保所有状态更新
                    time.sleep(1)
                    cli_output.print_success("所有任务已处理完成")
                except KeyboardInterrupt:
                    cli_output.print_warning("用户中断等待，后台任务可能仍在运行")

        # 停止上传队列线程
        handler.stop_upload_queue()

        return success_count > 0

    except Exception as e:
        cli_output.print_error(f"处理文件时发生错误", error=e)
        logger.error(f"处理文件时发生错误: {e}")
        return False


def display_config(config: dict) -> None:
    """
    显示当前配置

    Args:
        config: 配置字典
    """
    cli_output.print_header("当前配置")
    cli_output.print_separator()

    # 显示监控配置
    cli_output.print_info("监控配置:")
    monitoring_config = config.get("monitoring", {})
    print(f"  监控目录: {monitoring_config.get('watch_dir', '未设置')}")
    print(f"  输出目录: {monitoring_config.get('output_dir', '未设置')}")
    print(f"  轮询间隔: {monitoring_config.get('poll_interval', 1)} 秒")
    print(f"  使用轮询: {monitoring_config.get('use_polling', False)}")
    print(f"  轮询模式间隔: {monitoring_config.get('polling_interval', 5)} 秒")
    print(
        f"  支持的扩展名: {', '.join(monitoring_config.get('supported_extensions', []))}"
    )

    cli_output.print_separator()

    # 显示命名规则
    cli_output.print_info("命名规则:")
    naming_rules = config.get("naming_rules", {})
    print(f"  电视剧格式: {naming_rules.get('tv_show', '未设置')}")
    print(f"  电影格式: {naming_rules.get('movie', '未设置')}")
    print(f"  动画格式: {naming_rules.get('anime', '未设置')}")
    print(f"  简单格式: {naming_rules.get('simple', '未设置')}")

    cli_output.print_separator()

    # 显示TMDB配置
    cli_output.print_info("TMDB配置:")
    tmdb_config = config.get("tmdb", {})
    print(f"  API密钥: {'已设置' if tmdb_config.get('api_key') else '未设置'}")
    print(f"  语言: {tmdb_config.get('language', 'zh-CN')}")
    print(f"  地区: {tmdb_config.get('region', 'CN')}")
    print(f"  重试次数: {tmdb_config.get('retry_count', 3)}")
    print(f"  超时时间: {tmdb_config.get('timeout', 30)} 秒")

    cli_output.print_separator()


def start_web_server(
    host: str,
    port: int,
    video_handler: Optional[Any] = None,
    config: Optional[dict] = None,
    config_path: Optional[Path] = None,
    downloader_monitors: Optional[list] = None,
    reload: bool = False,
) -> threading.Thread:
    """
    在后台线程启动 Web 服务器

    Args:
        host: 监听地址
        port: 监听端口
        video_handler: VideoFileHandler 实例
        config: 配置字典
        config_path: 配置文件路径
        downloader_monitors: 下载器监控器列表
        reload: 是否启用热重载

    Returns:
        Web 服务器线程
    """
    logger = get_logger(__name__)

    def run_web():
        try:
            from .web.app import create_app
            import uvicorn

            # 初始化状态管理器
            state = get_state_manager()
            if video_handler is not None:
                state.set_video_handler(video_handler)
            if config is not None:
                state.set_config(config, config_path)
            if downloader_monitors is not None:
                state.set_downloader_monitors(downloader_monitors)

            # 创建应用
            app = create_app()

            logger.info(f"Web 管理后台启动于 http://{host}:{port}")
            cli_output.print_success(f"Web 管理后台: http://{host}:{port}")

            # 运行服务器
            uvicorn.run(
                app,
                host=host,
                port=port,
                log_level="warning",  # 减少 uvicorn 日志输出
            )

        except ImportError as e:
            logger.error(f"Web 服务依赖缺失: {e}")
            cli_output.print_error(
                "Web 服务依赖缺失，请安装: pip install fastapi uvicorn"
            )
        except Exception as e:
            logger.error(f"Web 服务启动失败: {e}")
            cli_output.print_error(f"Web 服务启动失败: {e}")

    # 在后台线程启动
    web_thread = threading.Thread(target=run_web, daemon=True, name="WebServer")
    web_thread.start()

    return web_thread


def main() -> None:
    """
    主函数
    """
    # 解析命令行参数
    parser = get_cli_parser()
    args = parser.parse_args()

    # 显示版本信息
    if args.version:
        cli_output.print_header(f"视频文件自动重命名和组织工具 v{__version__}")
        print("\n一个强大的工具，可以自动识别、重命名和组织您的视频文件。")
        print("支持从TMDB获取元数据，自动分类电视剧、电影和动漫。")
        sys.exit(0)

    try:
        # 加载配置
        config_path = args.config
        # 让load_config处理默认路径逻辑，它能正确处理打包后的环境

        config = load_config(config_path)

        # DEBUG: 打印主函数加载的路径映射
        print(
            f"DEBUG: main() - Loaded config mappings: {config.get('monitoring', {}).get('path_mappings')}"
        )

        # 初始化日志系统
        setup_logging(config.get("logging", {}))

        # 设置信号处理器
        setup_signal_handlers()

        # 应用命令行选项到配置
        cli_options = {}

        # 显示配置
        if args.show_config:
            display_config(config)
            sys.exit(0)

        # 123网盘整理模式
        if args.organize_p123:
            from .upload.p123_organizer import P123Organizer

            cli_output.print_header("123网盘整理模式")

            p123_config = config.get("p123", {})
            tmdb_config = config.get("tmdb", {})
            token = p123_config.get("token", "")
            organize_source_id = int(p123_config.get("organize_source_id", 0))
            organize_target_id = int(p123_config.get("organize_target_id", 0))
            max_workers = int(p123_config.get("max_workers", 2))
            tmdb_api_key = tmdb_config.get("api_key", "")

            if not token:
                cli_output.print_error("123云盘 token 未配置")
                sys.exit(1)

            if organize_source_id == 0 or organize_target_id == 0:
                cli_output.print_error(
                    "请先配置 organize_source_id 和 organize_target_id"
                )
                cli_output.print_info("在 config.ini 的 [p123] 段落中添加:")
                cli_output.print_info("  organize_source_id = 源目录ID")
                cli_output.print_info("  organize_target_id = 目标目录ID")
                sys.exit(1)

            organizer = P123Organizer(
                token=token,
                organize_source_id=organize_source_id,
                organize_target_id=organize_target_id,
                max_workers=max_workers,
                tmdb_api_key=tmdb_api_key,
            )

            if not organizer.is_available():
                cli_output.print_error("123云盘整理功能不可用（p123client未安装）")
                sys.exit(1)

            dry_run = args.organize_dry_run
            if dry_run:
                cli_output.print_warning("试运行模式：只显示，不实际执行")

            cli_output.print_info(f"源目录ID: {organize_source_id}")
            cli_output.print_info(f"目标目录ID: {organize_target_id}")

            # 使用流式处理（适用于大量文件）
            cli_output.print_info("使用流式处理模式（适用于大量文件）")
            result = organizer.organize_streaming(
                source_id=organize_source_id,
                target_id=organize_target_id,
                dry_run=dry_run,
                show_progress=True,
            )

            cli_output.print_separator()
            cli_output.print_info("整理完成!")
            cli_output.print_info(f"  成功: {result['success']}")
            cli_output.print_info(f"  失败: {result['failed']}")
            cli_output.print_info(f"  跳过: {result['skipped']}")
            cli_output.print_info(f"  总计: {result['total']}")

            if result["errors"]:
                cli_output.print_warning("错误列表:")
                for error in result["errors"][:10]:  # 只显示前10个
                    cli_output.print_error(f"  - {error}")
                if len(result["errors"]) > 10:
                    cli_output.print_info(f"  ... 共 {len(result['errors'])} 个错误")

            sys.exit(0)

        # 强制处理文件模式
        if args.process:
            cli_output.print_header("强制处理模式")
            success = force_process_file(args.process, config)
            sys.exit(0 if success else 1)

        cli_output.print_header(f"视频文件自动重命名和组织工具 v{__version__}")
        cli_output.print_info("启动中...")

        # 获取 logger 实例
        logger = get_logger(__name__)

        # 仅 Web 模式
        if args.web_only:
            cli_output.print_info("仅启动 Web 管理后台...")

            # 初始化状态管理器
            state = get_state_manager()
            state.set_config(config, Path(config_path) if config_path else None)
            state.set_system_running(False)

            # 在 web-only 模式下也初始化云盘客户端（供 strm 端点使用）
            yun139_cfg = config.get("yun139", {})
            raw_auth = yun139_cfg.get("authorization", "")
            yun139_auth = str(raw_auth).split("#")[0].split(";")[0].strip()
            if yun139_auth:
                try:
                    from .upload.upload_yun139 import Yun139Uploader
                    uploader = Yun139Uploader(
                        authorization=yun139_auth,
                        cloud_type=yun139_cfg.get("cloud_type", "personal_new"),
                        cloud_id=yun139_cfg.get("cloud_id", ""),
                        parent_id=yun139_cfg.get("parent_id", "/"),
                        custom_part_size=int(yun139_cfg.get("custom_part_size", 0)),
                        app_mode=yun139_cfg.get("app_mode", False),
                    )
                    # 创建一个轻量 handler 容器，仅暴露 yun139_uploader
                    class _MinimalHandler:
                        pass
                    handler = _MinimalHandler()
                    handler.yun139_uploader = uploader
                    state.set_video_handler(handler)
                    cli_output.print_success("139云盘客户端已初始化")
                except Exception as e:
                    cli_output.print_warning(f"139云盘客户端初始化失败: {e}")

            # 启动 Web 服务（主线程运行）
            try:
                from .web.app import create_app
                import uvicorn

                app = create_app()
                cli_output.print_success(f"Web 管理后台启动于 http://{args.web_host}:{args.web_port}")
                cli_output.print_info("按 Ctrl+C 停止服务")
                cli_output.print_separator()

                uvicorn.run(
                    app,
                    host=args.web_host,
                    port=args.web_port,
                    reload=args.web_reload,
                )
            except ImportError:
                cli_output.print_error("Web 服务依赖缺失，请安装: pip install fastapi uvicorn")
                sys.exit(1)
            sys.exit(0)

        # 初始化监控器
        monitor = initialize_monitor(config, cli_options)
        if not monitor:
            cli_output.print_error("监控器初始化失败，程序退出")
            sys.exit(1)

        # 启动 Web 服务（如果请求）
        web_thread = None
        if args.web:
            # 获取视频处理器和下载器监控器
            video_handler = getattr(monitor, "event_handler", None)
            downloader_monitors = getattr(monitor, "downloader_monitors", [])

            web_thread = start_web_server(
                host=args.web_host,
                port=args.web_port,
                video_handler=video_handler,
                config=config,
                config_path=Path(config_path) if config_path else None,
                downloader_monitors=downloader_monitors,
                reload=args.web_reload,
            )

        # 启动 Media Tracker 监听客户端
        if config.get("media_tracker", {}).get("enabled", False):
            try:
                video_handler = getattr(monitor, "event_handler", None)
                if video_handler and video_handler.renamer and video_handler.yun139_uploader:
                    from .core.media_tracker_client import MediaTrackerClient
                    mt_client = MediaTrackerClient(
                        config=config.get("media_tracker", {}),
                        renamer=video_handler.renamer,
                        yun139_uploader=video_handler.yun139_uploader,
                    )
                    mt_client.start()
            except Exception as e:
                logger.warning(f"初始化 Media Tracker 客户端失败: {e}")

        try:
            # 启动监控
            cli_output.print_separator()
            cli_output.print_info(
                f"支持的文件类型: {', '.join(monitor.supported_extensions)}"
            )
            cli_output.print_success("监控服务已启动！")
            cli_output.print_info("按 Ctrl+C 停止监控")
            cli_output.print_separator()

            # 设置系统运行状态
            state = get_state_manager()
            state.set_system_running(True)

            monitor.start()

        except KeyboardInterrupt:
            cli_output.print_info("用户中断，程序退出")
        except Exception as e:
            cli_output.print_error(f"监控过程中发生错误", error=e)
            logger.exception("监控过程中发生错误")
            # 尝试优雅地停止监控
            try:
                monitor.stop()
            except:
                pass
            sys.exit(1)
        finally:
            # 设置系统停止状态
            state = get_state_manager()
            state.set_system_running(False)

            # 确保监控器被停止
            try:
                monitor.stop()
                cli_output.print_success("监控服务已成功停止")
            except:
                pass

    except ValueError as e:
        # 处理配置验证错误
        cli_output.print_error(f"配置错误", error=str(e))
        print(f"配置错误: {str(e)}")
        sys.exit(1)
    except Exception as e:
        # 处理其他未预期的错误
        cli_output.print_error(f"启动程序时发生未预期的错误", error=e)
        print(f"启动失败: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
