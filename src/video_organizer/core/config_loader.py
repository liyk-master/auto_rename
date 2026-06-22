import os
import sys
import json
import configparser
import logging
from typing import Dict, Any, List, Optional

# 配置日志记录器
logger = logging.getLogger(__name__)

# 默认配置值
DEFAULT_CONFIG = {
    "monitoring": {
        "watch_dir": "",
        "output_dir": "",
        "poll_interval": 10,
        "supported_extensions": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv"],
        "use_polling": False,
        "polling_interval": 5,
        "path_mappings": {},  # 用于将下载器返回的路径映射到主机实际路径，例如："/downloads": "F:/Downloads"
        # 目录监控相关配置
        "enable_directory_monitor": False,
        "directory_watch_dir": "",
        "directory_output_dir": "",
        "directory_organize_mode": "copy",
        "directory_scrape_metadata": True,
        "directory_metadata_format": "nfo",
        "directory_polling_interval": 5,
    },
    "emos": {"auth_token": "", "base_url": "https://emos.lol"},
    "p123": {
        "token": "",
        "parent_id": 0,
        "max_workers": 2,
        "organize_source_id": 0,  # 需要整理的源目录ID
        "organize_target_id": 0,  # 整理到的目标目录ID
    },
    "cloud189": {
        "username": "",
        "password": "",
        "cookie": "",
        "parent_folder_id": "-11",
        "family_id": "",
        "max_workers": 5,
        "strm_server": "",  # STRM 服务器地址，如 http://192.0.2.0:5000
        "strm_output_dir": "",  # STRM 文件输出目录
        "delete_after": False,  # 上传完成后删除云端文件
        "empty_recycle_bin": False,  # 上传完成后清空回收站
        "generate_cas": False,  # 上传成功后生成 .cas 文件（用于秒传校验）
        "cas_output_dir": "",  # .cas 文件输出目录，留空则输出到程序同级目录下的 cas/ 文件夹
        "cas_upload_url": "",  # 外部 .cas 上传 API 地址
        "cas_upload_api_key": "",  # 外部 .cas 上传 API 的 Bearer 认证密钥
    },
    "yun139": {
        "authorization": "",  # Base64编码的认证信息
        "cloud_type": "personal_new",  # 云盘类型: personal_new, personal, family, group
        "cloud_id": "",  # 家庭云/群组云ID
        "parent_id": "/",  # 根目录文件夹ID，空字符串表示根目录
        "custom_part_size": 0,  # 自定义分片大小，0为自动
        "max_workers": 3,  # 并行上传视频数量（每个视频内分片串行上传）
        "strm_server": "",  # STRM 服务器地址，如 http://192.0.2.0:5010
        "strm_output_dir": "",  # STRM 文件输出目录
        "delete_after": False,  # 上传完成后删除云端文件
        "app_mode": False,  # 使用 Android App 协议栈伪装上传（绕过 PC 通道限制）
    },
    "naming": {
        "tv_show_format": "{show_name}/Season {season:02d}/{show_name} {season_episode} {quality_tags}",
        "movie_format": "{movie_name}{year_suffix}/{movie_name}{year_suffix} {quality_tags}",
        "anime_format": "{anime_name}/{season_name}/{anime_name} - S{season:02d}E{episode:02d} {quality_tags}",
        "simple_format": "{title} {quality_tags}",
    },
    "tmdb": {
        "api_key": "",
        "language": "zh-CN",
        "region": "CN",
        "retry_count": 3,
        "timeout": 30,
    },
    "processing": {
        "rename_only": False,
        "copy_mode": False,
        "delete_original": False,
        "delete_after_upload": False,
        "min_file_size": 0,
        "ignore_patterns": [],
        "upload_targets": "emos",
        "max_upload_workers": 3,  # 并行上传工作线程数
    },
    "logging": {
        "log_level": "INFO",
        "log_file": "",
        "console_log": True,
        "file_log": False,
    },
    "telegram": {"bot_token": "", "chat_id": ""},
    "llm_fallback": {"enabled": False, "max_concurrent": 2},
    "llm_provider_1": {"name": "", "api_url": "", "api_key": "", "model": "", "enabled": False, "weight": 1, "timeout": 30, "max_retries": 2},
    "llm_provider_2": {"name": "", "api_url": "", "api_key": "", "model": "", "enabled": False, "weight": 1, "timeout": 30, "max_retries": 2},
    "llm_provider_3": {"name": "", "api_url": "", "api_key": "", "model": "", "enabled": False, "weight": 1, "timeout": 30, "max_retries": 2},
    "guessit": {
        "enabled": True,  # 是否启用 GuessIt 增强识别
        "prefer_guessit": False,  # 是否优先使用 GuessIt 结果
    },
    "manual_rules": {
        "enabled": False,  # 是否启用手动规则
        "normalize_symbols": True,  # 是否归一化规则中的符号
        "rules": [],  # 手动规则列表
    },
    "downloaders": [],
    "emya_db": {
        "enabled": False,
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "",
        "database": "emya",
        "charset": "utf8mb4",
        "pool_size": 5,
        "max_overflow": 10,
        "pool_recycle": 3600,
        "default_user_id": 1,
        "default_tv_library": "电视剧",
        "default_movie_library": "电影",
    },
    "media_tracker": {
        "enabled": False,
        "host": "localhost",
        "port": 8082,
        "token": "",
        "reconnect_delay": 5,
        "app_mode": True,
        # 上传配置
        "upload_enabled": False,  # 是否启用上传到 media_tracker
        "upload_cloud": "cloud-1",  # 云盘标识
    },
    "auth": {
        "enabled": False,
        "username": "admin",
        "password": "admin",
    },
}

