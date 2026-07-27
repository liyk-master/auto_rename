"""
分类检测 — 根据元数据确定视频的分类目录
"""

import re
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 默认字幕组与内容类型映射
# content_type: anime=动漫, drama=电视剧, movie=电影
DEFAULT_RELEASE_GROUP_MAPPING = {
    # ====== 国漫字幕组（明确映射到 anime）======
    "VARYG": "anime", "Mortal": "anime", "Linn": "anime",
    "锅巴": "anime", "未定": "anime", "动漫花园": "anime",
    "GM-Team": "anime", "GM Team": "anime",
    # ====== 动漫字幕组 ======
    "VCB-Studio": "anime", "vcb-studio": "anime", "Vcbstudio": "anime",
    "Nekomoe kissaten": "anime", "Nekomoe": "anime",
    "喵萌奶茶屋": "anime", "喵萌": "anime",
    "动漫国字幕组": "anime", "动漫国": "anime",
    "Lilith-Raws": "anime", "Lilith": "anime",
    "LowPower-Raws": "anime", "LowPower": "anime",
    "EMR": "anime", "Moozzi2": "anime", "Reinforce": "anime",
    "Airota": "anime", "Kona": "anime",
    "Yousei-raws": "anime", "Yousei": "anime",
    "ANK-Raws": "anime", "ANK": "anime",
    "Sakurato": "anime", "Fumi-Raws": "anime", "Fumi": "anime",
    "Mingy": "anime", "MING": "anime",
    "ANi": "anime", "ANi-Raws": "anime",
    "Pas de Pop": "anime", "Pop": "anime",
    "SubsPlease": "anime", "Erai-raws": "anime",
    "HorribleRips": "anime", "Crackle": "anime",
    "Kodomount": "anime", "Mizuki": "anime",
    "Asakura": "anime", "NAG": "anime",
    "J播种": "anime", "DMG": "anime",
    "CASO": "anime", "SumiSora": "anime", "Sumi": "anime",
    "FLsnow": "anime", "FL": "anime",
    "XKsub": "anime", "XK": "anime",
    "Zeyao": "anime", "NC-Raws": "anime", "NC": "anime",
    "百冬练习生": "anime", "MISO": "anime",
    "Bean": "anime", "BeanSub": "anime", "FZSD": "anime",
    "SweetSub": "anime", "Sweet": "anime",
    "A-F": "anime", "SDMN": "anime",
    "UHA-Wings": "anime", "Wings": "anime",
    "NPU": "anime", "KTXP": "anime",
    "MCE翻译组": "anime",
    "极光字幕": "anime", "动音漫影": "anime", "星辰国漫": "anime",
    "幻樱字幕": "anime", "华盟字幕": "anime",
    "雪飘": "anime", "雪飘工作室": "anime",
    "澄空学园": "anime", "天月": "anime",
    "悠哈璃羽": "anime", "璃羽": "anime",
    "LoliHouse": "anime", "Loli": "anime",
    "Sakura": "anime",
    "诸神字幕": "anime", "诸神": "anime", "Kamigami": "anime",
    "千羽": "anime", "梦蓝": "anime", "风之圣殿": "anime",
    "Haolin": "anime", "好林": "anime", "枫林社": "anime",
    "喵森": "anime",
    "Moe": "anime", "Moe-Raws": "anime",
    "爱咕噜": "anime", "爱咕噜字幕": "anime",
    "迪迪": "anime", "迪迪字幕": "anime",
    "Luminous": "anime", "Luminous字幕": "anime",
    "Kaleido": "anime", "Kaleido字幕": "anime",
    "Octopus": "anime", "Octopus字幕": "anime",
    "橘花": "anime", "橘花字幕": "anime",
    "星梦": "anime", "星梦字幕": "anime",
    "白羽": "anime", "白羽字幕": "anime",
    "天道": "anime", "天道字幕": "anime",
    "轻之国度": "anime", "轻国": "anime",
    "异域": "anime", "异域字幕": "anime",
    "小p优优": "anime", "小p": "anime",
    "吹雪": "anime", "吹雪字幕": "anime",
    "丸子": "anime", "丸子字幕": "anime",
    "小程序": "anime", "小程序字幕": "anime",
    "初音": "anime", "初音字幕": "anime",
    "晓星": "anime", "晓星字幕": "anime",
    "千夏": "anime", "千夏字幕": "anime",
    "萌月": "anime", "萌月字幕": "anime",
    "肉粽": "anime", "肉粽字幕": "anime",
    "星空": "anime", "星空字幕": "anime",
    "乐园": "anime", "乐园字幕": "anime",
    "腾讯动漫": "anime",
    "SAGI": "anime", "Raku": "anime",
    "Zero-Raws": "anime", "Dazuraw": "anime",
    "KODAW": "anime", "沦波": "anime", "八王子": "anime",
    "Leopard-Raws": "anime", "IrizaRaws": "anime",
    "Kiss-Sub": "anime", "M-T": "anime",
    "WOLF": "anime", "WMSUB": "anime",
    "Studio GreenTea": "anime", "GreenTea": "anime",
    "orion origin": "anime", "Orion Origin": "anime",
    "FLSNOW": "anime",
    "MagicStar": "drama",
    "AI-Raws": "anime", "AIRaws": "anime",
    "Zero动漫": "anime", "GHOST": "anime",
    "Doomdos": "anime",
    # ====== 电视剧/综艺字幕组 ======
    "神舌字幕组": "drama", "神舌": "drama",
    "人人影视": "drama", "人人": "drama",
    "FIX字幕侠": "drama", "FIX": "drama",
    "追新番": "drama", "迅影网": "drama",
    "Sub Haddad": "drama", "土耳其语字幕": "drama",
    "凤凰天使": "drama", "凤凰天使字幕组": "drama",
    "韩迷字幕组": "drama", "韩迷": "drama",
    "幻想乐园": "drama", "悠乐": "drama",
    "橘子海外剧": "drama",
    "Dream字幕组": "drama", "Dream": "drama",
    "擦枪字幕": "drama", "擦枪": "drama",
    "射手字幕": "drama", "射手": "drama",
    "翻托邦字幕组": "drama", "翻托邦": "drama",
    "远鉴字幕组": "drama", "远鉴": "drama",
    "小玩剧字幕组": "drama", "小玩剧": "drama",
    "圣城字幕组": "drama", "圣城": "drama",
    "TDMSub": "drama",
    "百事特字幕": "drama", "百事特": "drama",
    "百科园字幕组": "drama",
    "YYeTs字幕组": "drama",
    "韩剧tv": "drama", "欧乐": "drama",
    "看韩剧": "drama", "韩剧热线": "drama",
    "韩流": "drama", "韩家园": "drama",
    "字幕港": "drama",
    "日菁字幕": "drama", "日菁": "drama",
    "东京字幕": "drama", "猪猪字幕": "drama",
    "弯弯字幕": "drama", "弯弯": "drama",
    "台剧字幕": "drama",
    "TVB": "drama", "粤语字幕": "drama",
    "飞屋字幕": "drama", "飞屋": "drama",
    "满汉全席": "drama", "破晓字幕": "drama", "破晓": "drama",
    "YYT": "drama", "听字幕": "drama",
    "R3字幕": "drama", "KRL字幕": "drama",
}


