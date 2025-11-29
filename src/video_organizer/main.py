import os
import sys
import signal
from pathlib import Path
from typing import Optional, Dict, Any

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# 导入配置加载器
from .core.config_loader import load_config, save_default_config

# 导入监控器和处理器
from .core.filesystem_monitor import FileSystemMonitor
from .core.video_file_handler import VideoFileHandler

# 导入日志工具
from .utils.logging_utils import get_logger, setup_logging

# 导入命令行工具
from .utils.cli_parser import get_cli_parser
from .utils.cli_output import get_cli_output

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


def initialize_monitor(config: dict, cli_options: Optional[Dict[str, Any]] = None) -> Optional[FileSystemMonitor]:
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
        monitoring_config = config.get('monitoring', {})
        
        # 默认值
        watch_dir = ""
        output_dir = ""
        supported_extensions = []
        poll_interval = 1
        use_polling = False
        polling_interval = 5
        
        # 先尝试从命令行选项获取配置
        if cli_options:
            watch_dir = cli_options.get('watch_dir', watch_dir)
            output_dir = cli_options.get('output_dir', output_dir)
            poll_interval = cli_options.get('poll_interval', poll_interval)
            use_polling = cli_options.get('use_polling', use_polling)
            polling_interval = cli_options.get('polling_interval', polling_interval)
        
        # 如果命令行没有提供，则从配置文件获取
        if not watch_dir:
            watch_dir = monitoring_config.get('watch_dir', '')
        if not output_dir:
            output_dir = monitoring_config.get('output_dir', '')
        if not supported_extensions:
            supported_extensions = monitoring_config.get('supported_extensions', [])
        if poll_interval == 1:
            poll_interval = monitoring_config.get('poll_interval', 1)
        if not use_polling:
            use_polling = monitoring_config.get('use_polling', False)
        if polling_interval == 5:
            polling_interval = monitoring_config.get('polling_interval', 5)
        
        # 验证必要的目录
        if not watch_dir:
            cli_output.print_error("监控目录未配置")
            logger.error("监控目录未配置")
            return None
        
        if not os.path.exists(watch_dir):
            cli_output.print_error(f"监控目录不存在: {watch_dir}")
            logger.error(f"监控目录不存在: {watch_dir}")
            return None
        
        # 确保输出目录存在
        if output_dir and not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
                cli_output.print_success(f"创建输出目录: {output_dir}")
                logger.info(f"创建输出目录: {output_dir}")
            except Exception as e:
                cli_output.print_error(f"创建输出目录失败", error=e)
                logger.error(f"创建输出目录失败: {e}")
                return None
        
        # FileSystemMonitor会自己创建和初始化必要的组件，包括event_handler
        
        # 创建并启动文件系统监控器
        monitor = FileSystemMonitor(
            watch_path=watch_dir,
            processed_path=output_dir,
            tmdb_api_key=config.get('tmdb', {}).get('api_key', ''),
            ai_service_url=None,
            supported_extensions=supported_extensions,
            use_polling=use_polling,
            polling_interval=polling_interval,
            naming_rules=config.get('naming_rules')
        )
        
        # 父监控器引用已在FileSystemMonitor内部设置
        
        cli_output.print_success("文件系统监控器初始化成功")
        logger.info("文件系统监控器初始化成功", extra={
            "watch_dir": watch_dir,
            "output_dir": output_dir,
            "extensions": str(supported_extensions),
            "mode": "polling" if use_polling else "event_listening"
        })
        
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
        monitoring_config = config.get('monitoring', {})
        output_dir = monitoring_config.get('output_dir', '')
        supported_extensions = monitoring_config.get('supported_extensions', [])
        naming_rules = config.get('naming_rules')
        tmdb_config = config.get('tmdb')
        
        # 验证文件存在
        if not os.path.exists(file_path):
            cli_output.print_error(f"文件不存在: {file_path}")
            return False
        
        # 验证输出目录
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            cli_output.print_success(f"创建输出目录: {output_dir}")
        
        # 创建文件处理器
        handler = VideoFileHandler(
            output_dir=output_dir,
            supported_extensions=supported_extensions,
            naming_rules=naming_rules,
            tmdb_config=tmdb_config
        )
        
        # 强制处理文件
        cli_output.print_info(f"开始处理文件: {file_path}")
        success = handler.force_process_file(file_path)
        
        if success:
            cli_output.print_success(f"文件处理成功: {file_path}")
        else:
            cli_output.print_error(f"文件处理失败: {file_path}")
        
        return success
        
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
    monitoring_config = config.get('monitoring', {})
    print(f"  监控目录: {monitoring_config.get('watch_dir', '未设置')}")
    print(f"  输出目录: {monitoring_config.get('output_dir', '未设置')}")
    print(f"  轮询间隔: {monitoring_config.get('poll_interval', 1)} 秒")
    print(f"  使用轮询: {monitoring_config.get('use_polling', False)}")
    print(f"  轮询模式间隔: {monitoring_config.get('polling_interval', 5)} 秒")
    print(f"  支持的扩展名: {', '.join(monitoring_config.get('supported_extensions', []))}")
    
    cli_output.print_separator()
    
    # 显示命名规则
    cli_output.print_info("命名规则:")
    naming_rules = config.get('naming_rules', {})
    print(f"  电视剧格式: {naming_rules.get('tv_show', '未设置')}")
    print(f"  电影格式: {naming_rules.get('movie', '未设置')}")
    print(f"  动画格式: {naming_rules.get('anime', '未设置')}")
    print(f"  简单格式: {naming_rules.get('simple', '未设置')}")
    
    cli_output.print_separator()
    
    # 显示TMDB配置
    cli_output.print_info("TMDB配置:")
    tmdb_config = config.get('tmdb', {})
    print(f"  API密钥: {'已设置' if tmdb_config.get('api_key') else '未设置'}")
    print(f"  语言: {tmdb_config.get('language', 'zh-CN')}")
    print(f"  地区: {tmdb_config.get('region', 'CN')}")
    print(f"  重试次数: {tmdb_config.get('retry_count', 3)}")
    print(f"  超时时间: {tmdb_config.get('timeout', 30)} 秒")
    
    cli_output.print_separator()


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
        if not config_path:
            # 使用默认配置路径
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
        
        # 确保配置文件存在
        if not os.path.exists(config_path):
            cli_output.print_warning(f"配置文件不存在: {config_path}")
            cli_output.print_info("正在创建默认配置文件...")
            save_default_config(config_path)
            cli_output.print_success(f"默认配置文件已创建: {config_path}")
        
        config = load_config(config_path)
        
        # 初始化日志系统
        setup_logging(config.get('logging', {}))
        
        # 设置信号处理器
        setup_signal_handlers()
        
        # 应用命令行选项到配置
        cli_options = {}
        
        # 显示配置
        if args.show_config:
            display_config(config)
            sys.exit(0)
        
        # 强制处理文件模式
        if args.process:
            cli_output.print_header("强制处理模式")
            success = force_process_file(args.process, config)
            sys.exit(0 if success else 1)
        
        cli_output.print_header(f"视频文件自动重命名和组织工具 v{__version__}")
        cli_output.print_info("启动中...")
        
        # 初始化监控器
        monitor = initialize_monitor(config, cli_options)
        if not monitor:
            cli_output.print_error("监控器初始化失败，程序退出")
            sys.exit(1)
        
        try:
            # 启动监控
            cli_output.print_separator()
            # 获取logger实例
            logger = get_logger(__name__)
            cli_output.print_info(f"开始监控目录: {monitor.watch_path}")
            cli_output.print_info(f"输出目录: {monitor.processed_path}")
            cli_output.print_info(f"支持的文件类型: {', '.join(monitor.supported_extensions)}")
            cli_output.print_info(f"轮询间隔: {monitor.polling_interval} 秒")
            cli_output.print_info(f"使用轮询模式: {'是' if monitor.use_polling else '否'}")
            cli_output.print_success("监控服务已启动！")
            cli_output.print_info("按 Ctrl+C 停止监控")
            cli_output.print_separator()
            
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


if __name__ == '__main__':
    main()