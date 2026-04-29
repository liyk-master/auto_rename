#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 dmhy RSS 抓取真实视频文件名（详情页 file_list）并批量测试识别效果
"""
import re
import sys
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict
from urllib.parse import urljoin

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

RSS_URL = "https://dmhy.org/topics/rss/rss.xml?keyword=&sort_id=0&team_id=151&order=date-desc"
OUTPUT_FILE = "dmhy_test_results.json"


def fetch_rss_item_details(limit=50):
    """从 RSS 获取详情页链接，然后访问详情页提取 file_list 中的文件名"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print("正在获取 RSS...")
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

            if link and len(items) < limit:
                items.append({
                    'rss_title': title,
                    'detail_url': link
                })

    print(f"获取到 {len(items)} 条记录，将访问详情页提取文件名...")
    return items


def extract_filename_from_detail(detail_url):
    """从详情页的 .file_list 提取真实文件名"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(detail_url, headers=headers, timeout=20)
        response.raise_for_status()
        response.encoding = "utf-8"

        soup = BeautifulSoup(response.text, "html.parser")

        file_div = soup.find("div", class_="file_list")
        if not file_div:
            return None

        # 提取所有 li 中的文件名
        filenames = []
        for li in file_div.find_all("li"):
            text = li.get_text(separator=" ", strip=True)
            # 匹配文件名: [xxx]....mkv/mp4/...
            match = re.search(r'(\[[^\]]+\].*?\.(?:mkv|mp4|avi|mov|wmv|flv|webm|m4v))', text, re.I)
            if match:
                filename = match.group(1).strip()
                filenames.append(filename)

        if filenames:
            # 返回第一个（通常是主文件）
            return filenames[0]
        return None

    except Exception as e:
        print(f"  [ERROR] 详情页抓取失败: {detail_url} - {e}")
        return None


def test_batch_filenames(items, renamer):
    """批量测试文件名识别"""
    results = {
        "total": len(items),
        "success": [],
        "failures": {
            "missing_show_name": [],
            "missing_episode": [],
            "missing_season": [],  # 季号缺失（对于剧集不算致命，但需要记录）
            "parse_error": []
        },
        "by_release_group": defaultdict(lambda: {"success": 0, "fail": 0, "samples": []}),
        "samples": []  # 保存每个样本的详细信息
    }

    for idx, item in enumerate(items, 1):
        filename = item.get('filename')
        rss_title = item.get('rss_title', '')
        detail_url = item.get('detail_url', '')

        if not filename:
            # 尝试从 rss_title 提取（作为后备）
            filename = item.get('rss_title', '')

        if not filename:
            results["failures"]["parse_error"].append({
                "filename": "N/A",
                "rss_title": rss_title,
                "error": "no filename extracted"
            })
            continue

        try:
            metadata = renamer._extract_with_regex(filename)
            release_group = metadata.get("release_group") or "Unknown"

            # 判断识别结果
            has_show = bool(metadata.get("show_name"))
            has_episode = bool(metadata.get("episode"))
            # season 缺失不一定是错误（对于电影）

            issues = []
            if not has_show:
                issues.append("missing_show_name")
            if not has_episode:
                issues.append("missing_episode")
            # season 缺失暂不列为失败

            # 保存样本详情
            sample_detail = {
                "filename": filename,
                "rss_title": rss_title,
                "detail_url": detail_url,
                "release_group": release_group,
                "parsed": {
                    "show_name": metadata.get("show_name"),
                    "season": metadata.get("season"),
                    "episode": metadata.get("episode"),
                    "media_type": metadata.get("media_type")
                },
                "issues": issues,
                "is_success": len(issues) == 0
            }
            results["samples"].append(sample_detail)

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
                    results["by_release_group"][release_group]["samples"].append(sample_detail)
            else:
                # 记录成功
                results["success"].append(sample_detail)
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
    """生成测试报告（纯文本）"""
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
            for item in items[:5]:
                report.append(f"    - {item['filename'][:60]}...")
                if "parsed" in item:
                    m = item["parsed"]
                    report.append(f"      解析: show={m.get('show_name')}, S={m.get('season')}, E={m.get('episode')}, media={m.get('media_type')}")
            if len(items) > 5:
                report.append(f"    ... 还有 {len(items) - 5} 个")
            report.append("")

    # 按字幕组统计（失败率 > 0 的）
    report.append("-" * 80)
    report.append("按字幕组统计 (失败率高的需要重点关注):")
    report.append("-" * 80)

    group_stats = []
    for group, stats in results["by_release_group"].items():
        total_group = stats["success"] + stats["fail"]
        if total_group > 0:
            fail_rate = stats["fail"] / total_group * 100
            group_stats.append((group, stats, fail_rate, total_group))

    group_stats.sort(key=lambda x: (-x[2], -x[3]))  # 按失败率降序，然后按样本数降序

    for group, stats, fail_rate, total_group in group_stats:
        status = "[需要关注]" if fail_rate >= 50 else "[正常]"
        report.append(f"  {group}: {stats['success']}/{total_group} 成功 ({100-fail_rate:.0f}% 成功率) {status}")
        if stats["samples"]:
            for sample in stats["samples"][:2]:
                issues_str = ", ".join(sample.get("issues", []))
                report.append(f"    - {sample['filename'][:50]}... (issues: {issues_str})")

    report.append("")
    report.append("-" * 80)
    report.append("成功识别样本 (前15个):")
    report.append("-" * 80)
    for item in results["success"][:15]:
        p = item["parsed"]
        try:
            season_str = f"{int(p.get('season', 1)):02d}" if p.get('season') else "01"
            episode_str = f"{int(p['episode']):03d}" if p.get('episode') else "???"
        except:
            season_str = str(p.get('season', '?'))
            episode_str = str(p.get('episode', '?'))
        report.append(f"  {p.get('show_name', 'N/A'):<30} S{season_str}E{episode_str} [{item['release_group']}]")

    return "\n".join(report)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50, help="抓取数量")
    parser.add_argument("--config", default="config.ini", help="配置文件路径")
    parser.add_argument("--offline", action="store_true", help="使用缓存，不重新抓取")
    parser.add_argument("--output", default="dmhy_results.json", help="输出文件")
    args = parser.parse_args()

    cache_file = Path(__file__).parent / "dmhy_cache_detailed.json"

    # 第一步：获取详情页 URL 列表
    if args.offline and cache_file.exists():
        with open(cache_file, 'r', encoding='utf-8') as f:
            items = json.load(f)
        print(f"从缓存加载 {len(items)} 条记录")
    else:
        rss_items = fetch_rss_item_details(args.limit)
        # 第二步：访问每个详情页提取真实文件名
        items = []
        for idx, item in enumerate(rss_items, 1):
            print(f"[{idx}/{len(rss_items)}] 获取详情: {item['rss_title'][:50]}...")
            filename = extract_filename_from_detail(item['detail_url'])
            if filename:
                items.append({
                    **item,
                    'filename': filename
                })
                print(f"  提取到: {filename}")
            else:
                print(f"  未能提取文件名，跳过")

        # 保存缓存
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print(f"保存 {len(items)} 条到缓存")

    if not items:
        print("未获取到任何文件名，退出")
        return

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
    print(f"\n开始测试 {len(items)} 个文件名...")
    results = test_batch_filenames(items, renamer)

    # 生成报告
    report = generate_report(results)
    print(report)

    # 保存完整结果
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n完整结果已保存: {args.output}")


if __name__ == "__main__":
    main()
