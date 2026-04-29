#!/usr/bin/env python3
"""
从 dmhy RSS 抓取真实视频文件名（从详情页 file_list 提取）
"""
import re
import sys
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("请安装依赖: pip install requests beautifulsoup4")
    sys.exit(1)

RSS_URL = "https://dmhy.org/topics/rss/rss.xml"


def fetch_rss_items(limit=50):
    """从 RSS 获取种子列表"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print(f"正在获取 RSS: {RSS_URL}")
    response = requests.get(RSS_URL, headers=headers, timeout=30)
    response.raise_for_status()

    # dmhy RSS 是 GBK 编码
    response.encoding = "gbk"

    root = ET.fromstring(response.content)

    # RSS 格式: <rss><channel><item>...</item>...</channel></rss>
    items = []
    channel = root.find('.//channel')
    if channel is not None:
        for item in channel.findall('item'):
            title = item.findtext('title', '').strip()
            link = item.findtext('link', '').strip()
            pub_date = item.findtext('pubDate', '').strip()

            if link:
                items.append({
                    'title': title,
                    'link': link,
                    'pub_date': pub_date
                })

            if len(items) >= limit:
                break

    print(f"共获取 {len(items)} 条 RSS 记录")
    return items


def fetch_file_list_from_detail(detail_url):
    """从详情页提取真正的视频文件名"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(detail_url, headers=headers, timeout=15)
        response.raise_for_status()
        response.encoding = "utf-8"

        soup = BeautifulSoup(response.text, "html.parser")

        # 查找 file_list div
        file_list_div = soup.find("div", class_="file_list")
        if not file_list_div:
            return None

        # 提取第一个文件名（通常是主文件/最大的文件）
        li_items = file_list_div.find_all("li")
        if not li_items:
            return None

        filenames = []
        for li in li_items[:5]:  # 取前5个文件
            # 文件名在 li 的直接文本中
            text = li.get_text(strip=True, separator=" ")
            # 文件名格式：[Nekomoe kissaten][Shunkashuutou...][05][1080p][JPSC].mp4 442MB
            # 需要提取 .mp4 前面的部分
            match = re.search(r'\[.*?\]\[.*?\].*?\.[a-zA-Z0-9]+', text)
            if match:
                filename = match.group(0)
                filenames.append(filename)

        return filenames[0] if filenames else None

    except Exception as e:
        print(f"  获取详情页失败: {e}")
        return None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50, help="抓取数量")
    parser.add_argument("--output", default="dmhy_filenames.json", help="输出文件")
    parser.add_argument("--use-cache", action="store_true", help="使用已存在的缓存文件")
    args = parser.parse_args()

    cache_file = Path(args.output)

    if args.use_cache and cache_file.exists():
        print(f"从缓存加载: {cache_file}")
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            filenames = data.get('filenames', [])
            print(f"加载了 {len(filenames)} 个文件名")
    else:
        # 获取 RSS 列表
        rss_items = fetch_rss_items(args.limit)

        # 访问每个详情页获取真实文件名
        filenames = []
        for idx, item in enumerate(rss_items, 1):
            print(f"[{idx}/{len(rss_items)}] 处理: {item['title'][:50]}...")

            detail_url = item['link']
            filename = fetch_file_list_from_detail(detail_url)

            if filename:
                filenames.append({
                    'filename': filename,
                    'rss_title': item['title'],
                    'link': detail_url
                })
                print(f"  提取到: {filename}")
            else:
                print(f"  未能提取文件名")

        # 保存缓存
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump({
                'filenames': filenames,
                'count': len(filenames)
            }, f, ensure_ascii=False, indent=2)
        print(f"\n保存 {len(filenames)} 个文件名到: {cache_file}")

    # 打印统计
    print(f"\n{'='*60}")
    print(f"共获取 {len(filenames)} 个真实视频文件名")
    print(f"{'='*60}")

    # 显示前10个样本
    print("\n样本数据（前10个）:")
    for item in filenames[:10]:
        print(f"  - {item['filename']}")


if __name__ == "__main__":
    main()
