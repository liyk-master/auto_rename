#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 dmhy RSS 抓取真实视频文件名并批量测试识别效果
"""
import re
import sys
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("请安装依赖: pip install requests beautifulsoup4")
    sys.exit(1)

from video_organizer.core.renamer import VideoRenamer
from video_organizer.core.config_loader import load_config

RSS_URL = "https://dmhy.org/topics/rss/rss.xml"
OUTPUT_FILE = "dmhy_test_results.json"


def fetch_rss_filenames(limit=50):
    """从 RSS 获取并解析真实文件名"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    response = requests.get(RSS_URL, headers=headers, timeout=30)
    response.raise_for_status()
    response.encoding = "gbk"

    root = ET.fromstring(response.content)
    items = []

    channel = root.find('.//channel')
    if channel is not None:
        for item in channel.findall('item'):
            title = item.findtext('title', '').strip()
            link = item.findtext('link', '').strip()

            # 从标题解析文件名
            # RSS标题格式: [字幕组][作品名][集号][规格].ext 或类似格式
            filename = parse_filename_from_title(title)

            if filename and len(items) < limit:
                items.append({
                    'filename': filename,
                    'rss_title': title,
                    'link': link
                })

    return items


def parse_filename_from_title(title):
    """从 RSS 标题解析文件名"""
    # 常见格式:
    # [Skymoon-Raws][海贼王][1159][...].mkv
    # [Sakurato] 邻家的天使同学 2 [04][...].mkv
    # [ANi] 作品名 - XX [1080P]...

    # 尝试匹配方括号为主的格式
    if title.startswith('['):
        # 找到第一个方括号组
        bracket_pattern = r'(\[[^\]]+\](?:\[[^\]]+\])+(?:\[[^\]]+\])*)'
        match = re.search(bracket_pattern, title)
        if match:
            base = match.group(1)
            # 尝试确定扩展名
            ext_match = re.search(r'\.(mkv|mp4|avi)', title, re.I)
            ext = ext_match.group(1) if ext_match else "mkv"
            return f"{base}.{ext}"

        # 下划线格式: [字幕组] Show_Name_2 [03]...
        underscore_pattern = r'(\[[^\]]+\])\s*([\w_]+)\s*(?:\[?(\d{1,3})\]?|\s*-\s*(\d{1,3}))'
        match = re.search(underscore_pattern, title)
        if match:
            group = match.group(1)
            name = match.group(2)
            episode = match.group(3) or match.group(4)
            ext_match = re.search(r'\.(mkv|mp4|avi)', title, re.I)
            ext = ext_match.group(1) if ext_match else "mkv"
            return f"{group}[{name}][{episode}].{ext}"

    # ANi 格式: [ANi] 作品名 - XX [...]
    ani_pattern = r'\[ANi\]\s+([^-\[]+)\s*-\s*(\d+)\s*\['
    match = re.search(ani_pattern, title)
    if match:
        name = match.group(1).strip()
        episode = match.group(2)
        ext_match = re.search(r'\.(mkv|mp4|avi)', title, re.I)
        ext = ext_match.group(1) if ext_match else "mp4"
        return f"[ANi][{name}][{episode}].{ext}"

    return None


def test_batch_filenames(items, renamer):
    """批量测试文件名识别"""
    results = {
        "total": len(items),
        "success": [],
        "failures": {
            "missing_show_name": [],
            "missing_episode": [],
            "missing_season": [],
            "parse_error": []
        },
        "by_release_group": defaultdict(lambda: {"success": 0, "fail": 0, "samples": []})
    }

    for item in items:
        filename = item['filename']
        rss_title = item['rss_title']

        try:
            metadata = renamer._extract_with_regex(filename)
            release_group = metadata.get("release_group", "Unknown")

            # 判断识别结果
            issues = []
            if not metadata.get("show_name"):
                issues.append("missing_show_name")
            if not metadata.get("episode"):
                issues.append("missing_episode")

            if issues:
                # 记录失败
                fail_data = {
                    "filename": filename,
                    "rss_title": rss_title,
                    "parsed": metadata,
                    "issues": issues
                }
                for issue in issues:
                    results["failures"][issue].append(fail_data)

                results["by_release_group"][release_group]["fail"] += 1
                if len(results["by_release_group"][release_group]["samples"]) < 3:
                    results["by_release_group"][release_group]["samples"].append(fail_data)
            else:
                # 记录成功
                success_data = {
                    "filename": filename,
                    "show_name": metadata.get("show_name"),
                    "season": metadata.get("season", 1),
                    "episode": metadata.get("episode"),
                    "release_group": release_group
                }
                results["success"].append(success_data)
                results["by_release_group"][release_group]["success"] += 1

        except Exception as e:
            results["failures"]["parse_error"].append({
                "filename": filename,
                "rss_title": rss_title,
                "error": str(e)
            })
            results["by_release_group"]["Unknown"]["fail"] += 1

    return results