def determine_anime_subcategory(
    metadata: Dict, origin_countries: List, original_language: str,
) -> str:
    """根据元数据确定动漫子分类（国漫、日番、欧美动漫等）"""
    chinese_countries = ["CN", "HK", "TW"]
    english_countries = ["US", "GB", "CA", "AU", "NZ"]

    has_cn = any(country in chinese_countries for country in origin_countries)
    has_jp = any(country in ["JP", "日本"] for country in origin_countries)
    has_en = any(country in english_countries for country in origin_countries)

    if has_cn and has_jp:
        if original_language in ["zh", "cn", "zh-cn", "zh-tw", "zh-hk"]:
            return "国漫"
        elif original_language in ["ja", "ja-jp"]:
            return "日番"
        else:
            title = metadata.get("show_name", "") or metadata.get("original_show_name", "")
            return "国漫" if re.search(r"[一-鿿]", title) else "日番"
    elif has_cn:
        return "国漫"
    elif has_jp:
        return "日番"
    elif has_en:
        return "欧美动漫"
    elif original_language in ["zh", "cn", "zh-cn", "zh-tw", "zh-hk"]:
        return "国漫"
    elif original_language in ["ja", "ja-jp"]:
        return "日番"
    elif original_language in ["en", "en-us", "en-gb"]:
        return "欧美动漫"
    else:
        title = metadata.get("show_name", "") or metadata.get("original_show_name", "")
        if re.search(r"[぀-ヿ]", title):
            return "日番"
        elif re.search(r"[一-鿿]", title):
            return "国漫"
        else:
            return "其他动漫"


