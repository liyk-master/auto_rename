"""
中文处理工具 — 繁简转换、中文数字/罗马数字转阿拉伯数字
"""

import re
import urllib.parse
import logging
from typing import Optional

# 繁简转换支持
try:
    import zhconv
    ZHCONV_AVAILABLE = True
except ImportError:
    ZHCONV_AVAILABLE = False

logger = logging.getLogger(__name__)


def decode_filename(filename: str) -> str:
    """
    解码 URL 编码的文件名。

    Args:
        filename: 可能是 URL 编码的文件名

    Returns:
        str: 解码后的文件名
    """
    if not filename:
        return filename

    # 检测是否包含 URL 编码
    if not re.search(r'%[0-9A-Fa-f]{2}', filename):
        return filename

    try:
        decoded = urllib.parse.unquote(filename)
        # 处理双重编码
        if re.search(r'%[0-9A-Fa-f]{2}', decoded):
            decoded = urllib.parse.unquote(decoded)
        return decoded
    except Exception:
        return filename


def roman_to_digit(roman: str) -> Optional[int]:
    """将罗马数字转换为阿拉伯数字 (I-X)"""
    roman_dict = {
        "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
        "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    }
    if not roman:
        return None
    return roman_dict.get(roman.upper())


def chinese_to_digit(cn_str: str) -> Optional[int]:
    """将中文数字转换为阿拉伯数字 (1-99)，支持简体、繁体大写数字"""
    cn_map = {
        # 简体数字
        "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        # 繁体大写数字（用于日文"之章"等格式）
        "壹": 1, "贰": 2, "參": 3, "肆": 4, "伍": 5,
        "陆": 6, "柒": 7, "捌": 8, "玖": 9, "拾": 10,
        # 阿拉伯数字
        "0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
        "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    }

    if not cn_str:
        return None

    # 如果是纯数字字符串
    if cn_str.isdigit():
        return int(cn_str)

    # 处理简单的中文数字
    if len(cn_str) == 1:
        return cn_map.get(cn_str)

    # 处理"十"开头的（如：十一、十二）
    if len(cn_str) == 2 and cn_str[0] == "十":
        return 10 + cn_map.get(cn_str[1], 0)

    # 处理"二十"、"三十"等
    if len(cn_str) == 2 and cn_str[1] == "十":
        return cn_map.get(cn_str[0], 0) * 10

    # 处理"二十一"等
    if len(cn_str) == 3 and cn_str[1] == "十":
        return cn_map.get(cn_str[0], 0) * 10 + cn_map.get(cn_str[2], 0)

    return None