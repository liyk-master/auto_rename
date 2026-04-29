#!/usr/bin/env python3
"""
从 dmhy.org 抓取字幕组命名样本，批量测试正则识别效果
"""
import re
import sys
import json
import logging
from pathlib import Path
from urllib.parse import urljoin

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from video_organizer.core.renamer import VideoRenamer
from video_organizer.core.config_loader import load_config

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("请安装依赖: pip install requests beautifulsoup4")
    sys.exit(1)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def fetch_dmhy_filenames(limit=50):
    """从 dmhy.org 抓取种子文件名"""
    base_url = "https://dmhy.org"
    # 获取新番列表第一页
    url = urljoin(base_url, "/topics/list?sort_id=2&page=1")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print(f"正在抓取 {url} ...")
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
    except Exception as e:
        print(f"请求失败: {e}")
        return []

    # dmhy 是 GBK 编码
    response.encoding = "utf-8"

    soup = BeautifulSoup(response.text, "html.parser")

    filenames = []
    # 查找 torrent 链接或标题
    # dmhy 的表格中，标题在 .title 类或 td[width="40%"] 中
    rows = soup.find_all("tr", class_="")

    for row in rows:
        # 尝试找到标题链接
        title_link = row.select_one("td.title a, .keyword a")
        if title_link:
            title = title_link.get_text(strip=True)
            # 过滤掉空标题和非视频内容
            if title and "." in title:
                # 尝试找到种子文件名，通常在详情页，这里先用标题
                filename = title
                if not filename.endswith((".mkv", ".mp4", ".avi", ".mov")):
                    # 尝试从详情页获取真实文件名
                    pass
                filenames.append(filename)

        if len(filenames) >= limit:
            break

    return filenames[:limit]


def test_filename_parsing(filenames, renamer):
    """测试文件名解析，返回有问题的情况"""
    results = {
        "success": [],
        "missing_season": [],
        "missing_episode": [],
        "missing_show_name": [],
        "other_issues": []
    }

    for filename in filenames:
        metadata = renamer._extract_with_regex(filename)

        issue = None
        if not metadata.get("show_name"):
            issue = "missing_show_name"
        elif not metadata.get("episode"):
            issue = "missing_episode"
        elif not metadata.get("season"):
            issue = "missing_season"

        if issue:
            results[issue].append({
                "filename": filename,
                "parsed": metadata
            })
        else:
            results["success"].append({
                "filename": filename,
                "parsed": metadata
            })

    return results


def print_results(results):
    """打印测试结果"""
    total = sum(len(v) for v in results.values())
    success_count = len(results["success"])

    print(f"\n{'='*60}")
    print(f"测试结果汇总: {success_count}/{total} 成功 ({success_count/total*100:.1f}%)")
    print(f"{'='*60}\n")

    # 按问题类型打印
    categories = [
        ("missing_show_name", "未识别到剧名"),
        ("missing_episode", "未识别到集号"),
        ("missing_season", "未识别到季号"),
        ("other_issues", "其他问题")
    ]

    for key, title in categories:
        items = results[key]
        if items:
            print(f"\n【{title}】({len(items)} 个):")
            print("-" * 60)
            for item in items[:10]:
                print(f"  文件: {item['filename'][:70]}...")
                meta = item['parsed']
                print(f"  解析: show_name={meta.get('show_name')}, "
                      f"season={meta.get('season')}, "
                      f"episode={meta.get('episode')}, "
                      f"release_group={meta.get('release_group')}")
                print()
            if len(items) > 10:
                print(f"  ... 还有 {len(items) - 10} 个未显示")

    # 成功的样本（展示前5个）
    print(f"\n【成功识别的样本】(前 5 个):")
    print("-" * 60)
    for item in results["success"][:5]:
        meta = item['parsed']
        print(f"  {meta.get('show_name', 'N/A'):<30} "
              f"S{meta.get('season', '?'):>02}E{meta.get('episode', '?'):>03} "
              f"[{meta.get('release_group', 'N/A')}]")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50, help="抓取数量")
    parser.add_argument("--offline", action="store_true", help="使用本地缓存")
    parser.add_argument("--config", default="config.ini", help="配置文件路径")
    args = parser.parse_args()

    cache_file = Path(__file__).parent / "dmhy_samples.json"

    # 获取文件名列表
    if args.offline and cache_file.exists():
        print(f"从缓存读取: {cache_file}")
        with open(cache_file, 'r', encoding='utf-8') as f:
            filenames = json.load(f)
    else:
        filenames = fetch_dmhy_filenames(args.limit)
        if not filenames:
            print("未能获取到文件名，请检查网络连接或网页结构变化")
            return

        # 保存缓存
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(filenames, f, ensure_ascii=False, indent=2)
        print(f"已保存 {len(filenames)} 个样本到: {cache_file}")

    # 初始化 renamer
    config = {}
    if Path(args.config).exists():
        config = load_config(args.config)

    tmdb_conf = config.get("tmdb", {})
    renamer = VideoRenamer(
        tmdb_api_key=tmdb_conf.get("api_key"),
        naming_rules=config.get("naming_rules", {}),
        config=config
    )

    print(f"\n开始测试 {len(filenames)} 个文件名...")
    results = test_filename_parsing(filenames, renamer)
    print_results(results)

    # 保存详细结果
    report_file = Path(__file__).parent / "dmhy_test_report.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n详细报告已保存: {report_file}")


if __name__ == "__main__":
    main()