def generate_report(results):
    """生成测试报告"""
    report = []
    report.append("=" * 80)
    report.append("DMHY 字幕命名格式批量测试报告")
    report.append("=" * 80)
    report.append("")

    total = results["total"]
    success_count = len(results["success"])
    fail_count = total - success_count
    success_rate = success_count / total * 100 if total > 0 else 0

    report.append(f"总计测试: {total} 个文件")
    report.append(f"成功识别: {success_count} ({success_rate:.1f}%)")
    report.append(f"识别失败: {fail_count}")
    report.append("")

    # 按失败类型统计
    report.append("-" * 80)
    report.append("按失败类型统计:")
    report.append("-" * 80)
    for fail_type, items in results["failures"].items():
        if items:
            report.append(f"  [{fail_type}]: {len(items)} 个")
            for item in items[:3]:  # 只显示前3个样本
                report.append(f"    - {item['filename'][:60]}...")
                if "parsed" in item:
                    m = item["parsed"]
                    report.append(f"      解析: show={m.get('show_name')}, S={m.get('season')}, E={m.get('episode')}")
            if len(items) > 3:
                report.append(f"    ... 还有 {len(items) - 3} 个")
            report.append("")

    # 按字幕组统计
    report.append("-" * 80)
    report.append("按字幕组统计 (失败率高的需要关注):")
    report.append("-" * 80)

    # 按失败率排序
    group_stats = []
    for group, stats in results["by_release_group"].items():
        total_group = stats["success"] + stats["fail"]
        if total_group > 0:
            fail_rate = stats["fail"] / total_group * 100
            group_stats.append((group, stats, fail_rate, total_group))

    group_stats.sort(key=lambda x: -x[2])  # 按失败率降序

    for group, stats, fail_rate, total_group in group_stats:
        if total_group >= 1:  # 至少一个样本
            status = "[需要关注]" if fail_rate > 50 else "[正常]"
            report.append(f"  {group}: {stats['success']}/{total_group} 成功 ({100-fail_rate:.0f}% 成功率) {status}")
            if stats["samples"]:
                for sample in stats["samples"]:
                    report.append(f"    失败样本: {sample['filename'][:50]}...")

    report.append("")
    report.append("-" * 80)
    report.append("成功识别样本 (前10个):")
    report.append("-" * 80)
    for item in results["success"][:10]:
        try:
            season_str = f"{int(item['season']):02d}" if item.get('season') else "??"
            episode_str = f"{int(item['episode']):03d}" if item.get('episode') else "??"
            report.append(f"  {item['show_name']:<30} S{season_str}E{episode_str} [{item['release_group']}]")
        except:
            report.append(f"  {item['show_name']:<30} S{item.get('season','?')}E{item.get('episode','?')} [{item['release_group']}]")

    return "\n".join(report)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--config", default="config.ini")
    parser.add_argument("--offline", action="store_true", help="使用本地缓存")
    args = parser.parse_args()

    cache_file = Path(__file__).parent / "dmhy_cache.json"

    # 获取数据
    if args.offline and cache_file.exists():
        with open(cache_file, 'r', encoding='utf-8') as f:
            items = json.load(f)
    else:
        items = fetch_rss_filenames(args.limit)
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)

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

    # 批量测试
    results = test_batch_filenames(items, renamer)

    # 生成并输出报告
    report = generate_report(results)
    print(report)

    # 保存完整结果
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n完整结果已保存: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