def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    加载并验证配置文件
    
    Args:
        config_path: 配置文件路径，如果不提供则使用默认路径
    
    Returns:
        配置字典
    
    Raises:
        FileNotFoundError: 如果配置文件不存在
        ValueError: 如果配置无效
    """
    if not config_path:
        # 检查是否为打包后的环境
        if getattr(sys, "frozen", False):
            # 如果是打包后的exe，配置文件在exe同级目录
            base_dir = os.path.dirname(sys.executable)
            config_path = os.path.join(base_dir, "config.ini")
        else:
            # 开发环境：使用项目内配置文件路径
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "config.ini"
            )
    
    # 检查配置文件是否存在
    if not os.path.exists(config_path):
        logger.warning(f"配置文件不存在: {config_path}")
        # 创建默认配置目录
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        # 保存默认配置
        save_default_config(config_path)
        logger.info(f"已创建默认配置文件: {config_path}")
    
    config = configparser.ConfigParser()
    # 使用UTF-8编码读取配置文件，避免编码错误
    config.read(config_path, encoding="utf-8")
    
    # 转换为字典并验证
    config_dict = _config_to_dict(config)
    
    # 验证必要的配置项
    if not _validate_config(config_dict):
        raise ValueError("配置验证失败，请检查配置文件")
    
    return config_dict


def save_default_config(config_path: str) -> None:
    """
    保存默认配置到文件
    
    Args:
        config_path: 配置文件路径
    """
    config = configparser.ConfigParser()
    
    # 设置默认配置
    for section, options in DEFAULT_CONFIG.items():
        # 跳过列表类型的配置（如下载器），它们不能直接作为INI的一个节
        if not isinstance(options, dict):
            continue
        
        config[section] = {}
        for key, value in options.items():
            if isinstance(value, list):
                config[section][key] = ",".join(value)
            else:
                config[section][key] = str(value)
    
    # 写入配置文件
    with open(config_path, "w", encoding="utf-8") as f:
        config.write(f)


def _config_to_dict(config: configparser.ConfigParser) -> Dict[str, Any]:
    """
    将配置对象转换为字典，同时合并默认配置
    
    Args:
        config: 配置对象
    
    Returns:
        配置字典
    """
    config_dict = {}
    
    # 合并默认配置和用户配置
    for section, default_options in DEFAULT_CONFIG.items():
        config_dict[section] = default_options.copy()
        
        # 如果配置中有该节
        if section in config:
            for key, value in config[section].items():
                # 根据默认值类型转换
                if key in default_options:
                    if isinstance(default_options[key], bool):
                        config_dict[section][key] = config[section].getboolean(key)
                    elif isinstance(default_options[key], int):
                        config_dict[section][key] = config[section].getint(key)
                    elif isinstance(default_options[key], list):
                        # 对于 manual_rules.rules，稍后特殊处理
                        if section == "manual_rules" and key == "rules":
                            # 不在这里处理，稍后统一处理
                            pass
                        else:
                            config_dict[section][key] = [
                                item.strip()
                                for item in config[section].get(key, "").split(",")
                                if item.strip()
                            ]
                    elif isinstance(default_options[key], dict):
                        # 特殊处理字典类型，用于path_mappings配置
                        if key == "path_mappings":
                            mappings_str = config[section].get(key, "")
                            mappings = {}
                            if mappings_str:
                                for mapping in mappings_str.split(","):
                                    mapping = mapping.strip()
                                    if mapping:
                                        parts = mapping.split(":", 1)
                                        if len(parts) == 2:
                                            mappings[parts[0].strip()] = parts[1].strip()
                            config_dict[section][key] = mappings
                        else:
                            config_dict[section][key] = config[section].get(key)
                    else:
                        # 对于字符串类型（如 api_key），直接从配置文件读取值
                        config_dict[section][key] = value
                else:
                    # 对于未知配置项，保留为字符串
                    config_dict[section][key] = value
    
    # 保留不在 DEFAULT_CONFIG 中的自定义节（如 downloader.xxx）
    for section in config.sections():
        if section not in DEFAULT_CONFIG:
            config_dict[section] = {}
            for key, value in config[section].items():
                config_dict[section][key] = value
    
    # 特殊处理 manual_rules 节中的规则配置
    if "manual_rules" in config_dict and "manual_rules" in config:
        rules_list = []
        manual_section = config["manual_rules"]
        
        # 方式1：如果配置了 rules 键（用 | 分隔的规则字符串）
        if "rules" in manual_section:
            rules_str = manual_section.get("rules", "")
            if rules_str:
                for rule_str in rules_str.split("|"):
                    rule_str = rule_str.strip()
                    if rule_str:
                        rules_list.append({"rule": rule_str, "enabled": True})
        
        # 方式2：收集所有 rule 开头的键（rule1, rule2, ...）
        for k, v in manual_section.items():
            if k.startswith("rule") and k != "rules" and k != "enabled":
                rule_str = v.strip()
                if rule_str:
                    rules_list.append({"rule": rule_str, "enabled": True})
        
        # 更新 rules 列表
        config_dict["manual_rules"]["rules"] = rules_list
        if rules_list:
            logger.info(f"从配置文件加载了 {len(rules_list)} 条手动规则")
    
    # 特殊处理命名规则
    if "naming" in config_dict:
        config_dict["naming_rules"] = {
            "tv_show": config_dict["naming"].pop("tv_show_format"),
            "movie": config_dict["naming"].pop("movie_format"),
            "anime": config_dict["naming"].pop("anime_format"),
            "simple": config_dict["naming"].pop("simple_format"),
        }
    
    # 特殊处理下载器配置
    config_dict["downloaders"] = []
    for section in config.sections():
        if section.startswith("downloader."):
            downloader_config = {}
            # 从section名称中提取下载器类型（例如：downloader.aria2 -> aria2）
            downloader_type = section.split(".")[1] if "." in section else ""
            downloader_config["type"] = downloader_type
            for key, value in config[section].items():
                downloader_config[key] = value
            config_dict["downloaders"].append(downloader_config)
    
    return config_dict


def _validate_config(config: Dict[str, Any]) -> bool:
    """
    验证配置有效性
    
    Args:
        config: 配置字典
    
    Returns:
        配置是否有效
    """
    is_valid = True
    
    # 验证监控配置
    if "monitoring" in config:
        # 对于输出目录，不再强制验证，因为我们现在使用下载器监控模式
        output_dir = config["monitoring"].get("output_dir", "")
        if not output_dir:
            logger.info("输出目录未配置，当前使用下载器监控模式")
        elif not os.path.exists(output_dir):
            # 尝试创建输出目录
            try:
                os.makedirs(output_dir)
                logger.info(f"已创建输出目录: {output_dir}")
            except Exception as e:
                logger.info(f"创建输出目录失败: {e}，当前使用下载器监控模式")
        
        # 对于监控目录，不再强制验证，因为我们现在使用下载器监控
        watch_dir = config["monitoring"].get("watch_dir", "")
        if not watch_dir:
            logger.info("监控目录未配置，当前使用下载器监控模式")
        elif not os.path.exists(watch_dir):
            logger.info(f"监控目录不存在: {watch_dir}，当前使用下载器监控模式")
    
    # 验证TMDB API密钥
    if "tmdb" in config:
        api_key = config["tmdb"].get("api_key", "")
        if not api_key:
            logger.warning("TMDB API密钥未配置，元数据刮削功能将不可用")
    
    # 验证命名规则
    if "naming_rules" in config:
        for rule_type, rule in config["naming_rules"].items():
            if not rule:
                logger.error(f"命名规则 {rule_type} 不能为空")
                is_valid = False
    
    return is_valid


def update_config(
    config_dict: Dict[str, Any], config_path: Optional[str] = None
) -> None:
    """
    更新配置文件
    
    Args:
        config_dict: 配置字典
        config_path: 配置文件路径
    """
    if not config_path:
        # 检查是否为打包后的环境
        if getattr(sys, "frozen", False):
            # 如果是打包后的exe，配置文件在exe同级目录
            base_dir = os.path.dirname(sys.executable)
            config_path = os.path.join(base_dir, "config.ini")
        else:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "config.ini"
            )
    
    config = configparser.ConfigParser()
    
    # 转换字典为配置对象
    for section, options in config_dict.items():
        if not isinstance(options, dict):
            continue
        # 特殊处理naming_rules
        if section == "naming_rules":
            if "naming" not in config:
                config["naming"] = {}
            for key, value in options.items():
                config["naming"][f"{key}_format"] = value
        else:
            config[section] = {}
            for key, value in options.items():
                # manual_rules.rules 由下面的 ruleN 写回，跳过
                if section == "manual_rules" and key == "rules":
                    continue
                if isinstance(value, list):
                    try:
                        config[section][key] = ",".join(value)
                    except TypeError:
                        config[section][key] = json.dumps(value, ensure_ascii=False)
                elif isinstance(value, dict):
                    config[section][key] = json.dumps(value, ensure_ascii=False)
                else:
                    config[section][key] = str(value)

    # 写回 manual_rules.rules 为 rule1, rule2, ... 条目
    manual_rules = config_dict.get("manual_rules", {})
    rules_list = manual_rules.get("rules", [])
    if isinstance(rules_list, list) and "manual_rules" in config:
        rule_idx = 1
        for rule_entry in rules_list:
            if isinstance(rule_entry, dict):
                rule_text = rule_entry.get("rule", "").strip()
                if rule_text:
                    config["manual_rules"][f"rule{rule_idx}"] = rule_text
                    rule_idx += 1
    
    # 写回 downloader.xxx 节（从 config_dict 中的 dict 键直接写入）
    for section_name in list(config_dict.keys()):
        if section_name.startswith("downloader."):
            options = config_dict[section_name]
            if not isinstance(options, dict):
                continue
            config[section_name] = {}
            for key, value in options.items():
                config[section_name][key] = str(value)
    
    # 保存配置文件
    parent_dir = os.path.dirname(config_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        config.write(f)