def determine_category(
    metadata: Dict,
    release_group_mapping: Dict[str, str],
    tmdb_id: Optional[str] = None,
) -> str:
    """
    根据元数据确定视频的分类目录

    Args:
        metadata: 包含视频元数据的字典
        release_group_mapping: 字幕组→内容类型映射
        tmdb_id: TMDB ID（可选，用于判断是否有 TMDB 结果）

    Returns:
        str: 分类目录路径
    """
    release_group = metadata.get("release_group", "")
    forced_content_type = None
    if release_group:
        if release_group in release_group_mapping:
            forced_content_type = release_group_mapping[release_group]
            logger.debug(f"字幕组 '{release_group}' 映射到类型: {forced_content_type}（后备）")

    original_language = metadata.get("original_language", "").lower()
    origin_countries = metadata.get("origin_country", [])
    genres = metadata.get("genres", [])
    genre_names = [genre.lower() for genre in genres]

    chinese_countries = ["CN", "HK", "TW"]
    english_countries = ["US", "GB", "CA", "AU", "NZ"]
    asian_countries = ["JP", "KR", "TH", "IN"]

    sub_category = ""
    base_category = "Other"

    media_type = metadata.get("media_type")
    if media_type == "movie":
        base_category = "Movies"
        if any(genre in genre_names for genre in ["animation", "animated", "动画"]):
            sub_category = "动画电影"
        else:
            original_title = metadata.get("original_title", "")
            if original_title and re.search(r"[一-鿿]", original_title):
                sub_category = "华语电影"
            elif original_language in ["zh", "cn"] or any(
                country in chinese_countries for country in origin_countries
            ):
                sub_category = "华语电影"
            else:
                sub_category = "外语电影"
    elif media_type == "tv":
        base_category = "TV Shows"
        if any(genre in genre_names for genre in ["documentary", "纪录片", "纪录"]):
            sub_category = "纪录片"
        elif any(genre in genre_names for genre in ["reality", "variety", "综艺", "game show", "真人秀"]):
            sub_category = "综艺"
        elif any(genre in genre_names for genre in ["animation", "animated", "动画"]):
            sub_category = determine_anime_subcategory(metadata, origin_countries, original_language)
        elif any(genre in genre_names for genre in ["kids", "children", "child", "儿童", "family"]):
            sub_category = "儿童"
        else:
            if forced_content_type == "anime":
                sub_category = determine_anime_subcategory(metadata, origin_countries, original_language)
                logger.info(f"基于字幕组映射判定为动漫: {sub_category}")
            elif original_language in ["zh", "cn"] or any(
                country in chinese_countries for country in origin_countries
            ):
                sub_category = "国产剧"
            elif original_language in ["en"] or any(
                country in english_countries for country in origin_countries
            ):
                sub_category = "欧美剧"
            elif original_language in ["ja", "ko", "th", "hi"] or any(
                country in ["JP", "日本"] for country in origin_countries
            ):
                sub_category = "日韩剧"
            else:
                sub_category = "欧美剧"
    else:
        base_category = "Other"

    # 后备逻辑：TMDB 没有明确分类时使用字幕组映射
    if not sub_category or sub_category == "未分类" or not tmdb_id:
        if forced_content_type:
            logger.info(f"TMDB没有明确分类或未搜索到结果，使用字幕组映射: {forced_content_type}")
            if forced_content_type == "anime":
                base_category = "TV Shows"
                if original_language in ["ja", "ja-jp"] or any(
                    country in ["JP", "日本"] for country in origin_countries
                ):
                    sub_category = "日番"
                elif original_language in ["zh", "cn", "zh-cn", "zh-tw", "zh-hk"] or any(
                    country in chinese_countries for country in origin_countries
                ):
                    sub_category = "国漫"
                elif original_language in ["en", "en-us", "en-gb"] or any(
                    country in english_countries for country in origin_countries
                ):
                    sub_category = "欧美动漫"
                else:
                    title = metadata.get("show_name", "") or metadata.get("original_show_name", "")
                    if re.search(r"[぀-ヿ]", title):
                        sub_category = "日番"
                    elif re.search(r"[一-鿿]", title):
                        sub_category = "国漫"
                    else:
                        sub_category = "其他动漫"
            elif forced_content_type == "drama":
                base_category = "TV Shows"
                if original_language in ["zh", "cn"] or any(
                    country in chinese_countries for country in origin_countries
                ):
                    sub_category = "国产剧"
                elif original_language in ["en"] or any(
                    country in english_countries for country in origin_countries
                ):
                    sub_category = "欧美剧"
                elif original_language in ["ja", "ko", "th", "hi"] or any(
                    country in asian_countries for country in origin_countries
                ):
                    sub_category = "日韩剧"
                else:
                    title = metadata.get("show_name", "") or metadata.get("original_show_name", "")
                    if re.search(r"[぀-ヿ]", title):
                        sub_category = "日番"
                    elif re.search(r"[一-鿿]", title):
                        sub_category = "国产剧"
                    else:
                        sub_category = "其他剧"
            elif forced_content_type == "movie":
                base_category = "Movies"
                if any(genre in genre_names for genre in ["animation", "animated", "动画"]):
                    sub_category = "动画电影"
                else:
                    sub_category = "外语电影"
        else:
            if media_type == "tv":
                base_category = "TV Shows"
                title = metadata.get("show_name", "") or metadata.get("original_show_name", "")
                if re.search(r"[぀-ヿ]", title):
                    sub_category = "日番"
                elif re.search(r"[一-鿿]", title):
                    sub_category = "国产剧"
                else:
                    sub_category = "欧美剧"
            elif media_type == "movie":
                base_category = "Movies"
                sub_category = "外语电影"

    return f"{base_category}/{sub_category}"