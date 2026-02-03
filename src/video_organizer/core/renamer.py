"""
Module for extracting metadata from video files and generating new names.
"""

import os
import re
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Union

from jinja2 import Template
from src.video_organizer.core.tmdb_client import TMDBClient
from src.video_organizer.utils.llm_translator import LLMTranslator

logger = logging.getLogger(__name__)


class VideoRenamer:
    """Extracts metadata from video files and generates organized paths."""

    # 默认命名规则模板
    DEFAULT_NAMING_RULES = {
        "tv_show": "{show_name}{year_suffix}{tmdbid_suffix}/Season {season:02d}/{show_name} {season_episode}{quality_tags_suffix}{release_group_suffix}",
        "movie": "{movie_name}{year_suffix}{tmdbid_suffix}/{movie_name}{en_title_suffix}{year_suffix}{quality_tags_suffix}{release_group_suffix}",
        "anime": "{anime_name}/{season_name}/{anime_name} - S{season:02d}E{episode:02d}{quality_tags_suffix}{release_group_suffix}",
        "simple": "{title}{quality_tags_suffix}{release_group_suffix}",
    }

    # 默认字幕组与内容类型映射
    # content_type: anime=动漫, drama=电视剧, movie=电影
    DEFAULT_RELEASE_GROUP_MAPPING = {
        # ====== 国漫字幕组（明确映射到 drama）======
        # 这些字幕组主要做国产动漫/电视剧，优先使用 drama 以便通过 TMDB 信息判断子分类
        "VARYG": "drama",
        "Mortal": "drama",
        "Linn": "drama",
        "锅巴": "drama",
        "未定": "drama",
        "动漫花园": "drama",
        "GM-Team": "drama",
        "GM Team": "drama",
        # ====== 动漫字幕组 ======
        "VCB-Studio": "anime",
        "vcb-studio": "anime",
        "Vcbstudio": "anime",
        "Nekomoe kissaten": "anime",
        "Nekomoe": "anime",
        "喵萌奶茶屋": "anime",
        "喵萌": "anime",
        "动漫国字幕组": "anime",
        "动漫国": "anime",
        "Lilith-Raws": "anime",
        "Lilith": "anime",
        "LowPower-Raws": "anime",
        "LowPower": "anime",
        "EMR": "anime",
        "Moozzi2": "anime",
        "Reinforce": "anime",
        "Airota": "anime",
        "Kona": "anime",
        "Yousei-raws": "anime",
        "Yousei": "anime",
        "ANK-Raws": "anime",
        "ANK": "anime",
        "Sakurato": "anime",
        "Fumi-Raws": "anime",
        "Fumi": "anime",
        "Mingy": "anime",
        "MING": "anime",
        "ANi": "anime",
        "ANi-Raws": "anime",
        "Pas de Pop": "anime",
        "Pop": "anime",
        "SubsPlease": "anime",
        "Erai-raws": "anime",
        "HorribleRips": "anime",
        "Crackle": "anime",
        "Kodomount": "anime",
        "Mizuki": "anime",
        "Asakura": "anime",
        "NAG": "anime",
        "J播种": "anime",
        "DMG": "anime",
        "CASO": "anime",
        "SumiSora": "anime",
        "Sumi": "anime",
        "FLsnow": "anime",
        "FL": "anime",
        "XKsub": "anime",
        "XK": "anime",
        "Zeyao": "anime",
        "NC-Raws": "anime",
        "NC": "anime",
        "百冬练习生": "anime",
        "MISO": "anime",
        "Bean": "anime",
        "BeanSub": "anime",
        "FZSD": "anime",
        "SweetSub": "anime",
        "Sweet": "anime",
        "A-F": "anime",
        "SDMN": "anime",
        "Web-Raws": "anime",
        "UHA-Wings": "anime",
        "Wings": "anime",
        "NPU": "anime",
        "KTXP": "anime",
        "MCE翻译组": "anime",
        "极光字幕": "anime",
        "动音漫影": "anime",
        "星辰国漫": "anime",
        "幻樱字幕": "anime",
        "华盟字幕": "anime",
        "雪飘": "anime",
        "澄空学园": "anime",
        "天月": "anime",
        "悠哈璃羽": "anime",
        "璃羽": "anime",
        "LoliHouse": "anime",
        "Loli": "anime",
        "Sakura": "anime",
        "诸神字幕": "anime",
        "诸神": "anime",
        "Kamigami": "anime",
        "千羽": "anime",
        "梦蓝": "anime",
        "风之圣殿": "anime",
        "Haolin": "anime",
        "好林": "anime",
        "枫林社": "anime",
        "喵森": "anime",
        "Moe": "anime",
        "Moe-Raws": "anime",
        "爱咕噜": "anime",
        "爱咕噜字幕": "anime",
        "迪迪": "anime",
        "迪迪字幕": "anime",
        "Luminous": "anime",
        "Luminous字幕": "anime",
        "Kaleido": "anime",
        "Kaleido字幕": "anime",
        "Octopus": "anime",
        "Octopus字幕": "anime",
        "橘花": "anime",
        "橘花字幕": "anime",
        "星梦": "anime",
        "星梦字幕": "anime",
        "白羽": "anime",
        "白羽字幕": "anime",
        "天道": "anime",
        "天道字幕": "anime",
        "轻之国度": "anime",
        "轻国": "anime",
        "异域": "anime",
        "异域字幕": "anime",
        "小p优优": "anime",
        "小p": "anime",
        "吹雪": "anime",
        "吹雪字幕": "anime",
        "丸子": "anime",
        "丸子字幕": "anime",
        "小程序": "anime",
        "小程序字幕": "anime",
        "初音": "anime",
        "初音字幕": "anime",
        "晓星": "anime",
        "晓星字幕": "anime",
        "千夏": "anime",
        "千夏字幕": "anime",
        "萌月": "anime",
        "萌月字幕": "anime",
        "肉粽": "anime",
        "肉粽字幕": "anime",
        "星空": "anime",
        "星空字幕": "anime",
        "乐园": "anime",
        "乐园字幕": "anime",
        "动漫花园": "anime",
        "腾讯动漫": "anime",
        "SAGI": "anime",
        "Raku": "anime",
        "Zero-Raws": "anime",
        "Dazuraw": "anime",
        "KODAW": "anime",
        "沦波": "anime",
        "八王子": "anime",
        "Leopard-Raws": "anime",
        "IrizaRaws": "anime",
        "Kiss-Sub": "anime",
        "M-T": "anime",
        "WOLF": "anime",
        "WMSUB": "anime",
        "Studio GreenTea": "anime",
        "GreenTea": "anime",
        "orion origin": "anime",
        "Orion Origin": "anime",
        "FLsnow": "anime",
        "FLSNOW": "anime",
        "MagicStar": "drama",
        "AI-Raws": "anime",
        "AIRaws": "anime",
        "雪飘工作室": "anime",
        "雪飘": "anime",
        "Xing": "anime",
        "Yami-Sub": "anime",
        "Zero动漫": "anime",
        "BlueStar": "anime",
        "Chotab": "anime",
        "Creepy": "anime",
        "FANS": "anime",
        "FREEDOM": "anime",
        "GHOST": "anime",
        "Lank": "anime",
        "LBC": "anime",
        "LOST": "anime",
        "LPD": "anime",
        "OPUS": "anime",
        "RIP": "anime",
        "SDR": "anime",
        "SEE": "anime",
        "SIN": "anime",
        "SMD": "anime",
        "SND": "anime",
        "SOL": "anime",
        "SP": "anime",
        "SUB": "anime",
        "SUN": "anime",
        "SUP": "anime",
        "SVD": "anime",
        "TCC": "anime",
        "THR": "anime",
        "TK": "anime",
        "TLC": "anime",
        "TMH": "anime",
        "TNG": "anime",
        "TOK": "anime",
        "UB": "anime",
        "UE": "anime",
        "UI": "anime",
        "UL": "anime",
        "UP": "anime",
        "VA": "anime",
        "VEC": "anime",
        "VI": "anime",
        "VIC": "anime",
        "VRR": "anime",
        "WAL": "anime",
        "WCD": "anime",
        "WDS": "anime",
        "WEC": "anime",
        "WHD": "anime",
        "WHITE": "anime",
        "WLF": "anime",
        "WMM": "anime",
        "WNF": "anime",
        "WOP": "anime",
        "WRA": "anime",
        "WSC": "anime",
        "WSP": "anime",
        "WTK": "anime",
        "XX": "anime",
        "XA": "anime",
        "XD": "anime",
        "XE": "anime",
        "XF": "anime",
        "XH": "anime",
        "XI": "anime",
        "XJ": "anime",
        "XM": "anime",
        "XN": "anime",
        "XO": "anime",
        "XPX": "anime",
        "XQ": "anime",
        "XRC": "anime",
        "XT": "anime",
        "XV": "anime",
        "YB": "anime",
        "YD": "anime",
        "YE": "anime",
        "YFB": "anime",
        "YH": "anime",
        "YI": "anime",
        "YJ": "anime",
        "YK": "anime",
        "YL": "anime",
        "YM": "anime",
        "YN": "anime",
        "YO": "anime",
        "YP": "anime",
        "YQ": "anime",
        "YR": "anime",
        "YS": "anime",
        "YSH": "anime",
        "YT": "anime",
        "YTC": "anime",
        "YU": "anime",
        "YUE": "anime",
        "YW": "anime",
        "YY": "anime",
        "ZA": "anime",
        "ZB": "anime",
        "ZC": "anime",
        "ZD": "anime",
        "ZE": "anime",
        "ZF": "anime",
        "ZG": "anime",
        "ZH": "anime",
        "ZI": "anime",
        "ZJ": "anime",
        "ZK": "anime",
        "ZL": "anime",
        "ZM": "anime",
        "ZN": "anime",
        "ZO": "anime",
        "ZR": "anime",
        "ZS": "anime",
        "ZSH": "anime",
        "ZT": "anime",
        "ZTV": "anime",
        "ZY": "anime",
        "ZZ": "anime",
        "Doomdos": "anime",
        "动漫花园": "anime",
        "腾讯动漫": "anime",
        "Acer": "anime",
        "Kfps": "anime",
        "Aurogon": "anime",
        "GPA": "anime",
        "HRC": "anime",
        "HRS": "anime",
        "HYS": "anime",
        "K6": "anime",
        "KD": "anime",
        "KEX": "anime",
        "KHB": "anime",
        "KID": "anime",
        "KMR": "anime",
        "KRC": "anime",
        "LCW": "anime",
        "LDL": "anime",
        "LHC": "anime",
        "LRC": "anime",
        "LRS": "anime",
        "LSP": "anime",
        "LTH": "anime",
        "LWC": "anime",
        "LZR": "anime",
        "MDR": "anime",
        "MHT": "anime",
        "MPS": "anime",
        "MSR": "anime",
        "MST": "anime",
        "MTH": "anime",
        "MTK": "anime",
        "MUM": "anime",
        "NAN": "anime",
        "NAX": "anime",
        "NBS": "anime",
        "NCT": "anime",
        "ND": "anime",
        "NF": "anime",
        "NH": "anime",
        "NK": "anime",
        "NL": "anime",
        "NOW": "anime",
        "NR": "anime",
        "NSD": "anime",
        "NV": "anime",
        "OBS": "anime",
        "OFA": "anime",
        "OPF": "anime",
        "ORA": "anime",
        "ORB": "anime",
        "ORZ": "anime",
        "OSR": "anime",
        "OTC": "anime",
        "OTW": "anime",
        "PBF": "anime",
        "PBL": "anime",
        "PBT": "anime",
        "PDV": "anime",
        "PNA": "anime",
        "PNR": "anime",
        "POL": "anime",
        "POS": "anime",
        "PPA": "anime",
        "PPK": "anime",
        "PRE": "anime",
        "PRG": "anime",
        "PRO": "anime",
        "PRR": "anime",
        "PSY": "anime",
        "PTA": "anime",
        "PTB": "anime",
        "PTC": "anime",
        "PTN": "anime",
        "PTT": "anime",
        "PUM": "anime",
        "QD": "anime",
        "QIE": "anime",
        "QM": "anime",
        "QMS": "anime",
        "QMT": "anime",
        "QMX": "anime",
        "RAV": "anime",
        "RBY": "anime",
        "RCC": "anime",
        "RCM": "anime",
        "RCS": "anime",
        "RDD": "anime",
        "RDF": "anime",
        "RDM": "anime",
        "REF": "anime",
        "REM": "anime",
        "REX": "anime",
        "RFF": "anime",
        "RFT": "anime",
        "RHI": "anime",
        "RHT": "anime",
        "ROI": "anime",
        "ROX": "anime",
        "RSD": "anime",
        "RTH": "anime",
        "RTT": "anime",
        "SBC": "anime",
        "SBD": "anime",
        "SBK": "anime",
        "SCO": "anime",
        "SCP": "anime",
        "SDR": "anime",
        "SEG": "anime",
        "SFT": "anime",
        "SHK": "anime",
        "SHP": "anime",
        "SHT": "anime",
        "SIC": "anime",
        "SLC": "anime",
        "SLK": "anime",
        "SLO": "anime",
        "SLR": "anime",
        "SMD": "anime",
        "SMI": "anime",
        "SMS": "anime",
        "SND": "anime",
        "SOP": "anime",
        "SOS": "anime",
        "SPC": "anime",
        "SPK": "anime",
        "SRD": "anime",
        "SRR": "anime",
        "SSC": "anime",
        "SSH": "anime",
        "SSR": "anime",
        "STA": "anime",
        "STB": "anime",
        "STC": "anime",
        "STD": "anime",
        "STE": "anime",
        "STH": "anime",
        "STL": "anime",
        "STN": "anime",
        "STP": "anime",
        "STR": "anime",
        "STS": "anime",
        "STW": "anime",
        "TAI": "anime",
        "TAM": "anime",
        "TBL": "anime",
        "TBZ": "anime",
        "TCD": "anime",
        "TCE": "anime",
        "TCO": "anime",
        "TDD": "anime",
        "TDE": "anime",
        "TDM": "anime",
        "TDS": "anime",
        "TEC": "anime",
        "TKC": "anime",
        "TNC": "anime",
        "TNX": "anime",
        "TOC": "anime",
        "TPA": "anime",
        "TPD": "anime",
        "TRI": "anime",
        "TRL": "anime",
        "TSA": "anime",
        "TSC": "anime",
        "TSE": "anime",
        "TSF": "anime",
        "TSK": "anime",
        "TTC": "anime",
        "TTE": "anime",
        "TTO": "anime",
        "TVC": "anime",
        "TVE": "anime",
        "TVR": "anime",
        "TX": "anime",
        "TY": "anime",
        "TZ": "anime",
        "UB": "anime",
        "UC": "anime",
        "UD": "anime",
        "UG": "anime",
        "UH": "anime",
        "UM": "anime",
        "UN": "anime",
        "UR": "anime",
        "UT": "anime",
        "VA": "anime",
        "VC": "anime",
        "VD": "anime",
        "VE": "anime",
        "VH": "anime",
        "VJ": "anime",
        "VK": "anime",
        "VL": "anime",
        "VM": "anime",
        "VN": "anime",
        "VO": "anime",
        "VS": "anime",
        "VT": "anime",
        "VV": "anime",
        "VW": "anime",
        "VX": "anime",
        "WA": "anime",
        "WB": "anime",
        "WD": "anime",
        "WE": "anime",
        "WF": "anime",
        "WG": "anime",
        "WK": "anime",
        "WL": "anime",
        "WM": "anime",
        "WN": "anime",
        "WO": "anime",
        "WP": "anime",
        "WQ": "anime",
        "WR": "anime",
        "WS": "anime",
        "WT": "anime",
        "WV": "anime",
        "WW": "anime",
        "WY": "anime",
        "XA": "anime",
        "XB": "anime",
        "XC": "anime",
        "XD": "anime",
        "XE": "anime",
        "XF": "anime",
        "XG": "anime",
        "XH": "anime",
        "XI": "anime",
        "XJ": "anime",
        "XK": "anime",
        "XL": "anime",
        "XM": "anime",
        "XN": "anime",
        "XO": "anime",
        "XP": "anime",
        "XQ": "anime",
        "XR": "anime",
        "XS": "anime",
        "XT": "anime",
        "XU": "anime",
        "XV": "anime",
        "XW": "anime",
        "XX": "anime",
        "XY": "anime",
        "XZ": "anime",
        "YA": "anime",
        "YB": "anime",
        "YC": "anime",
        "YD": "anime",
        "YE": "anime",
        "YF": "anime",
        "YG": "anime",
        "YH": "anime",
        "YI": "anime",
        "YJ": "anime",
        "YK": "anime",
        "YL": "anime",
        "YM": "anime",
        "YN": "anime",
        "YO": "anime",
        "YP": "anime",
        "YQ": "anime",
        "YR": "anime",
        "YS": "anime",
        "YT": "anime",
        "YU": "anime",
        "YV": "anime",
        "YW": "anime",
        "YX": "anime",
        "YY": "anime",
        "YZ": "anime",
        "ZA": "anime",
        "ZB": "anime",
        "ZC": "anime",
        "ZD": "anime",
        "ZE": "anime",
        "ZF": "anime",
        "ZG": "anime",
        "ZH": "anime",
        "ZI": "anime",
        "ZJ": "anime",
        "ZK": "anime",
        "ZL": "anime",
        "ZM": "anime",
        "ZN": "anime",
        "ZO": "anime",
        "ZP": "anime",
        "ZQ": "anime",
        "ZR": "anime",
        "ZS": "anime",
        "ZT": "anime",
        "ZU": "anime",
        "ZV": "anime",
        "ZW": "anime",
        "ZX": "anime",
        "ZY": "anime",
        "ZZ": "anime",
        # ====== 电视剧/综艺字幕组 ======
        "神舌字幕组": "drama",
        "神舌": "drama",
        "人人影视": "drama",
        "人人": "drama",
        "FIX字幕侠": "drama",
        "FIX": "drama",
        "追新番": "drama",
        "迅影网": "drama",
        "Sub Haddad": "drama",
        "土耳其语字幕": "drama",
        "凤凰天使": "drama",
        "凤凰天使字幕组": "drama",
        "韩迷字幕组": "drama",
        "韩迷": "drama",
        "幻想乐园": "drama",
        "悠乐": "drama",
        "橘子海外剧": "drama",
        "Dream字幕组": "drama",
        "Dream": "drama",
        "擦枪字幕": "drama",
        "擦枪": "drama",
        "射手字幕": "drama",
        "射手": "drama",
        "翻托邦字幕组": "drama",
        "翻托邦": "drama",
        "远鉴字幕组": "drama",
        "远鉴": "drama",
        "小玩剧字幕组": "drama",
        "小玩剧": "drama",
        "圣城字幕组": "drama",
        "圣城": "drama",
        "TDMSub": "drama",
        "百事特字幕": "drama",
        "百事特": "drama",
        "百科园字幕组": "drama",
        "YYeTs字幕组": "drama",
        "韩剧tv": "drama",
        "欧乐": "drama",
        "看韩剧": "drama",
        "韩剧热线": "drama",
        "韩流": "drama",
        "韩家园": "drama",
        "字幕港": "drama",
        "日菁字幕": "drama",
        "日菁": "drama",
        "东京字幕": "drama",
        "猪猪字幕": "drama",
        "弯弯字幕": "drama",
        "弯弯": "drama",
        "台剧字幕": "drama",
        "TVB": "drama",
        "粤语字幕": "drama",
        "飞屋字幕": "drama",
        "飞屋": "drama",
        "满汉全席": "drama",
        "破晓字幕": "drama",
        "破晓": "drama",
        "YYT": "drama",
        "听字幕": "drama",
        "R3字幕": "drama",
        "KRL字幕": "drama",
    }

    def __init__(
        self,
        tmdb_api_key: str,
        ai_service_url: Optional[str] = None,
        watch_path: Optional[Path] = None,
        naming_rules: Optional[Dict] = None,
        llm_config: Optional[Dict] = None,
        config: Optional[Dict] = None,
    ):
        self.tmdb_client = TMDBClient(tmdb_api_key) if tmdb_api_key else None
        self.ai_service_url = ai_service_url
        self.watch_path = watch_path
        self.naming_rules = naming_rules or self.DEFAULT_NAMING_RULES
        self.config = config  # 保存完整配置对象

        # 加载字幕组映射配置
        self._release_group_mapping = dict(self.DEFAULT_RELEASE_GROUP_MAPPING)
        if config and isinstance(config, dict):
            custom_mapping = config.get("release_group_mapping", {})
            if custom_mapping:
                # 合并配置，覆盖默认映射
                self._release_group_mapping.update(custom_mapping)
                logger.info(f"加载了 {len(custom_mapping)} 个自定义字幕组映射")

        # 初始化 LLM 翻译器
        self.llm_translator = None

        # 检查是否有 LLM 翻译配置
        llm_enabled = False
        llm_api_key = None
        llm_api_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        llm_model = "GLM-4.5-Flash"

        # 优先使用 llm_translation 配置
        if llm_config and isinstance(llm_config, dict):
            llm_enabled = llm_config.get("enabled", False)
            llm_api_key = llm_config.get("api_key")
            llm_api_url = llm_config.get("api_url", llm_api_url)
            llm_model = llm_config.get("model", llm_model)

        # 如果没有 llm_translation 配置，尝试使用 ai_translate 配置
        if not llm_enabled or not llm_api_key:
            # 从配置中获取 ai_translate 配置
            ai_translate_config = {}  # 默认空配置
            if hasattr(self, "config") and isinstance(self.config, dict):
                ai_translate_config = self.config.get("ai_translate", {})
            elif hasattr(self, "_config") and isinstance(self._config, dict):
                ai_translate_config = self._config.get("ai_translate", {})

            # 检查 ai_translate 配置
            ai_translate_enabled = ai_translate_config.get("enabled", False)
            ai_translate_api_key = ai_translate_config.get("api_key")

            if ai_translate_enabled and ai_translate_api_key:
                llm_enabled = True
                llm_api_key = ai_translate_api_key
                llm_api_url = ai_translate_config.get("api_url", llm_api_url)
                llm_model = ai_translate_config.get("model", llm_model)

        # 如果有有效的配置，初始化 LLM 翻译器
        if llm_enabled and llm_api_key:
            self.llm_translator = LLMTranslator(
                api_key=llm_api_key, api_url=llm_api_url, model=llm_model
            )
            logger.info("VideoRenamer: LLM 翻译器初始化成功")

        # LLM 并发控制信号量（最多同时 2 个 LLM 调用）
        self._llm_semaphore = threading.Semaphore(2)

        # 是否启用 LLM 兜底识别（从配置读取）
        self._llm_fallback_enabled = False
        llm_fallback_config = {}
        if config and isinstance(config, dict):
            llm_fallback_config = config.get("llm_fallback", {})
        if llm_fallback_config.get("enabled", False):
            self._llm_fallback_enabled = True
            max_concurrent = llm_fallback_config.get("max_concurrent", 2)
            if max_concurrent > 0:
                self._llm_semaphore = threading.Semaphore(max_concurrent)
            logger.info(
                f"VideoRenamer: LLM 兜底识别已启用 (max_concurrent={max_concurrent})"
            )

    def extract_metadata(
        self, file_path: Union[str, Path], media_type_hint: Optional[str] = None
    ) -> Dict:
        """
        从视频文件路径中提取元数据，支持父目录信息补全。

        Args:
            file_path (Union[str, Path]): 文件路径
            media_type_hint (str, optional): 媒体类型提示（tv, movie等）

        Returns:
            Dict: 提取的元数据
        """
        try:
            if isinstance(file_path, str):
                file_path = Path(file_path)

            if not hasattr(file_path, "name"):
                logger.error(f"无效的file_path参数: {file_path}")
                return {}

            # 1. 首先尝试从文件名提取
            metadata = self._extract_with_regex(file_path.name)

            # 2. 判断是否需要从父目录补全信息
            fragment_keywords = [
                "OP",
                "ED",
                "NCOP",
                "NCED",
                "PV",
                "Trailer",
                "SP",
                "Special",
                "OVA",
                "ONA",
                "NC",
                "EXTRAS",
            ]
            extracted_show_name = metadata.get("show_name", "")

            is_fragment = extracted_show_name.upper() in fragment_keywords
            # 如果剧名全是数字（有些正则误抓），也视为无效
            is_invalid_name = extracted_show_name.isdigit()
            # 如果剧名只包含季集信息（如 S01E81），也视为无效
            is_season_episode_only = bool(re.match(r'^S\d+E\d+', extracted_show_name.upper()))

            should_lookup_parent = (
                not metadata.get("show_name") 
                or is_fragment 
                or is_invalid_name 
                or is_season_episode_only
            )

            if should_lookup_parent:
                try:
                    # 向上查找最多两级父目录
                    parent_dirs = []
                    current = file_path.parent
                    search_limit = 2
                    for _ in range(search_limit):
                        if (
                            current
                            and current.name
                            and not (current.name.endswith(":") or current.name == "/")
                        ):
                            parent_dirs.append(current)
                            current = current.parent
                        else:
                            break

                    for p_dir in parent_dirs:
                        parent_metadata = self._extract_with_regex(p_dir.name)
                        # 如果父目录能提取到剧名
                        if parent_metadata.get("show_name"):
                            # 补全缺失字段（只补全 show_name 和 year，不覆盖 season 和 episode）
                            for key in ["show_name", "year", "tmdb_id"]:
                                # 特殊逻辑：如果父目录提取的剧名包含季号（如 GGO S02），进行二次清洗
                                val = parent_metadata.get(key)
                                if key == "show_name" and val:
                                    # 再次清洗以去除 BDrip, S02 等干扰
                                    val = self._clean_filename_for_search(val)

                                # 如果是片段或季集模式，强制覆盖 show_name
                                if (is_fragment or is_season_episode_only) and key == "show_name":
                                    metadata[key] = val
                                # 否则只在字段为空时补全
                                elif not metadata.get(key) and val:
                                    metadata[key] = val

                            logger.info(
                                f"从父目录 '{p_dir.name}' 中补全了剧名: {metadata.get('show_name')}"
                            )
                            if metadata.get("show_name"):
                                break

                    if not metadata.get("show_name") and len(file_path.parts) > 1:
                        # 最后的尝试：直接拿父目录名并清洗
                        raw_parent_name = file_path.parent.name
                        metadata["show_name"] = self._clean_filename_for_search(
                            raw_parent_name
                        )

                except Exception as e:
                    logger.error(f"父目录元数据提取失败: {e}")

            # 3. 补全媒体类型
            if media_type_hint:
                metadata["media_type"] = media_type_hint

            # 4. 如果仍没有 show_name，使用智能清洗
            if not metadata.get("show_name"):
                metadata["show_name"] = (
                    self._clean_filename_for_search(file_path.name) or file_path.stem
                )

            # # 5. AI 服务辅助
            # if (self.ai_service_url and
            #     (not metadata.get('show_name') or not metadata.get('season') or not metadata.get('episode'))):
            #     try:
            #         metadata = self._extract_with_ai(file_path.name, metadata)
            #     except Exception as e:
            #         logger.error(f"AI服务提取元数据失败: {e}")

            # 6. TMDB 丰富
            if metadata.get("show_name"):
                try:
                    # Before calling TMDB, clean show_name of release group info
                    show_name = metadata["show_name"]
                    # Remove release group in brackets at the beginning
                    show_name = re.sub(r"^\[[^\]]+\]\s*", "", show_name)
                    # Remove release group without brackets at the beginning (including space-separated)
                    show_name = re.sub(r"^[A-Z]{2,6}(?:[._]|\s)\s*", "", show_name)
                    # Remove common release group tags
                    for tag in [
                        "AHTV",
                        "CCTV",
                        "BTV",
                        "HunanTV",
                        "JSTV",
                        "ZJTV",
                        "GM-Team",
                        "Team",
                        "Group",
                        "Raws",
                        "Studio",
                    ]:
                        show_name = re.sub(
                            r"^\s*" + re.escape(tag) + r"\s*",
                            "",
                            show_name,
                            flags=re.IGNORECASE,
                        )
                    metadata["show_name"] = show_name.strip()

                    metadata = self._enrich_with_tmdb(metadata)
                except Exception as e:
                    logger.error(f"TMDB元数据丰富失败: {e}")

            # 7. 最终兜底填充
            metadata.setdefault("show_name", file_path.stem)
            metadata.setdefault("original_filename", file_path.name)
            metadata.setdefault("quality_tags", "")
            metadata.setdefault("year", "")
            metadata.setdefault("tmdb_id", "")
            # 确保season和episode有默认值1，即使它们已经存在但值为None
            # 但对于电影类型，不设置默认值
            media_type = metadata.get("media_type", "")
            if media_type != "movie":
                if metadata.get("season") is None:
                    metadata["season"] = 1
                if metadata.get("episode") is None:
                    metadata["episode"] = 1
            else:
                # 对于电影，删除可能的 season/episode 字段
                metadata.pop("season", None)
                metadata.pop("episode", None)

            return metadata
        except Exception as e:
            logger.error(f"提取元数据时发生未处理的异常: {e}")
            return {
                "show_name": getattr(file_path, "stem", "Unknown"),
                "original_filename": getattr(file_path, "name", "unknown"),
                "season": 1,
                "episode": 1,
                "error": str(e),
            }

    def _extract_keywords(self, filename: str) -> str:
        """从文件名中提取关键词，如质量、来源等"""
        # 常见的质量标记和标签
        quality_markers = [
            r"(?:\b(?:HD|FHD|UHD|4K|1080p|720p|480p|360p|240p)\b)",
            r"(?:\b(?:HDR|SDR|HDR10|Dolby\s*Vision)\b)",
            r"(?:\b(?:x264|x265|h264|h265|HEVC|AVC|MPEG4)\b)",
            r"(?:\b(?:AAC|DTS|DDP|TrueHD|Atmos)\b)",
            r"(?:\b(?:BD|BDRip|BluRay|DVD|DVDRip|WEB|WEBRip|WEB-DL)\b)",
            r"(?:\b(?:REPACK|PROPER|INTERNAL)\b)",
            r"(?:\b(?:CHS|ENG|双语|字幕|中字|英字)\b)",
            r"(?:\b(?:AC3|DTS-HD)\b)",
            r"(?:\b(?:Netflix|Disney\+|HBO|Amazon|Prime|Apple\+|iTunes)\b)",  # 流媒体平台
        ]

        extracted_keywords = []

        # 提取所有匹配的关键词
        extracted_keywords = []

        # 从原始文件名中提取关键词，保留原始顺序
        original_filename = filename

        # 定义要提取的关键词模式，使用非单词边界匹配，支持点号和下划线分隔
        # 优化顺序，先匹配长模式，避免短模式被重复匹配
        keyword_patterns = [
            r"(?:[^\w]|^)(2160p|4K|UHD|FHD|1080p|720p|480p|360p|240p|Ma10p|Ma10p_1080p)(?:[^\w]|$)",
            r"(?:[^\w]|^)(Dolby\s*Vision|HDR10|HDR|SDR)(?:[^\w]|$)",
            # 流媒体平台（完整名称和缩写）
            r"(?:[^\w]|^)(Netflix|NF|Disney\+|Disney|HBO|HBO\s*Max|Amazon|AMZN|Prime|Apple\+|Apple|iTunes)(?:[^\w]|$)",
            r"(?:[^\w]|^)(BDRip|BluRay|DVDRip|WEB-DL|WEBRip|WEB|BD|DVD)(?:[^\w]|$)",
            r"(?:[^\w]|^)(x265|x264|h265|h264|HEVC|AVC|MPEG4|x265_flac|x264_flac)(?:[^\w]|$)",
            r"(?:[^\w]|^)(DTS-HD|TrueHD|Atmos|DDP|DTS|AAC|AC3|FLAC|flac)(?:[^\w]|$)",
            r"(?:[^\w]|^)(REPACK|PROPER|INTERNAL|LIMITED|UNCUT|EXTENDED)(?:[^\w]|$)",
            r"(?:[^\w]|^)(DIRECTORS\.CUT|THEATRICAL\.CUT|UNCENSORED|UNRATED)(?:[^\w]|$)",
            r"(?:[^\w]|^)(REMUX|RECODE|HYBRID|CR|HQ)(?:[^\w]|$)",
            r"(?:[^\w]|^)(CHS|ENG|双语|字幕|中字|英字)(?:[^\w]|$)",
        ]

        # 提取所有匹配的关键词
        all_matches = []
        for pattern in keyword_patterns:
            matches = re.finditer(pattern, original_filename, re.IGNORECASE)
            for match in matches:
                all_matches.append((match.start(), match.group(1)))

        # 按在文件名中出现的顺序排序
        all_matches.sort(key=lambda x: x[0])

        # 去重，保留第一次出现的关键词
        seen = set()
        unique_keywords = []
        for _, keyword in all_matches:
            if keyword.lower() not in seen:
                seen.add(keyword.lower())
                unique_keywords.append(keyword)

        # 用点连接关键词
        return ".".join(unique_keywords)

    def _extract_with_regex(self, filename: str) -> Dict:
        """Extract metadata using regular expressions."""
        # 预处理：将全角括号替换为标准方括号，将+号替换为空格，将中文冒号替换为英文
        base_name = (
            filename.replace("【", "[")
            .replace("】", "]")
            .replace("+", " ")
            .replace("：", ":")
        )

        metadata = {
            "original_filename": filename,
            "season": None,
            "episode": None,
            "release_group": None,
        }

        # 提取文件基本信息
        name_only, ext = os.path.splitext(base_name)
        # 如果扩展名看起来不像视频扩展名（例如是从 [YTS.LT] 提取的 .lt]），则设为空
        video_extensions = [
            ".mp4",
            ".mkv",
            ".avi",
            ".mov",
            ".wmv",
            ".flv",
            ".srt",
            ".sub",
            ".idx",
            ".strm",
        ]
        if ext.lower() not in video_extensions:
            ext = ""
        metadata["extension"] = ext.lower()

        # 提取关键词
        metadata["quality_tags"] = self._extract_keywords(name_only)

        # 提取tmdbid信息
        tmdbid_pattern = r"\{tmdbid[=-](\d+)\}"
        tmdbid_match = re.search(tmdbid_pattern, name_only, re.IGNORECASE)
        if tmdbid_match:
            metadata["tmdb_id"] = tmdbid_match.group(1)

        # 提取年份信息
        year_patterns = [
            r"\((\d{4})(?:-\d{4})?\)",
            r"\.(\d{4})(?:-\d{4})?\.",
            r"\.(\d{4})(?:-\d{4})?\s",
            r"(?<!\d)(19\d{2}|20\d{2})(?!\d|[xXpP])",  # 匹配 19xx 或 20xx，且排除 1920x1080
        ]

        year_match = None
        for pattern in year_patterns:
            year_match = re.search(pattern, name_only)
            if year_match:
                metadata["year"] = year_match.group(1)
                break

        # 清理文件名，用于搜索
        cleaned_name = self._clean_filename_for_search(base_name)
        metadata["cleaned_name"] = cleaned_name

        # Common patterns
        # Special pattern for French/foreign movie formats with . and - separators
        # Like: Je.Navais.Que.Le.Neant.-.Shoah.Par.Lanzmann.2025.1080p.BluRay.x264.AAC5.1-[YTS.LT]
        patterns = [
            # -2. 空格分隔的外语电影模式：匹配 "片名 年份 分辨率 语言 技术信息 发布组" 格式
            # 如：Kokuho 2025 1080p Japanese WEB-DL HC HEVC x265 BONE.mkv
            # 如：The Last Viking 2025 1080p Danish WEB-DL HEVC x265 5.1 BONE.mkv
            # 如：Spirited Away 2001 1080p Japanese BluRay x264-REPACK.mkv
            # 特点：空格分隔，年份在片名后，包含语言标识和技术信息
            r"^(?P<show_name>[A-Za-z][A-Za-z0-9\s\']+)\s+(?P<year>\d{4})\s+(?:2160p|4K|UHD|FHD|1080p|720p|480p|360p|240p)(?:\s+(?:Japanese|Chinese|English|Korean|Spanish|French|German|Italian|Portuguese|Russian|Danish|Swedish|Norwegian|Finnish|Polish|Dutch|Czech|Hungarian|Turkish|Greek|Arabic|Hindi|Thai|Vietnamese|Indonesian|Malay|Filipino))?(?:\s+(?:WEB-DL|WEBRip|BluRay|BDRip|DVDRip|DVD|HDTV))(?:\s+(?:HC|REPACK|PROPER|INTERNAL))?(?:\s+[A-Z][A-Za-z0-9\s\-\.\.0-9]+)?$",
            # -1. 中文电影专用模式：匹配 "片名.分辨率.语言标签[网站信息].扩展名" 格式
            # 如：特工迷阵.1080p.HD中英双字[最新电影www.5266ys.com].mp4
            # 如：肖申克的救赎.720p.中英双字[电影天堂www.dytt8.net].mkv
            # 如：复仇者联盟.4K.中英双字.mp4
            # 这个模式优先级最高，专门处理中文PT/电影站资源
            # 注意：使用 name_only（不含扩展名）进行匹配，所以正则不需要匹配扩展名
            r"^(?P<show_name>[\u4e00-\u9fff\w\s]+)[.\-](?:2160p|4K|UHD|FHD|1080p|720p|480p|360p|240p)(?:[.\-](?:HD|FHD|UHD)?(?:中英双字|中字|英字|双语|国语|粤语|日语版|CHS|ENG|JAP))?(?:\[.*?\])?$",
            # 0.12 匹配中文目录格式 "剧名 第X季(年份)" - 如 "仙武传 第3季(2024)"
            r"^(?P<show_name>[\u4e00-\u9fff\w\s]+?)\s*第(?P<season_cn>[一二三四五六七八九十\d]+)季\s*\((?P<year>\d{4})\)",
            # 0.13 匹配中文目录格式 "剧名(年份)" - 如 "仙武传(2024)"
            r"^(?P<show_name>[\u4e00-\u9fff\w\s]+?)\s*\((?P<year>\d{4})\)",
            # 0.10 匹配 "数字-数字 剧名(年份)/SxxExx" 格式（如 6-2神国之上(2025)/S01E05）- 最高优先级
            r"^(?P<prefix>\d+-\d+)?(?P<show_name>[\u4e00-\u9fff\w\s\.\-]+?)\s*\((?P<year>\d{4})\)[\/\\]S(?P<season>\d+)E(?P<episode>\d+)",
            # 0.11 匹配 "数字-数字 剧名(年份)SxxExx" 格式（无分隔符）
            r"^(?P<prefix>\d+-\d+)?(?P<show_name>[\u4e00-\u9fff\w\s\.\-]+?)\s*\((?P<year>\d{4})\)\s*S(?P<season>\d+)E(?P<episode>\d+)",
            # 0.9 Special pattern for [Group][Type][ShowName][EnglishName][Year][Episode][Tags].mp4 (GM-Team style)
            # Like: [GM-Team][国漫][遮天][Shrouding the Heavens][2023][142][AVC][GB][1080P].mp4
            r"^\[[^\]]+\]\s*\[[^\]]+\]\s*\[(?P<show_name>[^\]]+)\]\[[^\]]+\]\[(?P<year>\d{4})\]\[(?P<episode>\d{1,4})\]",
            # 0.0 特殊模式：匹配纯中文标题（不含发布组、季号、集号）- 如 "为了所有的女孩.mkv"
            r"^(?P<show_name>[\u4e00-\u9fff]+)\.[a-z0-9]+$",
            # 0.0.1 匹配带年份的纯中文标题 - 如 "为了所有的女孩.2021.mkv"
            r"^(?P<show_name>[\u4e00-\u9fff]+)[.\s]*(?P<year>\d{4})\.[a-z0-9]+$",
            # 0.0.2 匹配点号分隔的简单英文标题：如 "The.Secret.Agent.mkv"
            # 只匹配纯字母，避免匹配 S01E01 格式
            r"^(?P<show_name>[A-Za-z]+(?:\.[A-Za-z]+)*)\.[a-z0-9]+$",
            # 0.0.3 带年份的简单格式：如 "Forrest.Gump.1994.mkv"
            r"^(?P<show_name>[A-Za-z]+(?:\.[A-Za-z]+)*)\.(?P<year>\d{4})\.[a-z0-9]+$",
            # 0. Special pattern for bracket-format anime: [Group][ShowName][48][GB][1080P][x264_AAC].mp4
            r"^\[[^\]]+\]\s*\[(?P<show_name>[^\]]+)\]\s*\[(?P<episode>\d{1,4}(?:-\d{1,4})?)\]",
            # 0.1 Special pattern for bracket-format anime with season: [Group][ShowName][S2][12][...]
            r"^\[[^\]]+\]\s*\[(?P<show_name>[^\]]+)\]\s*\[S(?P<season>\d+)\]\s*\[(?P<episode>\d{1,4}(?:-\d{1,4})?)\]",
            # 0.2 Special pattern for anime with episode title: [Group][Detective Conan_30th_1hSP][1187][Episode Title][...].mp4
            r"^\[[^\]]+\]\s*\[(?P<show_name>[\w\s]+?)(?:_\d+(?:th|nd|rd|st)?(?:_?\d+h(?:SP)?)?)?\]\s*\[(?P<episode>\d{1,4}(?:-\d{1,4})?)\]",
            # 0.3 Special pattern for anime with full episode info: [Group][Show_30th_1hSP][1187][Episode Title][BIG5][2160P][20260103].mp4
            r"^\[[^\]]+\]\s*\[(?P<show_name>[\w\s]+?)(?:_\d+(?:th|nd|rd|st)?(?:_?\d+h(?:SP)?)?)?\]\s*\[(?P<episode>\d{1,4}(?:-\d{1,4})?)\]\s*\[Episode\s+[^\]]+\]",
            # 0.4 Special pattern for [Group] Show Name [集号] format (no extra brackets around show name)
            r"^\[(?P<release_group>[^\]]+)\]\s*(?P<show_name>[^\[]+?)\s*\[(?P<episode>\d{1,4}(?:-\d{1,4})?)\]",
            # 0.5 Special pattern for [Group][Show][Omnibus_03(36.5)][1080p].mkv format
            r"^\[[^\]]+\]\s*\[(?P<show_name>[^\]]+)\]\s*\[Omnibus[_\s]*\d+(?:\(\d+(?:\.\d+)?\))?\]",
            # 0.5.1 Fallback for Omnibus format without episode capture
            r"^\[[^\]]+\]\s*\[(?P<show_name>[^\]]+)\]\s*\[Omnibus",
            # 0.6 Special pattern for [Group][Chinese/English Show][1080p].mp4 format
            r"^\[[^\]]+\]\s*\[(?:[^\]]+/)?(?P<show_name>[^\]]+)\]\s*\[",
            # 0.6 Special pattern for [Group] Show Name [集号][其他标签] 格式
            r"^\[(?P<release_group>[^\]]+)\]\s*(?P<show_name>[^\[]+?)\s*\[(?P<episode>\d{1,4}(?:-\d{1,4})?)\]\s*\[",
            # 0.7 Special pattern for Show.Name.EPxx.quality-Group.mkv format
            r"^(?P<show_name>[^\-]+?)\.EP(?P<episode>\d{1,4})(?:[.\s]+[^\-]+)*\-(?P<release_group>[^\.]+)$",
            # 0.8 Special pattern for Show.Name.EPxx.quality-Group.mkv format (alternative)
            r"^(?P<show_name>.+?)\.EP(?P<episode>\d{1,4}).*\-(?P<release_group>[A-Za-z]+)$",
            # 0. Special pattern for dot-and-hyphen separated movie titles with quality tags
            r"^(?P<show_name>[\w\s\.\-]+?)\s*[\(\[]?\d{4}[\)\]]?\s*(?:\.[\w\-]+)+(?:\-[\w\.\[\]]+)?$",
            # Movie-specific patterns - 电影专用匹配模式
            # 匹配带发布组、年份、技术信息和语言标签的电影格式
            r"^\[(?P<release_group>[^\]]+)\]\s*(?P<show_name>[^\(]+?)\s*\((?P<year>\d{4})\)\s*(?:\([^\)]+\))+\s*(?:(?P<language>[A-Z]+)\s*)?\[[^\]]+\]",
            # 匹配带发布组和年份的电影格式
            r"^\[(?P<release_group>[^\]]+)\]\s*(?P<show_name>[^\(]+?)\s*\((?P<year>\d{4})\)\s*(?:\([^\)]+\))+",
            # 2.5 匹配点分隔的电影格式 (731.Operation.Cherry.Blossoms.at.Night.2025.2160p.WEB-DL.H265.DTS.mkv)
            # 兼容使用 . 和 - 作为分隔符的文件名，如 Je.Navais.Que.Le.Neant.-.Shoah.Par.Lanzmann.2025.1080p.BluRay.x264.AAC5.1-[YTS.LT]
            r"^(?P<show_name>[\w\s\.\-]+?)[.\-](?P<year>\d{4})[.\-][^\-]+(?:\-[^\-]+)*$",
            # 2.6 匹配简化的点分隔电影格式 (电影名称.年份)
            r"^(?P<show_name>[\w\s\.\-]+?)[.\-](?P<year>\d{4})[.\-]",
            # 1. Show Name Season 01 Episode 01
            r"^(?P<show_name>.*?)[. ]?S(?P<season>\d+)E(?P<episode>\d+)",
            # 1.5. 匹配季节-only 格式（如 Downton.Abbey.S06.1080p.BluRay.x264...）
            r"^(?P<show_name>[A-Za-z][A-Za-z0-9\s\.]*?)[. ]S(?P<season>\d+)(?:\.|$)",
            # 2. Season patterns (English & Chinese)
            r"(?P<show_name>.*?)\s*Season\s*(?P<season>\d+)",
            r"(?P<show_name>.*?)\s*(?P<season>\d+)(?:st|nd|rd|th)\s*Season",
            r"(?P<show_name>.*?)\s*第(?P<season_cn>[一二三四五六七八九十\d]+)季",
            r"\[(?P<show_name>[^\]]+?)\s+第(?P<season_cn>[一二三四五六七八九十\d]+)季\]",
            # 2.5 匹配 "赘婿.第1季.E02" 格式（中文季号 + 点 + E集号）
            r"^(?P<show_name>.+?)第(?P<season_cn>\d+)季\.[Ee][Pp]?(?P<episode>\d+)",
            # 模式 A: 较长的或不常见的罗马数字 (II-IX, V, VI...) 允许后随空格、中横杠或中文附属标题
            r"(?P<show_name>.*?)(?<![a-zA-Z0-9])(?P<roman_season>VIII|VII|VI|III|II|IX|IV|V)(?![a-zA-Z0-9])\s*(?::|-|\s|$)",
            # 模式 B: 极其高频误触的单字母罗马数字 (X, I) 要求后随必须是行尾或元数据标记 (防止切断 Spy x Family)
            r"(?P<show_name>.*?)(?<![a-zA-Z0-9])(?P<roman_season>X|I)(?![a-zA-Z0-9])\s*(?::|-|\[|\(|\r?$)",
            # 2.5 匹配 "Show Name S2 - 01" 格式（季号在集号前面，用空格分隔）- 必须在 "Show Name - 09" 之前
            r"^(?P<show_name>(?!^\d+$)[A-Za-z][A-Za-z0-9\s\-\'\.]+?)\s+S(?P<season>\d+)\s*-\s*(?P<episode>\d{2,3})",
            # 2.6 匹配 "[Release Group] Show Name S2 - 01" 格式（带字幕组前缀的 S2 - 01 格式）
            r"^\[[^\]]+\]\s*(?P<show_name>(?!^\d+$)[A-Za-z][A-Za-z0-9\s\-\'\.]+?)\s+S(?P<season>\d+)\s*-\s*(?P<episode>\d{2,3})",
            # 2.7 匹配 "[Release Group] Show Name S3 [01]" 格式（S和集号在方括号中）
            r"^\[[^\]]+\]\s*(?P<show_name>(?!^\d+$)[A-Za-z][A-Za-z0-9\s\-\'\.]+?)\s+S(?P<season>\d+)\s+\[(?P<episode>\d{1,4}(?:-\d{1,4})?)\]",
            # 2.8 匹配 "数字-数字 剧名(年份)/SxxExx" 格式（如 6-2神国之上(2025)/S01E05）- 优先级高
            r"^(?P<prefix>\d+-\d+)?(?P<show_name>[\u4e00-\u9fff\w\s\.\-]+?)\s*\((?P<year>\d{4})\)[\/\\]S(?P<season>\d+)E(?P<episode>\d+)",
            # 2.9 匹配 "数字-数字 剧名(年份)SxxExx" 格式（无分隔符）- 优先级高
            r"^(?P<prefix>\d+-\d+)?(?P<show_name>[\u4e00-\u9fff\w\s\.\-]+?)\s*\((?P<year>\d{4})\)\s*S(?P<season>\d+)E(?P<episode>\d+)",
            # 1. Show Name Season 01 Episode 01
            r"^(?P<show_name>.*?)[. ]?S(?P<season>\d+)E(?P<episode>\d+)",
            # 匹配 Show Name - 09 (严格限制show_name不能只含数字)
            r"^(?:\[[^\]]+\])?\s*(?P<show_name>(?!^\d+$)(?:[^\-]|\-(?!\d{2,3}(?:\s|\.|\[|$)))+?)\s*-\s*(?P<episode>\d+(?:-\d+)?)\s*(?:\[|\(|$)",
            # 2.4 匹配 "Show.Name.EP03.1080p...-ReleaseGroup" 格式（如 Kurosaki.san.no...EP03.1080p.HULU.WEB-DL.AAC2.0.H.264-MagicStar）
            r"^(?P<show_name>.+?)[.\s]*[Ee][Pp](?P<episode>\d+)[.\s]*[^\s]+-(?P<release_group>[A-Za-z]+)$",
            # 匹配 Show Name EP09 / Ep09 / Show.Name.EP09 (严格限制show_name不能只含数字，支持点分隔)
            r"^(?:\[[^\]]+\])?\s*(?P<show_name>(?!^\d+$).*?)(?=[.\s]*(?:EP|Ep|第)[.\s]*\d)[.\s]*(?:EP|Ep|第)[.\s]*(?P<episode>\d+(?:-\d+)?)[.\s]*(?:集)?[.\s]*(?:\[|\(|$)",
            # 修复：匹配 "Spy x Family 2 - 05" 格式 (季号在集号前面，用空格分隔)
            r"^(?P<show_name>(?!^\d+$).+?)\s+(?P<season>\d+)\s*-\s*(?P<episode>\d{2})(?:\s|\.|\[|$)",
            # --- 常用 BT 资源/动漫格式匹配 ---
            # 匹配 [VCB-Studio] Show Name [12] 或 [denisplay] Detective Conan Movie 12 - Full Score of Fear (2008) [20th] 等格式
            r"^\[[^\]]+\]\s*(?P<show_name>.*?)\s*(?:\(\d{4}\))?\s*(?:\[[^\]\d]+\])?\s*\[(?P<episode>\d{1,4}(?:-\d{1,4})?)\]",
            # 匹配 [VCB-Studio] Show Name [OVA03] 等OVA格式
            r"^\[[^\]]+\]\s*(?P<show_name>.*?)\s*\[OVA(?P<episode>\d{1,4})\]",
            # 匹配 Show Name [OVA03] 等不带字幕组的OVA格式
            r"^(?P<show_name>(?!^\d+$).*?)\s*\[OVA(?P<episode>\d{1,4})\]",
            # 匹配 Show Name [12][...] (严格限制show_name不能只含数字)
            r"^(?P<show_name>(?!^\d+$).*?)\s*\[(?P<episode>\d{1,4}(?:-\d{1,4})?)\]",
            # 匹配 剧名 22 [GB] (空格集号，严格限制show_name不能只含数字且不含年份，且集号必须小于1000)
            # 添加年份前向否定断言，避免将年份误识别为集号
            r"^(?:\[[^\]]+\]\s+)?(?P<show_name>(?!^\d+$)[\u4e00-\u9fff\w\s]+?(?<!\d{4}))\s+(?P<episode>\d{1,3}(?:-\d{1,3})?)(?<!\d{4})(?:\s|$)",
            # 匹配 [Nekomoe kissaten][Watashi wo Tabetai, Hitodenashi][12][1080p][JPSC] 格式
            r"^\[[^\]]+\]\s*\[(?P<show_name>[^\]]+)\]\s*\[(?P<episode>\d{1,4}(?:-\d{1,4})?)\]",
            # 基础降级模式 (只抓集号，添加年份排除)
            # 匹配 [Doomdos] - 荒古恩仇录·破 风篇 - 第32话 - [1080P] 这种格式
            r"^(?:\[[^\]]+\])?\s*(?P<show_name>(?!^\d+$).*?)\s*-\s*第(?P<episode>\d+(?:-\d+)?)话\s*",
            r"(?<!\d{4})第(?P<episode>\d+(?:-\d+)?)集",
            r"(?<!\d{4})第(?P<episode>\d+(?:-\d+)?)话",
            r"(?<!\d{4})EP(?P<episode>\d+(?:-\d+)?)",
            r"(?<!\d{4})\[(?P<episode>\d{1,4}(?:-\d{1,4})?)\]",
            # 匹配 #01 或 #1 格式 (如 [AI-Raws] 魔神英雄伝ワタル2 #01)
            r"(?P<show_name>.*?)\s*#(?P<episode>\d{1,4})(?:$|\s|\.|\[|\()",
        ]

        match_found = False
        for i, pattern in enumerate(patterns):
            # 使用 name_only（不含扩展名）进行正则匹配
            match = re.search(pattern, name_only, re.IGNORECASE)
            if match:
                match_data = match.groupdict()

                # 处理中文季号转换
                if "season_cn" in match_data and match_data["season_cn"]:
                    cn_val = match_data["season_cn"]
                    digit = self._chinese_to_digit(cn_val)
                    if digit:
                        match_data["season"] = str(digit)

                # 补全元数据
                for key, value in match_data.items():
                    if value and key != "season_cn" and not metadata.get(key):
                        # 清理show_name：移除末尾点号，将点替换为空格（用于日文/英文剧名）
                        if key == "show_name":
                            value = value.rstrip(".").replace(".", " ")
                        metadata[key] = value
                match_found = True

        # 提取字幕组信息（通常在文件名开头，格式为[字幕组名称]）
        # 在所有其他正则匹配之后提取，确保不会被覆盖
        release_group_pattern = r"^\[([^\]]+)\]"
        release_group_match = re.search(release_group_pattern, base_name)
        if release_group_match:
            metadata["release_group"] = release_group_match.group(1)

        # 提取末尾的发布组格式（如 -MagicStar）
        release_group_trailing_pattern = r"\-([A-Za-z]+)\.(?:mkv|mp4|avi|flv|mov|wmv)$"
        release_group_trailing_match = re.search(
            release_group_trailing_pattern, base_name
        )
        if release_group_trailing_match and not metadata.get("release_group"):
            metadata["release_group"] = release_group_trailing_match.group(1)

        # 提取不带方括号的发布组格式（如 AHTV.Judge.of.Song.Dynasty...）
        # 匹配连续大写字母组后跟点号或空格
        release_group_no_bracket_pattern = r"^([A-Z]{2,6})[._]"
        release_group_no_bracket_match = re.search(
            release_group_no_bracket_pattern, base_name
        )
        if release_group_no_bracket_match and not metadata.get("release_group"):
            # 只在方括号格式未匹配时才使用这种格式
            potential_group = release_group_no_bracket_match.group(1)
            # 排除纯TV/MOVIE等关键词
            if potential_group.lower() not in [
                "tv",
                "movie",
                "film",
                "bluray",
                "web",
                "hd",
                "dts",
                "aac",
            ]:
                metadata["release_group"] = potential_group

        # 先移除此处的媒体类型相关代码，将在后面统一处理

        if match_found:
            # Clean up show name
            if "show_name" in metadata:
                # 1. 优先处理罗马数字转换
                if "roman_season" in metadata and metadata["roman_season"]:
                    digit = self._roman_to_digit(metadata["roman_season"])
                    if digit:
                        metadata["season"] = str(digit)
                        # 从剧名中剔除罗马数字后缀
                        metadata["show_name"] = re.sub(
                            rf"\s*{metadata['roman_season']}\s*$",
                            "",
                            metadata["show_name"],
                        ).strip()

                # 接下来执行常规清理
                show_name = metadata["show_name"]
                # 1. 移除首部的发布组方括号，如 [Dynamis One]
                show_name = re.sub(r"^\[[^\]]+\]\s*", "", show_name)
                # 2. 移除首部的无括号发布组格式（如 AHTV.Judge, AHTV Judge, VCB-Studio）
                show_name = re.sub(r"^[A-Z]{2,6}(?:[._]|\s)\s*", "", show_name)
                # 2. 移除括号内的年份 (2022) - 无论位置如何
                show_name = re.sub(r"\s*\(\d{4}(?:-\d{4})?\)\s*", " ", show_name)
                # 3. 移除方括号内的标签，如 [国漫]、[中文配音] 等
                # 先移除特定的常见标签
                common_tags = [
                    "国漫",
                    "日漫",
                    "美漫",
                    "新番",
                    "GM-Team",
                    "Team",
                    "Group",
                    "Raws",
                    "Studio",
                    "中文配音",
                    "中配",
                    "配音",
                    "繁中",
                    "简中",
                    "CHT",
                    "CHS",
                    "AHTV",
                    "CCTV",
                    "BTV",
                    "HunanTV",
                    "JSTV",
                    "ZJTV",
                ]
                for tag in common_tags:
                    show_name = re.sub(
                        r"\[\s*" + re.escape(tag) + r"\s*\]",
                        "",
                        show_name,
                        flags=re.IGNORECASE,
                    )
                # 4. 移除剩余的所有方括号内容（用于搜索时更干净）
                show_name = re.sub(r"\[[^\]]+\]", "", show_name)

                # 5. 移除常见的语言标签
                language_tags = [
                    "CHINESE",
                    "ENGLISH",
                    "JAPANESE",
                    "KOREAN",
                    "中文",
                    "英语",
                    "日语",
                    "韩语",
                    "中字",
                    "英字",
                    "双语",
                ]
                for tag in language_tags:
                    show_name = re.sub(
                        r"\s+" + re.escape(tag) + r"\s*$",
                        "",
                        show_name,
                        flags=re.IGNORECASE,
                    )
                    show_name = re.sub(
                        r"^\s*" + re.escape(tag) + r"\s+",
                        "",
                        show_name,
                        flags=re.IGNORECASE,
                    )
                    show_name = re.sub(
                        r"\s+" + re.escape(tag) + r"\s+",
                        " ",
                        show_name,
                        flags=re.IGNORECASE,
                    )

                # 6. 额外清理：如果剧名末尾残存了连集信息（如 Pocket Monsters 115），剔除它
                show_name = re.sub(r"\s+\d+(?:-\d+)?$", "", show_name)

                # 7. 移除周年纪念/特别篇标记（如 _30th_1hSP, _25th_Anniversary 等）
                show_name = re.sub(
                    r"_\d+(?:th|nd|rd|st)?(?:_?\d+h(?:SP)?)?\s*$",
                    "",
                    show_name,
                    flags=re.IGNORECASE,
                )

                metadata["show_name"] = show_name.strip()
                show_name = show_name.strip().rstrip(".")
                # 移除多余的空格（包含双空格）
                show_name = re.sub(r"\s+", " ", show_name)

                # 特别处理中文名称，不进行title()转换
                if re.search(r"[\u4e00-\u9fff]", show_name):
                    # 只替换英文点(.)，保留中文点(·)
                    show_name = re.sub(r"\.", " ", show_name).strip()
                    # 移除副标题（只移除明确的副标题关键词，保留正式剧名部分）
                    # 使用与 _clean_filename_for_search 相同的逻辑
                    if "·" in show_name:
                        subtitle_keywords = [
                            r"篇",
                            r"章",
                            r"回",
                            r"卷",
                            r"部",
                            r"季",
                            r"传",
                            r"特别篇",
                            r"番外篇",
                            r"外传",
                            r"前传",
                            r"后传",
                        ]
                        subtitle_pattern = (
                            r"·.*?(?:"
                            + "|".join(subtitle_keywords)
                            + r")(?=$|\s|\.|\-|\(|\[|，|、)"
                        )
                        show_name = re.sub(subtitle_pattern, "", show_name)
                else:
                    show_name = re.sub(r"\.", " ", show_name).title().strip()

                # 专门处理EPxx格式：如果有episode信息，直接从原始文件名提取show_name
                if metadata.get("episode"):
                    episode_str = metadata["episode"]
                    filename_parts = metadata["original_filename"].split(".")
                    new_show_name = []
                    found_ep = False

                    for part in filename_parts:
                        # 检查是否包含EPxx模式
                        if re.search(
                            r"(?i)EP" + re.escape(episode_str) + r"[a-zA-Z]*", part
                        ):
                            found_ep = True
                            break
                        new_show_name.append(part)

                    if found_ep and new_show_name:
                        # 重新组合show_name
                        show_name = ".".join(new_show_name)
                        # 移除可能的字幕组标记（如[xxx]）
                        show_name = re.sub(r"^\[[^\]]+\]\s*", "", show_name)
                        # 处理点分隔的情况
                        if "." in show_name:
                            # 对于包含中文的名称，直接替换点为空格
                            if re.search(r"[\u4e00-\u9fff]", show_name):
                                show_name = show_name.replace(".", " ").strip()
                            # 对于英文名称，替换点为空格并转为title格式
                            else:
                                show_name = show_name.replace(".", " ").title().strip()

                metadata["show_name"] = show_name.strip()

        # 如果直接从原始文件名中没有匹配到，再尝试从清理后的文件名中匹配
        if not match_found:
            for pattern in patterns:
                match = re.search(pattern, cleaned_name, re.IGNORECASE)
                if match:
                    metadata.update(match.groupdict())
                    # Clean up show name
                    if "show_name" in metadata:
                        # 移除show_name中的年份信息
                        show_name = metadata["show_name"]
                        # 移除括号内的年份 (2022) - 无论位置如何
                        show_name = re.sub(
                            r"\s*\(\d{4}(?:-\d{4})?\)\s*", " ", show_name
                        )
                        # 移除末尾的空格和点
                        show_name = show_name.strip().rstrip(".")
                        # 移除多余的空格
                        show_name = re.sub(r"\s+", " ", show_name)

                        # 特别处理中文名称，不进行title()转换
                        if re.search(r"[\u4e00-\u9fff]", show_name):
                            show_name = show_name.replace(".", " ").strip()
                        else:
                            show_name = show_name.replace(".", " ").title().strip()

                        # 移除show_name中EPxx及之后的部分（处理点分隔文件名）
                        ep_match = re.search(r"(?i)\s+EP\d+\s*", show_name)
                        if ep_match:
                            show_name = show_name[: ep_match.start()].strip()

                        metadata["show_name"] = show_name
                    break

        # 如果没有匹配到show_name但有cleaned_name，尝试提取show_name
        if not metadata.get("show_name") and cleaned_name:
            # 从清理后的名称中提取可能的剧集信息，然后获取show_name
            season_episode_pattern = r"(S\d+E\d+|第\d+季第\d+集。第\d+集)"
            match = re.search(season_episode_pattern, cleaned_name, re.IGNORECASE)
            if match:
                # 提取show_name为剧集信息前的部分
                show_name = cleaned_name[: match.start()].strip()
                if show_name:
                    metadata["show_name"] = show_name

        # LLM 兜底识别：如果正则匹配失败或匹配质量差且启用了 LLM 兜底
        # 判断是否需要 LLM 处理：1) 没有 show_name，或 2) show_name 包含网站前缀/PT站名
        show_name = metadata.get("show_name", "")
        needs_llm = False

        if not show_name:
            needs_llm = True
        else:
            # 检查 show_name 是否包含网站前缀/PT站名等低质量标识
            site_prefixes = [
                "uindex",
                "org",
                "net",
                "cc",
                "tv",
                "xyz",
                "top",
                "cn",
                "hk",
                "ptp",
                "btn",
                "hdhome",
                "hdcity",
                "chd",
                "ctrl",
                "fluca",
                "keepfrds",
                "ourbits",
                "carpathia",
                "hdpt",
                "pterclub",
                "ww",
                "www",
                "http",
                "https",
                "ftp",
            ]
            show_name_lower = show_name.lower()
            for prefix in site_prefixes:
                if (
                    show_name_lower.startswith(prefix + " ")
                    or " " + prefix in show_name_lower
                ):
                    needs_llm = True
                    logger.info(
                        f"检测到低质量 show_name '{show_name}'，触发 LLM 兜底识别"
                    )
                    break

        if needs_llm and self._llm_fallback_enabled and self.llm_translator:
            logger.info(f"尝试 LLM 兜底识别: {base_name}")

            # 使用信号量限制并发
            acquired = self._llm_semaphore.acquire(timeout=10)
            if acquired:
                try:
                    llm_result = self.llm_translator.parse_filename(base_name)
                    if llm_result:
                        logger.info(f"LLM 兜底识别成功: {llm_result}")

                        # 使用LLM返回的show_name
                        if llm_result.get("show_name"):
                            metadata["show_name"] = llm_result["show_name"]
                        if llm_result.get("season"):
                            metadata["season"] = llm_result["season"]
                        if llm_result.get("episode"):
                            metadata["episode"] = llm_result["episode"]
                        if llm_result.get("year"):
                            metadata["year"] = llm_result["year"]
                        if llm_result.get("release_group"):
                            metadata["release_group"] = llm_result["release_group"]
                        if llm_result.get("media_type"):
                            metadata["media_type"] = llm_result["media_type"]
                        if llm_result.get("original_language"):
                            metadata["original_language"] = llm_result[
                                "original_language"
                            ]
                except Exception as e:
                    logger.error(f"LLM 兜底识别失败: {e}")
                finally:
                    self._llm_semaphore.release()
            else:
                logger.warning("LLM 兜底识别超时（并发数已达上限），跳过")

        # 媒体类型检测逻辑改进：
        # 1. 优先检测明显的剧集格式
        is_tv = False

        # 检查是否有明确的SxxExx格式（即使包含PT/网盘标签）
        # SxxExx格式是最明确的剧集标识，应该优先识别
        if re.search(r"(?i)(^|[^a-zA-Z])S\d+E\d+($|[^a-zA-Z])", base_name):
            is_tv = True
        # 检查其他季集信息，包括中文季集格式和OVA/SP标识，即使包含分辨率等信息
        # 只要有明确的季集标识就应识别为TV，避免将包含分辨率的中文剧集或OVA/SP误判为电影
        elif re.search(
            r"(?i)(^|[^a-zA-Z])(第\d+季|第\d+集|EP\d+|\d+话|OVA\d+|SP\d+)", base_name
        ):
            is_tv = True
        elif metadata.get("season") and metadata.get("episode"):
            # 检查season和episode是否合理（避免将年份等数字误识别）
            try:
                season_num = int(metadata["season"])
                episode_num = int(metadata["episode"])
                # 如果season大于10或episode大于1000，可能是误识别
                if season_num > 10 or episode_num > 1000:
                    is_tv = False
                else:
                    # 进一步检查：如果集号等于年份，很可能是误识别
                    if metadata.get("year") and str(episode_num) == metadata.get(
                        "year"
                    ):
                        is_tv = False
                    else:
                        is_tv = True
            except (ValueError, TypeError):
                is_tv = False
        elif metadata.get("season") or metadata.get("episode"):
            # 只有season或只有episode的情况
            try:
                if metadata.get("season"):
                    season_num = int(metadata["season"])
                    if season_num > 10:
                        is_tv = False
                    else:
                        # 进一步检查：如果季号等于年份，很可能是误识别
                        if metadata.get("year") and str(season_num) == metadata.get(
                            "year"
                        ):
                            is_tv = False
                        else:
                            is_tv = True
                if metadata.get("episode"):
                    episode_num = int(metadata["episode"])
                    if episode_num > 1000:
                        is_tv = False
                    else:
                        # 进一步检查：如果集号等于年份，很可能是误识别
                        if metadata.get("year") and str(episode_num) == metadata.get(
                            "year"
                        ):
                            is_tv = False
                        else:
                            is_tv = True
            except (ValueError, TypeError):
                is_tv = False

        # 2. 检测电影类型
        is_movie = False
        # 优先检测PT/网盘常见的电影命名格式（包含分辨率、编码、来源等信息）
        if re.search(
            r"(?i)(2160p|4k|uhd|fhd|1080p|720p|480p|360p|240p)(?:\.|\s)(web-dl|bluray|bdrip|hdrip|dvdrip|webdl|bd|dvd)(?:\.|\s)(x264|x265|h264|h265|hevc|xvid|divx)",
            base_name,
        ):
            is_movie = True
        elif re.search(
            r"\bMovie\b|\bmovie\b|\bFilm\b|\bfilm\b", base_name, re.IGNORECASE
        ):
            is_movie = True
        elif metadata.get("year"):
            # 如果season或episode等于年份，很可能是电影
            if metadata.get("season") == metadata.get("year") or metadata.get(
                "episode"
            ) == metadata.get("year"):
                is_movie = True
            # 如果文件名中包含年份，且没有明确的剧集格式，需要进一步判断
            # 不要立即默认为电影，而是标记为不确定，让TMDB查询来决定
            elif not re.search(
                r"(?i)(^|[^a-zA-Z])S\d+E\d+($|[^a-zA-Z])|第\d+季|第\d+集|EP\d+",
                base_name,
            ):
                # 有年份但无集信息，暂时不确定类型，设置为None让后续TMDB查询决定
                is_movie = None  # 不确定
        # 3. 如果文件名看起来像电影格式（包含分辨率、编码等信息），判定为电影
        elif re.search(
            r"(?i)(2160p|4k|uhd|fhd|1080p|720p|480p|360p|240p)\s*(?:\[|\()?\d{4}(?:\]|\))?",
            base_name,
        ):
            is_movie = True

        # 3. 确定最终媒体类型
        # 优先考虑明确的剧集格式，即使同时满足电影格式也应识别为TV
        if is_tv:
            metadata["media_type"] = "tv"
        elif is_movie is True:
            metadata["media_type"] = "movie"
        elif is_movie is None:
            # 不确定类型，设置为None，让TMDB查询决定
            metadata["media_type"] = None
        else:
            # 默认情况，根据是否有季集信息判断
            if metadata.get("season") or metadata.get("episode"):
                metadata["media_type"] = "tv"
            else:
                metadata["media_type"] = "movie"

        # 根据媒体类型处理season和episode的默认值
        media_type = metadata.get("media_type")
        if media_type == "tv":
            # 对于电视剧，如果有明确的episode但没有season，默认设置season=1
            # 无论是否有显式的季号标识（Sxx或第x季），只要是TV类型且有集号，就应该有季号
            if metadata.get("episode") and not metadata.get("season"):
                metadata["season"] = "1"
        else:  # movie类型
            # 对于电影，清空season和episode
            metadata["season"] = None
            metadata["episode"] = None

        # 额外的安全检查：如果是电影，确保没有season和episode
        if metadata.get("media_type") == "movie":
            metadata["season"] = None
            metadata["episode"] = None

        # 统一清理show_name：处理点分隔的文件名
        if metadata.get("show_name") and metadata.get("episode"):
            # 直接使用original_filename处理，确保能正确提取
            filename_parts = metadata["original_filename"].split(".")
            episode_str = metadata.get("episode")
            new_parts = []
            found_ep = False

            for part in filename_parts:
                # 检查是否包含EPxx模式
                if re.search(r"(?i)EP" + re.escape(episode_str) + r"[a-zA-Z]*", part):
                    found_ep = True
                    break
                new_parts.append(part)

            if found_ep and new_parts:
                # 重新组合show_name
                show_name = ".".join(new_parts)
                # 移除可能的字幕组标记（如[xxx]）
                show_name = re.sub(r"^\[[^\]]+\]\s*", "", show_name)
                # 对于英文名称，替换点为空格并转为title格式
                if not re.search(r"[\u4e00-\u9fff]", show_name):
                    show_name = show_name.replace(".", " ").title().strip()
                else:
                    show_name = show_name.replace(".", " ").strip()
                metadata["show_name"] = show_name

        # 最终清理：确保show_name纯净，不包含年份、副标题等无关信息
        if "show_name" in metadata:
            show_name = metadata["show_name"]

            # 1. 移除括号内的年份和其他信息
            # 例如：(2022), [2023], (2021-2024) 等
            show_name = re.sub(r"\s*[\[\(]\d{4}(?:-\d{4})?[\]\)]\s*", " ", show_name)

            # 2. 移除独立的年份数字
            show_name = re.sub(r"\s+\d{4}\s*$", "", show_name)

            # 3. 处理点号分隔的情况
            # 例如：瑞草洞.Law.and.the.City.2025 -> 瑞草洞
            # 但保留类似"假面骑士.ZEZTZ"中的系列标识
            if (
                "." in show_name
                and re.search(r"[\u4e00-\u9fff]", show_name)
                and metadata.get("media_type") != "movie"
            ):
                parts = show_name.split(".")
                # 收集所有相关部分：包含中文的部分和可能的系列标识
                relevant_parts = []
                found_chinese = False
                for part in parts:
                    if re.search(r"[\u4e00-\u9fff]", part):
                        relevant_parts.append(part)
                        found_chinese = True
                    elif found_chinese and (
                        part.isupper() or re.match(r"^[A-Z0-9]{2,}$", part)
                    ):
                        # 如果已经找到了中文部分，并且下一个部分是大写字母组合（可能是系列标识），则保留
                        relevant_parts.append(part)
                    elif found_chinese:
                        # 否则停止收集
                        break
                if relevant_parts:
                    show_name = " ".join(relevant_parts)
            # 对于电影，不要截断英文名称，保留所有有意义的部分
            # 只移除明显的质量标签和年份信息
            elif "." in show_name and metadata.get("media_type") == "movie":
                # 保留所有点号分隔的部分，但移除年份和质量标签
                parts = show_name.split(".")
                filtered_parts = []
                quality_tags = [
                    "2160p",
                    "4k",
                    "uhd",
                    "fhd",
                    "1080p",
                    "720p",
                    "480p",
                    "360p",
                    "240p",
                    "web-dl",
                    "bluray",
                    "bdrip",
                    "hdrip",
                    "dvdrip",
                    "webdl",
                    "bd",
                    "dvd",
                    "x264",
                    "x265",
                    "h264",
                    "h265",
                    "hevc",
                    "xvid",
                    "divx",
                    "dts",
                    "ac3",
                    "dd5.1",
                    "aac",
                    "5.1",
                    "7.1",
                ]
                for part in parts:
                    # 跳过明显的年份和质量标签
                    if re.match(r"^\d{4}$", part) or part.lower() in quality_tags:
                        continue
                    filtered_parts.append(part)
                if filtered_parts:
                    show_name = " ".join(filtered_parts)
                else:
                    # 如果过滤后没有内容，保留原始show_name
                    show_name = metadata["show_name"]

            # 4. 处理空格分隔的副标题
            # 例如：瑞草洞 Law and the City -> 瑞草洞
            # 但保留类似"假面骑士 ZEZTZ"中的系列标识
            if " " in show_name and re.search(r"[\u4e00-\u9fff]", show_name):
                parts = show_name.split(" ")
                # 收集所有相关部分：包含中文的部分和可能的系列标识
                relevant_parts = []
                found_chinese = False
                for part in parts:
                    if re.search(r"[\u4e00-\u9fff]", part):
                        relevant_parts.append(part)
                        found_chinese = True
                    elif found_chinese and (
                        part.isupper() or re.match(r"^[A-Z0-9]{2,}$", part)
                    ):
                        # 如果已经找到了中文部分，并且下一个部分是大写字母组合（可能是系列标识），则保留
                        relevant_parts.append(part)
                    elif found_chinese:
                        # 否则停止收集
                        break
                if relevant_parts:
                    show_name = " ".join(relevant_parts)

            # 5. 移除常见的修饰词
            modifiers = [
                r"\s+特别版\s*$",
                r"\s+导演剪辑版\s*$",
                r"\s+加长版\s*$",
                r"\s+最终版\s*$",
            ]
            for modifier in modifiers:
                show_name = re.sub(modifier, "", show_name, flags=re.IGNORECASE)

            # 6. 移除多余的空格和特殊字符（保留中文点(·)）
            show_name = show_name.strip().rstrip(".")
            show_name = re.sub(r"\s+", " ", show_name)
            # 移除非字母数字和中文的字符（包括中文点(·)）
            show_name = re.sub(r"[^\w\s\u4e00-\u9fff·]", "", show_name)

            metadata["show_name"] = show_name
        # 如果没有提取到show_name，使用清理后的文件名作为默认值
        elif cleaned_name:
            # 移除明显的年份和质量标签
            default_show_name = cleaned_name
            # 移除括号内的内容
            default_show_name = re.sub(r"[\[\(].*?[\]\)]", "", default_show_name)
            # 移除年份
            default_show_name = re.sub(r"\s*\d{4}\s*", "", default_show_name)
            # 移除多余的空格和特殊字符
            default_show_name = default_show_name.strip().rstrip(".")
            default_show_name = re.sub(r"\s+", " ", default_show_name)
            default_show_name = re.sub(r"[^\w\s\u4e00-\u9fff]", "", default_show_name)
            metadata["show_name"] = default_show_name
        # 最后的备用方案：使用文件名的基本部分
        else:
            metadata["show_name"] = os.path.splitext(base_name)[0]

        # 最终清理：确保show_name没有多余空格和尾部残留
        if metadata.get("show_name"):
            show_name = metadata["show_name"]
            # 移除双空格
            show_name = re.sub(r"\s+", " ", show_name)
            # 移除尾部残留的质量标签和数字（如 px2645, 1 等）
            show_name = re.sub(r"\s+[a-z]+\d+\s*$", "", show_name, flags=re.IGNORECASE)
            show_name = re.sub(r"\s+\d+\s*$", "", show_name)
            show_name = show_name.strip()
            metadata["show_name"] = show_name

        return metadata

    def _roman_to_digit(self, roman: str) -> Optional[int]:
        """将罗马数字转换为阿拉伯数字 (I-X)"""
        roman_dict = {
            "I": 1,
            "II": 2,
            "III": 3,
            "IV": 4,
            "V": 5,
            "VI": 6,
            "VII": 7,
            "VIII": 8,
            "IX": 9,
            "X": 10,
        }
        if not roman:
            return None
        return roman_dict.get(roman.upper())

    def _chinese_to_digit(self, cn_str: str) -> Optional[int]:
        """将中文数字转换为阿拉伯数字 (1-99)"""
        cn_map = {
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
            "0": 0,
            "1": 1,
            "2": 2,
            "3": 3,
            "4": 4,
            "5": 5,
            "6": 6,
            "7": 7,
            "8": 8,
            "9": 9,
        }

        if not cn_str:
            return None

        # 如果是纯数字字符串
        if cn_str.isdigit():
            return int(cn_str)

        # 处理简单的中文数字
        if len(cn_str) == 1:
            return cn_map.get(cn_str)

        # 处理“十”开头的（如：十一、十二）
        if len(cn_str) == 2 and cn_str[0] == "十":
            return 10 + cn_map.get(cn_str[1], 0)

        # 处理“二十”、“三十”等
        if len(cn_str) == 2 and cn_str[1] == "十":
            return cn_map.get(cn_str[0], 0) * 10

        # 处理“二十一”等
        if len(cn_str) == 3 and cn_str[1] == "十":
            return cn_map.get(cn_str[0], 0) * 10 + cn_map.get(cn_str[2], 0)

        return None

    def _extract_with_ai(self, filename: str, existing_metadata: Dict) -> Dict:
        """
        Use AI service to extract metadata from filename.
        """
        logger.warning("AI extraction not implemented, using regex results only")

        return existing_metadata

    def _clean_filename_for_search(self, filename: str) -> str:
        """清理文件名，移除常见的修饰词和标记，为搜索做准备"""
        # 1. 移除后缀
        cleaned = os.path.splitext(filename)[0]

        # 2. 预处理：移除括号内的技术参数和发布组
        # 质量标记正则表达式
        quality_patterns = r"HD|FHD|UHD|4K|1080p|720p|480p|360p|240p|2160p|2160|HDR|SDR|HDR10|Dolby\s*Vision|DV|dv|Dv|x264|x265|h264|h265|HEVC|AVC|MPEG4|10bit|AAC|DTS|DDP|TrueHD|Atmos|FLAC|AC3|DTS-HD|OPUS|BD|BDRip|BluRay|DVD|DVDRip|WEB|WEBRip|WEB-DL|REPACK|PROPER|INTERNAL|CHS|ENG|双语|字幕|中字|英字|简日内嵌|繁体|简体|日语版|国语版|粤语版|MP4|MKV|AVI|GB|BIG5|CHT|CHS|TC|SC|JAP|CN|JP|Dub|JP\s*Dub|TV|Web|AAC5|5\.1|7\.1|DTS"

        # 3. 移除发布组信息（方括号或末尾格式）
        cleaned = re.sub(r"\[YTS\.?LT?\]", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\-?\[[^\]]+\]", "", cleaned)
        cleaned = re.sub(r"\-?[A-Z]{2,6}$", "", cleaned)

        # 4. 移除质量标签和年份
        cleaned = re.sub(r"[\[\(]?\d{4}[\]\)]?", "", cleaned)
        cleaned = re.sub(r"[.\-]\d{4}[.\-]", "", cleaned)
        cleaned = re.sub(r"\s+\d{4}\s*$", "", cleaned)

        # 移除质量标签（按点号或横杠分隔）
        quality_tags = [
            "1080p",
            "720p",
            "480p",
            "360p",
            "2160p",
            "4k",
            "uhd",
            "fhd",
            "bluray",
            "bdrip",
            "web-dl",
            "webrip",
            "dvdrip",
            "bd",
            "dvd",
            "web",
            "x264",
            "x265",
            "h264",
            "h265",
            "hevc",
            "xvid",
            "divx",
            "dts",
            "ac3",
            "ddp",
            "aac",
            "dts-hd",
            "truehd",
            "atmos",
            "flac",
            "repack",
            "proper",
            "internal",
            "5.1",
            "7.1",
            "GB",
            "JP",
            "CHS",
            "JPSC",
        ]
        for tag in quality_tags:
            cleaned = re.sub(
                r"[.\-]" + re.escape(tag) + r"[.\-]?", "", cleaned, flags=re.IGNORECASE
            )
            cleaned = re.sub(
                r"\s+" + re.escape(tag) + r"$", "", cleaned, flags=re.IGNORECASE
            )

        # 5. 移除所有方括号内容（包含技术参数的块、发布组、集号等）
        # 先移除方括号内容，保留剧名部分
        # 匹配 [集号] 格式 (纯数字)
        cleaned = re.sub(r"\[\d+(?:-\d+)?\]", "", cleaned)
        # 匹配 [S01] 季号格式
        cleaned = re.sub(r"\[S\d+\]", "", cleaned, flags=re.IGNORECASE)
        # 匹配 [OVAxx] 格式
        cleaned = re.sub(r"\[OVA\d+\]", "", cleaned, flags=re.IGNORECASE)
        # 匹配其他方括号内容（保留可能包含剧名的块）
        cleaned = re.sub(
            r"\[([^\]]+)\]",
            lambda m: (
                m.group(1)
                if m.group(1).replace("_", " ").replace(" ", "").isalnum()
                and len(m.group(1)) > 3
                else ""
            ),
            cleaned,
        )

        # 6. 移除常见的修饰符和季集信息 (Season 2, Episode 11 等)
        cleaned = re.sub(r"Season\s*\d+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"第\d+季", "", cleaned)
        cleaned = re.sub(r"-\s*(\d{1,3})\s*(?=[.\s]|$)", r" \1 ", cleaned)

        # 特别移除末尾的罗马数字
        cleaned = re.sub(
            r"\s+(VIII|VII|VI|III|II|IX|IV|V|X|I)$", "", cleaned, flags=re.IGNORECASE
        )

        # 移除副标题
        subtitle_keywords = [
            r"篇",
            r"章",
            r"回",
            r"卷",
            r"部",
            r"季",
            r"传",
            r"特别篇",
            r"番外篇",
            r"外传",
            r"前传",
            r"后传",
        ]
        subtitle_pattern = (
            r"·.*?(?:" + "|".join(subtitle_keywords) + r")(?=$|\s|\.|\-|\(|\[|，|、)"
        )
        cleaned = re.sub(subtitle_pattern, "", cleaned)

        # 7. 最后清理符号和多余空格
        # 移除各种特殊字符
        cleaned = re.sub(r"\[|\]|\.|\_|\&|\+|\(|\)", " ", cleaned)
        # 处理单独的连字符替换为空格
        cleaned = re.sub(r"(?<!\w)-(?!\w)", " ", cleaned)
        # 清理尾部残留的横杠和数字
        cleaned = re.sub(r"[\s\-]+\d*\s*$", "", cleaned)
        cleaned = re.sub(r"^\s*[\-]+\s*", "", cleaned)
        # 移除多余的空格
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # 8. 最终检查：移除末尾的数字
        cleaned = re.sub(r"\s+\d+$", "", cleaned)

        # 针对剧名的额外优化：如果清理后太短，做最后保护
        if not cleaned:
            cleaned = filename

        return cleaned

    def _prepare_search_term(self, search_term: str) -> str:
        """准备搜索词，为TMDB搜索优化"""
        prepared = re.sub(r"\s+", " ", search_term).strip()

        # 移除版本描述词 (日语版, 国语版 等)
        version_patterns = r"日语版|国语版|粤语版|中字|字幕|双语|内嵌"
        prepared = re.sub(version_patterns, "", prepared)

        # 将下划线替换为空格 (Jujutsu_Kaisen -> Jujutsu Kaisen)
        prepared = prepared.replace("_", " ")

        if re.search(r"[\u4e00-\u9fff]", prepared):
            prepared = re.sub(r"S\d+E\d+", "", prepared, flags=re.IGNORECASE)
            prepared = re.sub(r"S\d+", "", prepared, flags=re.IGNORECASE)
            prepared = re.sub(r"第\d+季(第\d+集)?", "", prepared, flags=re.IGNORECASE)
            prepared = re.sub(r"\d+集", "", prepared)
            prepared = prepared.strip()
        else:
            # 对于英文搜索词，只移除 SxxExx 格式，保留 Sxx 格式用于电视剧识别
            prepared = re.sub(r"S\d+E\d+", "", prepared, flags=re.IGNORECASE)
            # 保留 CamelCase 格式（如 BluRay），只对纯小写单词首字母大写
            prepared = re.sub(r"\b[a-z]", lambda m: m.group(0).upper(), prepared)
            prepared = re.sub(r"\s+", " ", prepared).strip()

        return prepared.strip()

    def _search_with_language(
        self, search_term: str, media_type_hint: str, year: Optional[str], language: Optional[str]
    ) -> List[Dict]:
        """
        基于语言的搜索辅助方法

        Args:
            search_term (str): 搜索词
            media_type_hint (str): 媒体类型提示
            year (Optional[str]): 年份
            language (Optional[str]): 搜索语言，如果为 None 则不限制语言，返回所有语言的结果

        Returns:
            List[Dict]: 搜索结果列表
        """
        results = []
        try:
            # 直接使用搜索词，不翻译
            final_search_term = search_term

            # 安全地处理年份参数，避免无效年份导致搜索失败
            year_param = None
            if year:
                try:
                    year_param = int(year)
                except (ValueError, TypeError):
                    logger.warning(
                        f"无效的年份值: '{year}'，将不使用年份过滤条件进行搜索"
                    )
                    year_param = None

            # 搜索方法选择
            if media_type_hint == "tv":
                search_method = self.tmdb_client.search_tv
            elif media_type_hint == "movie":
                search_method = self.tmdb_client.search_movie
            else:
                return results

            # 1. 第一次搜索：使用年份参数
            search_results = search_method(
                final_search_term, year_param, language=language
            )
            if isinstance(search_results, dict) and "results" in search_results:
                results = search_results["results"]

            # 2. 降级搜索：如果没有找到结果且使用了年份参数，则去掉年份重新搜索
            if not results and year_param:
                logger.info(
                    f"使用年份 {year_param} 搜索无结果，尝试去掉年份参数重新搜索"
                )
                search_results = search_method(
                    final_search_term, None, language=language
                )
                if isinstance(search_results, dict) and "results" in search_results:
                    results = search_results["results"]
                    if results:
                        logger.info(f"去掉年份后搜索到 {len(results)} 个结果")
        except Exception as e:
            logger.error(f"语言搜索失败: {e}")

        return results

    # 添加缓存机制，避免重复搜索
    _search_cache = {}

    def _enrich_with_tmdb(self, metadata: Dict) -> Dict:
        """使用TMDB API丰富元数据信息，获取更完整的视频详情"""
        # 确保metadata是字典类型
        if not isinstance(metadata, dict):
            logger.error("元数据不是字典类型，直接返回")
            return {}

        try:
            logger.info(f"开始TMDB搜索: metadata={metadata}")
            # 保存原始的quality_tags和release_group，避免被覆盖
            original_quality_tags = metadata.get("quality_tags", "")
            original_release_group = metadata.get("release_group", "")

            # 优先使用已有的 tmdb_id，如果文件名中已经包含 {tmdbid-xxx}
            existing_tmdb_id = metadata.get("tmdb_id")
            if existing_tmdb_id:
                logger.info(f"文件名中已包含TMDB ID: {existing_tmdb_id}，直接使用该ID获取元数据")
                media_type_hint = metadata.get("media_type", metadata.get("type", ""))
                
                try:
                    tmdb_id_int = int(existing_tmdb_id)
                    if media_type_hint == "tv":
                        details = self.tmdb_client.get_tv_details(tmdb_id_int, language="zh-CN")
                        if details and details.get("name"):
                            logger.info(f"成功获取TV剧集详情: {details.get('name', '')}")
                            # 构造搜索结果格式，直接跳到元数据丰富部分
                            best_match = {
                                "id": tmdb_id_int,
                                "name": details.get("name", ""),
                                "original_name": details.get("original_name", ""),
                                "first_air_date": details.get("first_air_date", ""),
                                "overview": details.get("overview", ""),
                                "poster_path": details.get("poster_path", ""),
                                "backdrop_path": details.get("backdrop_path", ""),
                                "vote_average": details.get("vote_average", 0),
                                "vote_count": details.get("vote_count", 0),
                                "popularity": details.get("popularity", 0),
                                "genre_ids": details.get("genre_ids", []),
                                "origin_country": details.get("origin_country", []),
                                "original_language": details.get("original_language", ""),
                                "media_type": "tv",
                            }
                            # 保存 genre_ids 用于判断动画类型
                            metadata["genre_ids"] = best_match.get("genre_ids", [])
                            
                            # 跳过搜索，直接进入元数据丰富部分
                            # 使用专门的API获取更详细的信息，优先使用中文
                            # 先尝试获取中文详细信息
                            if not details or not (details.get("name") or details.get("overview")):
                                details = self.tmdb_client.get_tv_details(tmdb_id_int, language="en-US")
                                if details:
                                    logger.info("中文电视剧信息不完整，使用英文信息")
                            
                            # 保存原始标题
                            original_name = metadata.get("show_name")
                            metadata["original_show_name"] = original_name
                            # 丰富元数据，优先使用中文标题
                            metadata["show_name"] = details.get("name", original_name)
                            metadata["overview"] = details.get("overview", "")
                            metadata["rating"] = details.get("vote_average", 0)
                            metadata["genres"] = [genre["name"] for genre in details.get("genres", [])]
                            metadata["original_name"] = details.get("original_name", "")
                            metadata["original_language"] = details.get("original_language", "")
                            metadata["origin_country"] = details.get("origin_country", [])
                            metadata["first_air_date"] = details.get("first_air_date", "")
                            metadata["last_air_date"] = details.get("last_air_date", "")
                            metadata["status"] = details.get("status", "")
                            metadata["number_of_seasons"] = details.get("number_of_seasons", 0)
                            metadata["number_of_episodes"] = details.get("number_of_episodes", 0)
                            metadata["tmdb_id"] = best_match["id"]
                            
                            # 提取年份
                            if details.get("first_air_date"):
                                metadata["year"] = details["first_air_date"].split("-")[0]
                            elif "first_air_date" in best_match and best_match["first_air_date"]:
                                metadata["year"] = best_match["first_air_date"].split("-")[0]
                            
                            # 保存图片路径
                            metadata["poster_path"] = details.get("poster_path", "")
                            metadata["backdrop_path"] = details.get("backdrop_path", "")
                            
                            # 获取演职人员信息
                            credits = self.tmdb_client.get_tv_credits(best_match["id"])
                            if credits:
                                metadata["cast"] = [
                                    actor["name"] for actor in credits.get("cast", [])[:10]
                                ]
                                metadata["director"] = [
                                    crew["name"]
                                    for crew in credits.get("crew", [])
                                    if crew.get("job") == "Director"
                                ]
                            
                            # 获取网络信息
                            if "networks" in details:
                                metadata["networks"] = [
                                    network["name"] for network in details["networks"]
                                ]
                            
                            # 恢复原始的quality_tags和release_group
                            metadata["quality_tags"] = original_quality_tags
                            metadata["release_group"] = original_release_group
                            
                            logger.info(f"使用TMDB ID成功丰富元数据: show_name={metadata.get('show_name')}, year={metadata.get('year')}")
                            return metadata
                    else:
                        details = self.tmdb_client.get_movie_details(tmdb_id_int, language="zh-CN")
                        if details and details.get("title"):
                            logger.info(f"成功获取电影详情: {details.get('title', '')}")
                            # 构造搜索结果格式，直接跳到元数据丰富部分
                            best_match = {
                                "id": tmdb_id_int,
                                "title": details.get("title", ""),
                                "original_title": details.get("original_title", ""),
                                "release_date": details.get("release_date", ""),
                                "overview": details.get("overview", ""),
                                "poster_path": details.get("poster_path", ""),
                                "backdrop_path": details.get("backdrop_path", ""),
                                "vote_average": details.get("vote_average", 0),
                                "vote_count": details.get("vote_count", 0),
                                "popularity": details.get("popularity", 0),
                                "genre_ids": details.get("genre_ids", []),
                                "original_language": details.get("original_language", ""),
                                "media_type": "movie",
                            }
                            # 保存 genre_ids 用于判断动画类型
                            metadata["genre_ids"] = best_match.get("genre_ids", [])
                            
                            # 跳过搜索，直接进入元数据丰富部分
                            # 先尝试获取中文详细信息
                            if not details or not (details.get("title") or details.get("overview")):
                                details = self.tmdb_client.get_movie_details(tmdb_id_int, language="en-US")
                                if details:
                                    logger.info("中文电影信息不完整，使用英文信息")
                            
                            # 保存原始标题
                            original_name = metadata.get("title")
                            metadata["original_show_name"] = original_name
                            # 丰富元数据，优先使用中文标题
                            metadata["title"] = details.get("title", original_name)
                            metadata["overview"] = details.get("overview", "")
                            metadata["rating"] = details.get("vote_average", 0)
                            metadata["genres"] = [genre["name"] for genre in details.get("genres", [])]
                            metadata["original_title"] = details.get("original_title", "")
                            metadata["original_language"] = details.get("original_language", "")
                            metadata["release_date"] = details.get("release_date", "")
                            metadata["runtime"] = details.get("runtime", 0)
                            metadata["status"] = details.get("status", "")
                            metadata["tmdb_id"] = best_match["id"]
                            
                            # 提取年份
                            if details.get("release_date"):
                                metadata["year"] = details["release_date"].split("-")[0]
                            elif "release_date" in best_match and best_match["release_date"]:
                                metadata["year"] = best_match["release_date"].split("-")[0]
                            
                            # 保存图片路径
                            metadata["poster_path"] = details.get("poster_path", "")
                            metadata["backdrop_path"] = details.get("backdrop_path", "")
                            
                            # 获取演职人员信息
                            credits = self.tmdb_client.get_movie_credits(best_match["id"])
                            if credits:
                                metadata["cast"] = [
                                    actor["name"] for actor in credits.get("cast", [])[:10]
                                ]
                                metadata["director"] = [
                                    crew["name"]
                                    for crew in credits.get("crew", [])
                                    if crew.get("job") == "Director"
                                ]
                            
                            # 恢复原始的quality_tags和release_group
                            metadata["quality_tags"] = original_quality_tags
                            metadata["release_group"] = original_release_group
                            
                            logger.info(f"使用TMDB ID成功丰富元数据: title={metadata.get('title')}, year={metadata.get('year')}")
                            return metadata
                except Exception as e:
                    logger.warning(f"使用TMDB ID {existing_tmdb_id} 获取元数据失败: {e}，将使用搜索方式")
            
            # 如果没有 tmdb_id 或获取失败，则使用搜索方式
            # 优先使用show_name搜索，否则使用title，确保搜索词存在
            search_term = metadata.get("show_name", metadata.get("title", ""))
            if not search_term:
                logger.warning("搜索词为空，无法进行TMDB搜索")
                # 确保返回的metadata包含必要字段
                metadata.setdefault("quality_tags", original_quality_tags)
                metadata.setdefault("year", "")
                metadata.setdefault("tmdb_id", "")
                return metadata

            # 准备优化后的搜索词
            prepared_search_term = self._prepare_search_term(search_term)
            logger.info(
                f"搜索TMDB: 原始搜索词='{search_term}', 优化后搜索词='{prepared_search_term}'"
            )
            logger.info(
                f"搜索TMDB: 原始搜索词长度={len(search_term)}, 优化后搜索词长度={len(prepared_search_term)}"
            )

            # 搜索匹配的视频信息
            # 首先尝试明确的类型搜索
            media_type_hint = metadata.get("media_type", metadata.get("type", ""))
            year = metadata.get("year")

            # 安全处理年份参数
            year_int = None
            if year:
                try:
                    year_int = int(year)
                    current_year = 2026  # 硬编码当前年份，避免循环导入
                    # 检查年份是否在未来（当前年份+1，因为有些文件可能包含下一年的预告）
                    if year_int > current_year + 1:
                        logger.warning(
                            f"检测到未来年份 '{year_int}'，当前年份为 {current_year}，"
                            f"该年份可能无效，将不使用年份过滤条件"
                        )
                        year_int = None
                except (ValueError, TypeError):
                    year_int = None

            # 使用处理后的年份（过滤了无效年份）
            search_year: Optional[str] = str(year_int) if year_int else None

            # 定义缓存键
            cache_key = (prepared_search_term, media_type_hint, search_year)

            # 检查缓存
            if cache_key in self._search_cache:
                logger.info(f"使用缓存的搜索结果: {cache_key}")
                results = self._search_cache[cache_key]
            else:
                # 优化的搜索策略：减少API调用次数
                # 1. 优先使用精确搜索（明确类型+语言匹配）
                # 2. 仅在必要时进行跨语言搜索
                # 3. 合并搜索结果，避免重复请求

                # 定义语言检测函数（移到类级别或作为静态方法可进一步优化）
                def is_chinese(text):
                    """检测文本是否包含中文"""
                    return bool(re.search(r"[\u4e00-\u9fff]", text))

                # 定义完全匹配检查函数
                def has_exact_match(search_results, target_term, target_year=None):
                    if not search_results:
                        return False, None
                    # 确保search_results是列表类型
                    if isinstance(search_results, dict) and "results" in search_results:
                        search_results = search_results["results"]
                    if not isinstance(search_results, list):
                        return False, None

                    # 提前翻译目标术语，避免在循环中重复翻译
                    target_term_lower = target_term.lower()

                    for result in search_results:
                        result_title = result.get(
                            "name", result.get("title", "")
                        ).lower()
                        original_name = result.get("original_name", "").lower()

                        # 1. 直接匹配（标题完全相同）
                        if (
                            result_title == target_term_lower
                            or original_name == target_term_lower
                        ):
                            # 如果没有指定目标年份，或者结果有匹配年份，则认为完全匹配
                            if not target_year:
                                return True, result
                            # 检查年份是否匹配
                            date_field = (
                                "first_air_date"
                                if result.get("media_type") == "tv"
                                else "release_date"
                            )
                            result_date = result.get(date_field, "")
                            result_year = (
                                result_date.split("-")[0] if result_date else ""
                            )
                            if result_year == str(target_year):
                                return True, result

                        # 2. 简繁基础兼容 (针对 Dragon Raja)
                        if (target_term_lower == "龍族" and result_title == "龙族") or (
                            target_term_lower == "龙族" and result_title == "龍族"
                        ):
                            return True, result

                    return False, None

                # 检测优化后搜索词的语言
                search_term_is_chinese = is_chinese(prepared_search_term)
                logger.info(
                    f"检测到优化后的搜索词 '{prepared_search_term}' 包含中文: {search_term_is_chinese}"
                )

                # 初始搜索语言选择
                primary_language = "zh-CN" if search_term_is_chinese else "en-US"
                secondary_language = "en-US" if search_term_is_chinese else "zh-CN"

                all_results = []
                unique_ids = set()
                exact_match_result = None

                # 1. 第一次搜索：精确类型+主要语言搜索
                logger.info(
                    f"第一次搜索：使用优化后的搜索词 '{prepared_search_term}' 进行{primary_language}搜索"
                )
                primary_results = []

                # 如果有明确的媒体类型，优先使用专用搜索
                if media_type_hint:
                    primary_results = self._search_with_language(
                        prepared_search_term,
                        media_type_hint,
                        search_year,
                        primary_language,
                    )
                    if primary_results:
                        logger.info(f"专用类型搜索返回 {len(primary_results)} 个结果")
                elif media_type_hint is None:
                    # 媒体类型不确定，同时搜索电影和电视剧
                    logger.info("媒体类型不确定，同时搜索电影和电视剧...")
                    tv_results = self._search_with_language(
                        prepared_search_term, "tv", search_year, primary_language
                    )
                    movie_results = self._search_with_language(
                        prepared_search_term, "movie", search_year, primary_language
                    )

                    # 合并结果，优先使用电视剧结果
                    primary_results = tv_results + movie_results
                    logger.info(
                        f"TV搜索返回 {len(tv_results)} 个结果, Movie搜索返回 {len(movie_results)} 个结果, 合并后 {len(primary_results)} 个结果"
                    )

                # 如果专用搜索没有结果，尝试通用搜索
                if not primary_results:
                    general_results = self.tmdb_client.search_video_show(
                        prepared_search_term, search_year, language=primary_language
                    )
                    if general_results:
                        primary_results = general_results
                        logger.info(f"通用搜索返回 {len(primary_results)} 个结果")

                # 检查是否有完全匹配
                if primary_results:
                    exact_match_found, exact_match_result = has_exact_match(
                        primary_results, prepared_search_term, search_year
                    )
                    if not exact_match_found:
                        exact_match_found, exact_match_result = has_exact_match(
                            primary_results, search_term, search_year
                        )

                if exact_match_result:
                    logger.info(
                        f"找到完全匹配: {exact_match_result.get('name', exact_match_result.get('title'))}"
                    )
                    results = [exact_match_result]
                else:
                    # 保存第一次搜索结果
                    for result in primary_results:
                        if result.get("id") not in unique_ids:
                            all_results.append(result)
                            unique_ids.add(result.get("id"))

                    # 2. 仅在必要时进行第二次跨语言搜索
                    # 只有当第一次搜索结果少于3个或者没有明确匹配时，才进行跨语言搜索
                    if len(all_results) < 3:
                        logger.info(
                            f"第一次搜索结果较少({len(all_results)}个)，进行跨语言搜索"
                        )

                        # 跨语言搜索：不指定语言参数，让 TMDB 返回所有语言的结果
                        secondary_results = []
                        if media_type_hint:
                            secondary_results = self._search_with_language(
                                prepared_search_term,
                                media_type_hint,
                                search_year,
                                None,  # 不限制语言，获取所有语言的结果
                            )
                        elif media_type_hint is None:
                            # 媒体类型不确定，同时搜索电影和电视剧
                            tv_results = self._search_with_language(
                                prepared_search_term,
                                "tv",
                                search_year,
                                None,  # 不限制语言
                            )
                            movie_results = self._search_with_language(
                                prepared_search_term,
                                "movie",
                                search_year,
                                None,  # 不限制语言
                            )
                            secondary_results = tv_results + movie_results

                        if not secondary_results:
                            general_secondary_results = (
                                self.tmdb_client.search_video_show(
                                    prepared_search_term,
                                    search_year,
                                    language=None,  # 不限制语言
                                )
                            )
                            if general_secondary_results:
                                secondary_results = general_secondary_results

                        # 检查跨语言搜索结果
                        if secondary_results:
                            exact_match_found, exact_match_result = has_exact_match(
                                secondary_results, prepared_search_term, search_year
                            )
                            if exact_match_result:
                                logger.info(
                                    f"在跨语言搜索中找到完全匹配: {exact_match_result.get('name', exact_match_result.get('title'))}"
                                )
                                results = [exact_match_result]
                            else:
                                # 合并跨语言搜索结果
                                for result in secondary_results:
                                    if result.get("id") not in unique_ids:
                                        all_results.append(result)
                                        unique_ids.add(result.get("id"))
                                results = all_results
                        else:
                            results = all_results
                    else:
                        logger.info(
                            f"第一次搜索结果充足({len(all_results)}个)，跳过跨语言搜索"
                        )
                        results = all_results

                # 保存到缓存
                if results:
                    self._search_cache[cache_key] = results

            # 确保results是列表类型
            if not isinstance(results, list):
                results = []

            if not results:
                logger.warning(f"没有找到匹配 '{search_term}' 的结果")

                # 备选策略：尝试使用 cleaned_name 搜索
                cleaned_name = metadata.get("cleaned_name", "")
                if cleaned_name and cleaned_name != search_term:
                    logger.info(
                        f"尝试使用 cleaned_name '{cleaned_name}' 作为备选搜索词"
                    )
                    alt_results = self._search_with_language(
                        cleaned_name, media_type_hint, search_year, primary_language
                    ) or self._search_with_language(
                        cleaned_name, media_type_hint, search_year, secondary_language
                    )

                    if alt_results:
                        # 检查备选搜索是否有完全匹配
                        alt_prepared = self._prepare_search_term(cleaned_name)
                        alt_prepared_is_chinese = bool(
                            re.search(r"[\u4e00-\u9fff]", alt_prepared)
                        )
                        alt_primary = "zh-CN" if alt_prepared_is_chinese else "en-US"

                        alt_exact_found, alt_exact = has_exact_match(
                            alt_results, alt_prepared, search_year
                        )
                        if alt_exact_found:
                            logger.info(
                                f"备选搜索找到完全匹配: {alt_exact.get('name', alt_exact.get('title'))}"
                            )
                            results = [alt_exact]
                        elif alt_results:
                            results = alt_results[:5]  # 取前5个结果
                            logger.info(f"备选搜索返回 {len(results)} 个结果")

                if not results:
                    # 确保返回的metadata包含必要字段
                    metadata.setdefault("quality_tags", original_quality_tags)
                    metadata.setdefault("year", "")
                    metadata.setdefault("tmdb_id", "")
                    return metadata

            # 寻找最匹配的结果
            best_match = None

            # 1. 优先匹配年份和媒体类型
            for result in results:
                # 尝试匹配年份
                date_field = (
                    "first_air_date"
                    if result.get("media_type") == "tv"
                    else "release_date"
                )
                if date_field in result and result[date_field]:
                    result_year = result[date_field].split("-")[0]
                    if result_year == metadata.get("year"):
                        best_match = result
                        logger.info(
                            f"找到年份匹配的结果: {result.get('name', result.get('title'))} ({result_year})"
                        )
                        break

            # 2. 无论是否有媒体类型提示，都使用标题相似度和流行度排序选择最佳结果
            if not best_match:
                # 优先考虑媒体类型匹配的结果
                if media_type_hint:
                    # 筛选出匹配媒体类型的结果
                    type_matched_results = [
                        result
                        for result in results
                        if result.get("media_type") == media_type_hint
                    ]
                    if type_matched_results:
                        target_results = type_matched_results
                    else:
                        # 如果没有匹配媒体类型的结果，使用所有结果
                        target_results = results
                else:
                    # 没有媒体类型提示，使用所有结果
                    target_results = results

                # 计算标题相似度并按相似度和流行度排序
                search_term_lower = search_term.lower()

                def calculate_score(result):
                    title = result.get("name", result.get("title", "")).lower()
                    original_name = result.get("original_name", "").lower()

                    # 标准化搜索词和标题，移除所有非字母数字和中文的字符（包括中文点(·)）
                    normalized_search = re.sub(
                        r"[^\w\s\u4e00-\u9fff]", "", search_term_lower
                    )
                    normalized_search = re.sub(r"\s+", "", normalized_search)

                    normalized_title = re.sub(r"[^\w\s\u4e00-\u9fff]", "", title)
                    normalized_title = re.sub(r"\s+", "", normalized_title)

                    normalized_original = re.sub(
                        r"[^\w\s\u4e00-\u9fff]", "", original_name
                    )
                    normalized_original = re.sub(r"\s+", "", normalized_original)

                    # 定义通用数字字符集（用于模糊匹配）
                    # 包括：阿拉伯数字(0-9)、中文数字(一二三四五六七八九十)、罗马数字(Ⅰ-Ⅹ, ⅰ-ⅹ)
                    digit_pattern = (
                        "[0-9一二三四五六七八九十ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅰⅱⅲⅳⅵⅶⅷⅸⅹⅺⅻⅼⅽⅾⅿ]+"
                    )
                    # 进一步标准化：移除所有数字（用于模糊匹配）
                    fuzzy_search = re.sub(digit_pattern, "", normalized_search)
                    fuzzy_title = re.sub(digit_pattern, "", normalized_title)
                    fuzzy_original = re.sub(digit_pattern, "", normalized_original)

                    score = 0
                    # 1. 模糊匹配：移除所有数字后，搜索词和标题完全匹配
                    if fuzzy_search == fuzzy_title or fuzzy_search == fuzzy_original:
                        score = 12000
                    # 2. 搜索词是标题的前缀（标题更长，更精确）
                    elif (
                        normalized_title.startswith(normalized_search)
                        and len(normalized_title) > len(normalized_search)
                    ) or (
                        normalized_original.startswith(normalized_search)
                        and len(normalized_original) > len(normalized_search)
                    ):
                        score = 15000
                    # 3. 完全匹配得分极高（在标准化后的字符串上）
                    elif (
                        normalized_search == normalized_title
                        or normalized_search == normalized_original
                    ):
                        score = 10000
                    # 4. 搜索词是标题的显著子集（在标准化后的字符串上）
                    elif (
                        normalized_search in normalized_title
                        and len(normalized_search) > 1
                    ):
                        score = 1000
                    # 5. 标题是搜索词的子集（在标准化后的字符串上）
                    elif (
                        normalized_title in normalized_search
                        and len(normalized_title) > 1
                    ):
                        score = 500

                    total_score = score + result.get("popularity", 0)
                    return total_score

                # 按得分排序
                sorted_results = sorted(
                    target_results, key=calculate_score, reverse=True
                )
                best_match = sorted_results[0]
                logger.info(
                    f"找到最匹配的结果: {best_match.get('name', best_match.get('title'))}"
                )
                # 保存 genre_ids 用于判断动画类型（搜索结果中有，详情API中文版可能丢失动画标签）
                metadata["genre_ids"] = best_match.get("genre_ids", [])

            # 3. 确保结果有效
            if not best_match:
                logger.warning(f"没有找到有效的匹配结果")
                # 确保返回的metadata包含必要字段
                metadata.setdefault("quality_tags", original_quality_tags)
                metadata.setdefault("year", "")
                metadata.setdefault("tmdb_id", "")
                return metadata

            # 获取详细信息
            media_type = best_match.get("media_type", "tv")

            # 定义获取中文详细信息的辅助函数
            def is_chinese(text):
                """检测文本是否包含中文"""
                return bool(re.search(r"[\u4e00-\u9fff]", text))

            # 使用专门的API获取更详细的信息，优先使用中文
            if media_type == "tv":
                # 先尝试获取中文详细信息
                details = self.tmdb_client.get_tv_details(
                    best_match["id"], language="zh-CN"
                )
                # 如果中文信息不完整，尝试获取英文信息
                if not details or not (details.get("name") or details.get("overview")):
                    details = self.tmdb_client.get_tv_details(
                        best_match["id"], language="en-US"
                    )
                    if details:
                        logger.info("中文电视剧信息不完整，使用英文信息")
                if not details:
                    logger.warning(f"无法获取TV详情(ID: {best_match['id']})")
                    # 确保返回原始metadata，而不是False
                    return metadata
                # 保存原始标题
                original_name = metadata.get("show_name")
                metadata["original_show_name"] = original_name
                # 丰富元数据，优先使用中文标题
                # 无论标题是否为中文，都设置完整的元数据
                if details.get("name") and is_chinese(details["name"]):
                    metadata["show_name"] = details["name"]
                    logger.info(f"使用中文标题: {details['name']}")
                else:
                    metadata["show_name"] = (
                        original_name  # 优先使用原始标题，不覆盖为英文
                    )

                # 无论标题是否为中文，都设置完整的元数据
                metadata["overview"] = details.get("overview", "")
                metadata["rating"] = details.get("vote_average", 0)
                metadata["genres"] = [
                    genre["name"] for genre in details.get("genres", [])
                ]
                metadata["original_name"] = details.get("original_name", "")
                metadata["original_language"] = details.get("original_language", "")
                metadata["origin_country"] = details.get("origin_country", [])
                metadata["first_air_date"] = details.get("first_air_date", "")
                metadata["last_air_date"] = details.get("last_air_date", "")
                metadata["status"] = details.get("status", "")
                metadata["number_of_seasons"] = details.get("number_of_seasons", 0)
                metadata["number_of_episodes"] = details.get("number_of_episodes", 0)
                metadata["tmdb_id"] = best_match["id"]

                # 打印调试信息
                logger.info(
                    f"TMDB元数据: language={metadata.get('original_language')}, country={metadata.get('origin_country')}, genres={metadata.get('genres')}"
                )

                # 提取年份 - 确保年份被正确设置
                if details.get("first_air_date"):
                    metadata["year"] = details["first_air_date"].split("-")[0]
                    logger.debug(f"从TMDB获取到年份: {metadata['year']}")
                else:
                    # 如果没有first_air_date，尝试从搜索结果中获取
                    if "first_air_date" in best_match and best_match["first_air_date"]:
                        metadata["year"] = best_match["first_air_date"].split("-")[0]
                        logger.debug(f"从搜索结果获取到年份: {metadata['year']}")
                    else:
                        # 确保year字段存在，避免后续处理出错
                        if "year" not in metadata:
                            metadata["year"] = ""
                        logger.debug(
                            f"没有找到年份信息，使用现有year: {metadata['year']}"
                        )

                # 获取网络信息
                if "networks" in details:
                    metadata["networks"] = [
                        network["name"] for network in details["networks"]
                    ]

                # 保存图片路径
                metadata["poster_path"] = details.get("poster_path", "")
                metadata["backdrop_path"] = details.get("backdrop_path", "")

                # 获取演职人员信息
                credits = self.tmdb_client.get_tv_credits(best_match["id"])
                if credits:
                    # 只取前10位演员
                    metadata["cast"] = [
                        {
                            "name": actor["name"],
                            "character": actor.get("character", ""),
                            "profile_path": actor.get("profile_path", ""),
                        }
                        for actor in credits.get("cast", [])[:10]
                    ]
                    # 只取导演和编剧
                    metadata["crew"] = [
                        {"name": crew["name"], "job": crew.get("job", "")}
                        for crew in credits.get("crew", [])
                        if crew.get("job") in ["Director", "Writer", "Creator"]
                    ][
                        :5
                    ]  # 限制数量

                # 如果有剧集信息，尝试找到对应的剧集
                if "season" in metadata and "episode" in metadata:
                    # 处理连集 (如 115-120)，提取第一个集号用于搜索
                    search_episode = (
                        str(metadata["episode"]).split("-")[0]
                        if "-" in str(metadata["episode"])
                        else metadata["episode"]
                    )

                    try:
                        # 获取剧集详细信息，优先使用中文
                        episode_details = self.tmdb_client.get_tv_episode_details(
                            best_match["id"],
                            metadata["season"],
                            search_episode,
                            language="zh-CN",
                        )
                        # 如果中文剧集信息不完整，尝试获取英文信息
                        if not episode_details or not episode_details.get("name"):
                            episode_details = self.tmdb_client.get_tv_episode_details(
                                best_match["id"],
                                metadata["season"],
                                metadata["episode"],
                                language="en-US",
                            )
                            logger.info("中文剧集信息不完整，使用英文信息")

                            if episode_details:
                                # 设置剧集名称
                                metadata["episode_name"] = episode_details.get(
                                    "name", ""
                                )
                                metadata["episode_overview"] = episode_details.get(
                                    "overview", ""
                                )
                                metadata["air_date"] = episode_details.get(
                                    "air_date", ""
                                )
                                metadata["episode_rating"] = episode_details.get(
                                    "vote_average", 0
                                )
                                # 保存剧集缩略图路径
                                metadata["still_path"] = episode_details.get(
                                    "still_path", ""
                                )
                    except Exception as e:
                        logger.warning(f"获取剧集详情失败: {e}")
            else:
                # 获取电影详细信息，优先使用中文
                details = self.tmdb_client.get_movie_details(
                    best_match["id"], language="zh-CN"
                )
                # 如果中文信息不完整，尝试获取英文信息
                if not details or not (details.get("title") or details.get("overview")):
                    details = self.tmdb_client.get_movie_details(
                        best_match["id"], language="en-US"
                    )
                    if details:
                        logger.info("中文电影信息不完整，使用英文信息")
                if not details:
                    logger.warning(f"无法获取电影详情(ID: {best_match['id']})")
                    # 确保返回原始metadata，而不是False
                    return metadata
                # 保存原始标题，并处理None值情况
                original_title = metadata.get("title")
                # 丰富元数据，优先使用中文标题
                # 无论是否是中文标题，都设置所有元数据字段
                if details.get("title") and is_chinese(details["title"]):
                    metadata["title"] = details["title"]
                    logger.info(f"使用中文标题: {details['title']}")
                else:
                    # 如果原始标题为None或空字符串，使用TMDB的原始标题
                    metadata["title"] = original_title or details.get(
                        "original_title", ""
                    )
                    logger.info(f"使用原始标题: {metadata['title']}")

                # 始终设置其他元数据字段
                metadata["overview"] = details.get("overview", "")
                metadata["rating"] = details.get("vote_average", 0)
                metadata["genres"] = [
                    genre["name"] for genre in details.get("genres", [])
                ]
                metadata["original_title"] = details.get("original_title", "")
                metadata["original_language"] = details.get("original_language", "")
                metadata["origin_country"] = details.get("origin_country", [])
                metadata["release_date"] = details.get("release_date", "")
                # 提取电影年份
                if metadata["release_date"]:
                    metadata["year"] = metadata["release_date"].split("-")[0]
                    logger.debug(f"从TMDB获取到电影年份: {metadata['year']}")
                metadata["runtime"] = details.get("runtime", 0)
                metadata["status"] = details.get("status", "")
                metadata["budget"] = details.get("budget", 0)
                metadata["revenue"] = details.get("revenue", 0)

                # 获取外部ID信息
                external_ids = self.tmdb_client.get_external_ids(
                    best_match["id"], "movie"
                )
                if external_ids:
                    metadata["imdb_id"] = external_ids.get("imdb_id", "")
                    metadata["tmdb_id"] = external_ids.get("id", "")
                    logger.info(
                        f"获取到外部ID: IMDB={metadata['imdb_id']}, TMDB={metadata['tmdb_id']}"
                    )

                # 获取评论（如果可用）
                if "reviews" in details and details["reviews"].get("results"):
                    metadata["reviews"] = [
                        {"author": review["author"], "content": review["content"]}
                        for review in details["reviews"]["results"][:3]  # 只取前3条评论
                    ]

                # 保存图片路径
                metadata["poster_path"] = details.get("poster_path", "")
                metadata["backdrop_path"] = details.get("backdrop_path", "")

            # 设置媒体类型
            metadata["media_type"] = media_type
            # 恢复原始的quality_tags和release_group
            metadata["quality_tags"] = original_quality_tags
            metadata["release_group"] = original_release_group
            return metadata
        except Exception as e:
            logger.error(f"TMDB enrichment failed: {e}")
            # 确保quality_tags和release_group存在
            metadata["quality_tags"] = original_quality_tags
            metadata["release_group"] = original_release_group
            # 确保year和tmdb_id字段存在，避免后续处理出错
            if "year" not in metadata:
                metadata["year"] = ""
            if "tmdb_id" not in metadata:
                metadata["tmdb_id"] = ""
            # 尝试从搜索结果中保存 genre_ids（即使API调用失败也可能有搜索结果）
            if "genre_ids" not in metadata and best_match:
                metadata["genre_ids"] = best_match.get("genre_ids", [])
            return metadata

    def _determine_category(self, metadata: Dict) -> str:
        """
        根据元数据确定视频的分类目录

        Args:
            metadata (Dict): 包含视频元数据的字典

        Returns:
            str: 分类目录路径
        """
        # 获取字幕组信息（仅在 TMDB 没有明确分类时使用）
        release_group = metadata.get("release_group", "")
        forced_content_type = None
        if release_group:
            # 精确匹配
            if release_group in self._release_group_mapping:
                forced_content_type = self._release_group_mapping[release_group]
                logger.debug(
                    f"字幕组 '{release_group}' 映射到类型: {forced_content_type}（后备）"
                )
            else:
                # 模糊匹配（检查字幕组名称是否包含映射关键词）
                for group_name, content_type in self._release_group_mapping.items():
                    if group_name in release_group or release_group in group_name:
                        forced_content_type = content_type
                        logger.debug(
                            f"字幕组 '{release_group}' 模糊匹配到 '{group_name}'，映射到类型: {content_type}（后备）"
                        )
                        break

        # 获取语言和地区信息
        original_language = metadata.get("original_language", "").lower()
        origin_countries = metadata.get("origin_country", [])
        genres = metadata.get("genres", [])
        genre_names = [genre.lower() for genre in genres]

        # 扩展的国家/地区识别列表
        chinese_countries = ["CN", "HK", "TW"]
        english_countries = ["US", "GB", "CA", "AU", "NZ"]
        asian_countries = ["JP", "KR", "TH", "IN"]

        # 子分类逻辑
        sub_category = ""
        base_category = "Other"  # 默认值

        # 1. 优先使用 TMDB 分类
        media_type = metadata.get("media_type")
        if media_type == "movie":
            base_category = "Movies"
            # 电影子分类
            if any(
                genre in genre_names for genre in ["animation", "animated", "动画"]
            ):
                sub_category = "动画电影"
            else:
                original_title = metadata.get("original_title", "")
                if original_title and re.search(r"[\u4e00-\u9fff]", original_title):
                    sub_category = "华语电影"
                elif original_language in ["zh", "cn"] or any(
                    country in chinese_countries for country in origin_countries
                ):
                    sub_category = "华语电影"
                else:
                    sub_category = "外语电影"
        elif media_type == "tv":
            base_category = "TV Shows"
            # 电视剧子分类
            if any(genre in genre_names for genre in ["documentary", "纪录片"]):
                sub_category = "纪录片"
            elif any(
                genre in genre_names
                for genre in ["reality", "variety", "综艺", "game show"]
            ):
                sub_category = "综艺"
            elif any(
                genre in genre_names for genre in ["animation", "animated", "动画"]
            ):
                if original_language in ["ja", "ja-jp"] or any(
                    country in ["JP", "日本"] for country in origin_countries
                ):
                    sub_category = "日番"
                elif original_language in [
                    "zh",
                    "cn",
                    "zh-cn",
                    "zh-tw",
                    "zh-hk",
                ] or any(
                    country in chinese_countries for country in origin_countries
                ):
                    sub_category = "国漫"
                elif original_language in ["en", "en-us", "en-gb"] or any(
                    country in english_countries for country in origin_countries
                ):
                    sub_category = "欧美动漫"                    
                else:
                    title = metadata.get("show_name", "") or metadata.get(
                        "original_show_name", ""
                    )
                    if re.search(r"[\u3040-\u30FF]", title):
                        sub_category = "日番"
                    elif re.search(r"[\u4E00-\u9FFF]", title):
                        sub_category = "国漫"
                    else:
                        sub_category = "其他动漫"
            elif any(
                genre in genre_names
                for genre in ["kids", "children", "child", "儿童", "family"]
            ):
                sub_category = "儿童"
            else:
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
                    original_show_name = metadata.get("original_show_name", "")
                    if original_show_name and re.search(
                        r"[\u4e00-\u9fff]", original_show_name
                    ):
                        sub_category = "国产剧"
                    else:
                        sub_category = "未分类"
        else:
            base_category = "Other"

        # 2. 如果 TMDB 没有明确的分类（sub_category 为空或为"未分类"），则使用字幕组映射作为后备
        if not sub_category or sub_category == "未分类":
            if forced_content_type:
                logger.info(
                    f"TMDB没有明确分类，使用字幕组映射: {forced_content_type}"
                )
                if forced_content_type == "anime":
                    base_category = "TV Shows"
                    # 根据语言和地区判断动漫子分类
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
                        title = metadata.get("show_name", "") or metadata.get(
                            "original_show_name", ""
                        )
                        if re.search(r"[\u3040-\u30FF]", title):
                            sub_category = "日番"
                        elif re.search(r"[\u4E00-\u9FFF]", title):
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
                        sub_category = "其他剧"
                elif forced_content_type == "movie":
                    base_category = "Movies"
                    if any(genre in genre_names for genre in ["animation", "animated", "动画"]):
                        sub_category = "动画电影"
                    else:
                        sub_category = "外语电影"

        # 组合分类路径
        return f"{base_category}/{sub_category}"

    def generate_new_path(
        self,
        metadata: Dict,
        rule_type: Optional[str] = None,
        original_path: Optional[Union[str, Path]] = None,
        output_dir: Optional[Path] = None,
    ) -> Path:
        """
        根据元数据和指定的命名规则生成新的组织路径。

        Args:
            metadata (Dict): 包含视频元数据的字典
            rule_type (str, optional): 命名规则类型 (tv_show, movie, anime, simple)
            original_path (Path, optional): 原始文件路径，用于保留文件扩展名
            output_dir (Path, optional): 输出目录，用于检测文件冲突

        Returns:
            Path: 生成的新路径
        """
        # 转换original_path为Path对象，如果它是字符串的话
        if original_path and isinstance(original_path, str):
            original_path = Path(original_path)

        # 确定媒体类型和适当的命名规则
        media_type = metadata.get("media_type")
        if rule_type is None:
            if media_type == "movie":
                rule_type = "movie"
            elif media_type == "tv" or (
                metadata.get("season") and metadata.get("episode")
            ):
                rule_type = "tv_show"
            else:
                rule_type = "simple"

        # 获取对应的命名模板
        template = self.naming_rules.get(rule_type, self.naming_rules["simple"])

        # 准备用于格式化的变量字典，优先使用原始标题
        def safe_int(val, default=1):
            if not val:
                return default
            if isinstance(val, int):
                return val
            if str(val).isdigit():
                return int(val)
            return val  # 保持为字符串 (如 115-120)

        # 检查是否是OVA/特别篇，如果是则设置为Season 0
        is_special = False
        if original_path and original_path.name:
            # 检查文件名是否包含特别篇标识（使用正则表达式精确匹配，避免部分匹配）
            special_patterns = [
                r"\bOVA\b",  # 匹配独立的OVA
                r"\bOVA0?1\b",
                r"\bOVA0?2\b",
                r"\bOVA0?3\b",
                r"\bOVA0?4\b",
                r"\bOVA0?5\b",
                r"\bOVA0?6\b",
                r"\bOVA0?7\b",
                r"\bOVA0?8\b",
                r"\bOVA0?9\b",
                r"\bOVA10\b",
                r"(?<!\w)SP(?!\w)",  # 匹配独立的SP，排除SPY等词
                r"(?<=\[)Special(?=\])",  # [Special] 格式
                r"\bSpecial\s*(?:Episode|EP|Ep)\b",  # Special Episode 格式
                r"\bSpecial\s*\d+\b",  # Special 01 格式
                r"\bSpecial\b(?=\s*\.\w+$)",  # Special.mkv 格式（在文件名末尾）
                r"特别篇",  # 中文关键词
                r"番外篇",  # 中文关键词
            ]
            filename_upper = original_path.name.upper()
            for pattern in special_patterns:
                if re.search(pattern, filename_upper, re.IGNORECASE):
                    is_special = True
                    break

        # 如果是特别篇，设置季数为0，否则使用正常的安全转换
        if is_special:
            season = 0
        else:
            season = safe_int(metadata.get("season", 1))

        episode = safe_int(metadata.get("episode", 1))

        # 补零辅助
        s_str = f"{season:02d}" if isinstance(season, int) else str(season)
        e_str = f"{episode:02d}" if isinstance(episode, int) else str(episode)

        # 处理各种条件后缀
        year = metadata.get("year", "")
        tmdb_id = metadata.get("tmdb_id", "")

        # 确保年份被正确添加，即使year为空也不影响其他逻辑
        year_suffix = f" ({year})" if year and year != "" else ""
        year_bracket_suffix = f" [{year}]" if year and year != "" else ""
        year_dot_suffix = f".{year}" if year and year != "" else ""

        tmdbid_suffix = f" {{tmdbid={tmdb_id}}}" if tmdb_id else ""
        tmdbid_bracket_suffix = f" [{tmdb_id}]" if tmdb_id else ""
        tmdbid_dot_suffix = f".{tmdb_id}" if tmdb_id else ""
        tmdbid_raw = tmdb_id if tmdb_id else ""

        en_title_suffix = (
            f".{metadata.get('en_title')}" if metadata.get("en_title") else ""
        )
        web_source = (
            f".{metadata.get('web_source')}" if metadata.get("web_source") else ""
        )
        edition = f".{metadata.get('edition')}" if metadata.get("edition") else ""
        part = f".{metadata.get('part')}" if metadata.get("part") else ""
        video_format = (
            f"{metadata.get('video_format')}" if metadata.get("video_format") else ""
        )
        video_codec = (
            f".{metadata.get('video_codec')}" if metadata.get("video_codec") else ""
        )
        audio_codec = (
            f".{metadata.get('audio_codec')}" if metadata.get("audio_codec") else ""
        )
        customization = (
            f".{metadata.get('customization')}" if metadata.get("customization") else ""
        )
        customization_suffix = (
            f"-{metadata.get('customization')}" if metadata.get("customization") else ""
        )
        release_group = (
            f"-{metadata.get('release_group')}" if metadata.get("release_group") else ""
        )
        release_group_suffix = (
            f"-{metadata.get('release_group')}" if metadata.get("release_group") else ""
        )

        # 电视剧季集格式
        season_episode = f"S{s_str}E{e_str}"

        format_vars = {
            "title": self._sanitize_filename(
                metadata.get("title")
                or metadata.get("original_title")
                or metadata.get("show_name", "Unknown Title")
            ),
            "year": metadata.get("year", ""),
            "year_suffix": year_suffix,
            "year_bracket_suffix": year_bracket_suffix,
            "year_dot_suffix": year_dot_suffix,
            "tmdbid_suffix": tmdbid_suffix,
            "tmdbid_bracket_suffix": tmdbid_bracket_suffix,
            "tmdbid_dot_suffix": tmdbid_dot_suffix,
            "tmdb_id": tmdb_id,  # 直接提供tmdb_id变量
            "tmdbid_raw": tmdbid_raw,  # 直接提供原始tmdb_id
            "en_title_suffix": en_title_suffix,
            "web_source": web_source,
            "edition": edition,
            "part": part,
            "video_format": video_format,
            "video_codec": video_codec,
            "audio_codec": audio_codec,
            "customization": customization,
            "customization_suffix": customization_suffix,
            "release_group": release_group,
            "release_group_suffix": release_group_suffix,
            "season_episode": season_episode,
            "show_name": self._sanitize_filename(
                metadata.get(
                    "show_name", metadata.get("original_show_name", "Unknown Show")
                )
            ),
            "season": season,
            "episode": episode,
            "episode_name": self._sanitize_filename(metadata.get("episode_name", "")),
            "movie_name": self._sanitize_filename(
                metadata.get("title")
                or metadata.get("original_title")
                or metadata.get("show_name", "Unknown Movie")
            ),
            "anime_name": self._sanitize_filename(
                metadata.get(
                    "show_name", metadata.get("original_show_name", "Unknown Anime")
                )
            ),
            "season_name": f"Season {s_str}",
            "quality_tags": metadata.get("quality_tags", ""),
            "quality_tags_suffix": (
                f" {metadata.get('quality_tags', '')}"
                if metadata.get("quality_tags", "")
                else ""
            ),
        }

        # 添加调试日志，追踪变量值和模板渲染

        try:
            # 提取后缀名：优先使用 original_path，其次使用 metadata 中的 extension 备份
            file_ext = ""
            if original_path and original_path.suffix:
                file_ext = original_path.suffix
            elif metadata.get("extension"):
                # 正则表达式阶段提取的后缀
                file_ext = metadata.get("extension")
                if file_ext and not file_ext.startswith("."):
                    file_ext = "." + file_ext

            # 检查模板是否使用了Jinja2语法
            if "{{" in template and "}}" in template:
                # 使用Jinja2模板引擎处理
                jinja_template = Template(template)

                # 准备Jinja2模板需要的变量
                jinja_vars = {
                    "title": (
                        format_vars["show_name"]
                        if format_vars.get("show_name")
                        else format_vars.get("movie_name", "Unknown Title")
                    ),
                    "year": year,
                    "tmdbid": tmdb_id,
                    "season": season,
                    "episode": episode,
                    "season_episode": format_vars["season_episode"],
                    "videoFormat": format_vars.get("video_format", ""),
                    "webSource": metadata.get("web_source", ""),
                    "edition": metadata.get("edition", ""),
                    "videoCodec": metadata.get("video_codec", ""),
                    "audioCodec": metadata.get("audio_codec", ""),
                    "customization": metadata.get("customization", ""),
                    "releaseGroup": metadata.get("release_group", ""),
                    "fileExt": file_ext,  # 注入后缀变量
                    "quality_tags": format_vars["quality_tags"],
                    "quality_tags_suffix": format_vars["quality_tags_suffix"],
                    "show_name": format_vars["show_name"],
                    "movie_name": format_vars["movie_name"],
                    "episode_name": format_vars["episode_name"],
                }

                # 渲染Jinja2模板
                path_str = jinja_template.render(**jinja_vars)
            else:
                # 使用原始的Python format字符串处理
                # 预处理模板，处理自定义的 {tmdbid=tmdbid} 格式
                processed_template = template

                # 预处理年份格式，当year为空时移除年份部分
                if not year:
                    processed_template = processed_template.replace(" ({year})", "")
                    processed_template = processed_template.replace("({year})", "")

                # 使用临时占位符避免format()解析
                tmdbid_placeholder = "__TMDBID_PLACEHOLDER__"
                if tmdb_id:
                    # 将 {tmdbid=tmdbid} 替换为临时占位符
                    processed_template = processed_template.replace(
                        "{tmdbid=tmdbid}", tmdbid_placeholder
                    )
                else:
                    # 如果没有tmdb_id，移除这个占位符
                    processed_template = processed_template.replace(
                        " {tmdbid=tmdbid}", ""
                    )
                    processed_template = processed_template.replace(
                        "{tmdbid=tmdbid}", ""
                    )

                # 使用模板生成路径
                path_str = processed_template.format(**format_vars)

                # 替换临时占位符为实际的tmdbid字符串
                if tmdb_id:
                    tmdbid_str = f"{{tmdbid={tmdb_id}}}"
                    path_str = path_str.replace(tmdbid_placeholder, tmdbid_str)

            # 强化后缀保护：如果生成的路径还没有后缀，强制追加
            if file_ext and not path_str.lower().endswith(file_ext.lower()):
                path_str = path_str + file_ext

            path = Path(path_str)

            # 确定分类目录
            category_path = self._determine_category(metadata)

            # 获取基础分类
            base_category = "TV Shows" if media_type == "tv" else "Movies"

            # 组合分类目录和文件名，避免重复的基础分类
            if path.parts and path.parts[0] == base_category:
                # 如果path已经包含了base_category，就去掉path的第一个部分
                full_path = Path(category_path) / Path(*path.parts[1:])
            else:
                full_path = Path(category_path) / path

            # 检测并处理文件冲突
            if output_dir:
                full_output_path = output_dir / full_path
                full_path = self._handle_file_conflict(full_output_path)

            return full_path
        except KeyError as e:
            logger.error(
                f"Naming template missing required variable: {e}. Using default path structure."
            )
            # 如果模板格式失败，使用默认结构
            if not metadata.get("show_name"):
                raise ValueError("Cannot generate path without show name")

            # Base structure: Show Name/Season X/Show Name - SXXEXX - Episode Name
            show_name = self._sanitize_filename(metadata["show_name"])
            season = metadata.get("season", "1")
            episode = metadata.get("episode", "1")
            episode_name = self._sanitize_filename(metadata.get("episode_name", ""))

            # Format season and episode numbers
            season_str = (
                f"Season {int(season):02d}"
                if str(season).isdigit()
                else f"Season {season}"
            )
            episode_str = (
                f"E{int(episode):02d}" if str(episode).isdigit() else f"E{episode}"
            )

            # Build filename
            filename_parts = [show_name, f"S{int(season):02d}{episode_str}"]
            if episode_name:
                filename_parts.append(episode_name)

            filename = " - ".join(filename_parts)

            # 如果提供了原始路径，保留扩展名
            if original_path and original_path.suffix:
                filename += original_path.suffix

            # 直接使用文件名，不添加分类目录前缀
            base_path = Path(f"{filename}")

            # 不添加分类目录前缀
            return base_path

        return path

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string to be safe for use as a filename."""
        if not name:
            return ""

        # Replace problematic characters
        import re

        name = re.sub(r"[<>:/\\|?*]", "", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name

    def _handle_file_conflict(self, file_path: Path) -> Path:
        """
        处理文件冲突，当文件存在时发出警告但保留原始文件名

        Args:
            file_path (Path): 原始文件路径

        Returns:
            Path: 原始文件路径

        Raises:
            FileExistsError: 当文件已存在时抛出异常，提醒冲突
        """
        if file_path.exists():
            logger.warning(f"文件已存在，无法覆盖: {file_path}")
            # 不自动生成新名称，而是提醒冲突
            raise FileExistsError(f"文件已存在，无法覆盖: {file_path}")

        # 如果文件不存在，直接返回原始路径
        return file_path

    def set_naming_rules(self, rules: Dict[str, str]) -> None:
        """设置自定义命名规则

        Args:
            rules (Dict[str, str]): 命名规则字典，键为媒体类型，值为模板字符串
        """
        for media_type, template in rules.items():
            if media_type in self.naming_rules:
                self.naming_rules[media_type] = template
                logger.info(f"Updated naming rule for {media_type}: {template}")
            else:
                logger.warning(f"Unknown media type for naming rule: {media_type}")
