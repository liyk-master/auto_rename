import os
import sys
import argparse
import logging
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

try:
    from src.video_organizer.core.config_loader import load_config
    from src.video_organizer.core.tmdb_client import TMDBClient
    from src.video_organizer.core.renamer import VideoRenamer
except ImportError as e:
    print(f"导入失败: {e}")
    print("请确保在项目根目录下运行此脚本。")
    sys.exit(1)

# 配置日志
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="单独测试 Renamer 和 TMDB Client 的工具")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--search", type=str, help="直接在 TMDB 中搜索视频标题")
    group.add_argument("--file", type=str, help="模拟文件路径，测试元数据提取和重命名路径生成")
    group.add_argument("--comprehensive", type=str, help="综合测试：提取元数据并进行 TMDB 丰富")
    
    parser.add_argument("--type", type=str, choices=['movie', 'tv'], help="手动指定媒体类型")
    parser.add_argument("--config", type=str, help="指定配置文件路径")
    
    args = parser.parse_args()
    
    # 1. 加载配置
    try:
        config_path = args.config if args.config else os.path.join(os.getcwd(), 'config.ini')
        if not os.path.exists(config_path):
            print(f"提示: 找不到配置文件 {config_path}, 将尝试使用默认配置或环境变量")
            
        config = load_config(args.config)
        tmdb_conf = config.get('tmdb', {})
        naming_conf = config.get('naming_rules', {})
        
        api_key = tmdb_conf.get('api_key')
        if not api_key:
            print("警告: 配置文件中未找到 TMDB API Key。部分功能将受限。")
            
        print(f"成功加载配置，TMDB 语言: {tmdb_conf.get('language', 'zh-CN')}")
    except Exception as e:
        print(f"加载配置失败 (仅影响 TMDB 功能): {e}")
        api_key = None
        naming_conf = {}
        tmdb_conf = {}
        
    # 2. 初始化客户端
    tmdb_client = None
    if api_key:
        tmdb_client = TMDBClient(
            api_key=api_key,
            retry_count=tmdb_conf.get('retry_count', 3),
            timeout=tmdb_conf.get('timeout', 30)
        )
    
    renamer = VideoRenamer(
        tmdb_api_key=api_key,
        naming_rules=naming_conf
    )
    if tmdb_client:
        renamer.tmdb_client = tmdb_client
    
    # 3. 执行测试逻辑
    if args.search:
        if not tmdb_client:
            print("错误: 需要 API Key 才能进行搜索。")
            return
        print(f"\n--- TMDB 搜索测试: '{args.search}' ---")
        results = tmdb_client.search_video_show(args.search, language=tmdb_conf.get('language'))
        if results:
            if isinstance(results, list):
                print(f"找到 {len(results)} 个结果:")
                for i, res in enumerate(results[:5]):
                    m_type = res.get('media_type', 'unknown')
                    name = res.get('name') or res.get('title')
                    year = res.get('first_air_date', res.get('release_date', ''))[:4]
                    print(f"  [{i+1}] {name} ({year}) - 类型: {m_type}, ID: {res.get('id')}")
            else:
                name = results.get('name') or results.get('title')
                print(f"匹配到结果: {name}, ID: {results.get('id')}")
        else:
            print("未找到匹配结果。")
            
    elif args.file:
        print(f"\n--- 元数据提取测试: '{args.file}' ---")
        file_path = Path(args.file)
        # 仅正则提取
        metadata = renamer._extract_with_regex(file_path.name)
        
        print("仅 Regex 提取结果:")
        for k, v in metadata.items():
            if v:
                print(f"  {k}: {v}")
                
        # 模拟生成路径
        try:
            # 补齐必要字段以生成路径
            metadata.setdefault('tmdb_id', 'TEST_ID')
            metadata.setdefault('media_type', args.type or 'tv')
            if not metadata.get('show_name') and not metadata.get('title'):
                metadata['show_name'] = file_path.stem
                
            new_path = renamer.generate_new_path(metadata)
            print(f"\n生成的模拟重命名路径:")
            print(f"  {new_path}")
        except Exception as e:
            print(f"生成路径失败: {e}")

    elif args.comprehensive:
        print(f"\n--- 综合识别测试: '{args.comprehensive}' ---")
        # 完整提取逻辑 (包含 TMDB 丰富)
        metadata = renamer.extract_metadata(args.comprehensive, media_type_hint=args.type)
        
        print("\n最终元数据 (包含 TMDB 丰富结果):")
        important_fields = ['show_name', 'title', 'tmdb_id', 'media_type', 'season', 'episode', 'year', 'quality_tags']
        for field in important_fields:
            if metadata.get(field):
                print(f"  {field}: {metadata.get(field)}")
                
        try:
            new_path = renamer.generate_new_path(metadata, original_path=args.comprehensive)
            print(f"\n最终生成的标准化路径:")
            print(f"  {new_path}")
        except Exception as e:
            print(f"生成路径失败: {e}")

if __name__ == "__main__":
    main()
