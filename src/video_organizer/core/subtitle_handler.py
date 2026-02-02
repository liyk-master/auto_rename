"""
字幕文件处理器模块
用于智能识别、重命名和组织字幕文件
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SubtitleHandler:
    """字幕文件处理器"""

    # 字幕语言映射
    LANGUAGE_CODES = {
        # 英语
        'eng': 'English',
        'en': 'English',
        'english': 'English',
        # 中文
        'chs': 'Chinese.Simplified',
        'cht': 'Chinese.Traditional',
        'zh': 'Chinese',
        'chinese': 'Chinese',
        '简体': 'Chinese.Simplified',
        '繁体': 'Chinese.Traditional',
        # 葡萄牙语
        'por': 'Portuguese',
        'pt': 'Portuguese',
        'portuguese': 'Portuguese',
        'brazilian': 'Portuguese.Brazilian',
        # 西班牙语
        'spa': 'Spanish',
        'es': 'Spanish',
        'spanish': 'Spanish',
        # 法语
        'fre': 'French',
        'fr': 'French',
        'french': 'French',
        # 德语
        'ger': 'German',
        'de': 'German',
        'german': 'German',
        # 日语
        'jpn': 'Japanese',
        'ja': 'Japanese',
        'japanese': 'Japanese',
        # 韩语
        'kor': 'Korean',
        'ko': 'Korean',
        'korean': 'Korean',
        # 俄语
        'rus': 'Russian',
        'ru': 'Russian',
        'russian': 'Russian',
        # 阿拉伯语
        'ara': 'Arabic',
        'ar': 'Arabic',
        'arabic': 'Arabic',
        # 意大利语
        'ita': 'Italian',
        'it': 'Italian',
        'italian': 'Italian',
    }

    # 字幕类型标识
    SUBTITLE_TYPES = {
        'sdh': 'SDH',  # 听障字幕
        'hi': 'HI',    # 听障标识
        'forced': 'Forced',  # 强制字幕
        'cc': 'CC',   # 闭路字幕
        'normal': 'Normal',  # 标准字幕
    }

    def __init__(self):
        self.logger = logger

    def is_subtitle_file(self, file_path: Path) -> bool:
        """
        判断文件是否为字幕文件

        Args:
            file_path: 文件路径

        Returns:
            是否为字幕文件
        """
        subtitle_extensions = {'.srt', '.ass', '.ssa', '.sub', '.vtt'}
        return file_path.suffix.lower() in subtitle_extensions

    def parse_subtitle_filename(self, filename: str) -> Dict[str, Optional[str]]:
        """
        解析字幕文件名，提取语言和类型信息

        Args:
            filename: 字幕文件名

        Returns:
            包含语言、类型等信息的字典
        """
        result = {
            'language': None,
            'language_code': None,
            'type': 'Normal',
            'is_sdh': False,
            'is_forced': False,
        }

        filename_lower = filename.lower()

        # 检查是否为听障字幕 (SDH/HI)
        if 'sdh' in filename_lower or '.hi.' in filename_lower or filename_lower.endswith('.hi.srt'):
            result['is_sdh'] = True
            result['type'] = 'SDH'

        # 检查是否为强制字幕
        if 'forced' in filename_lower:
            result['is_forced'] = True
            result['type'] = 'Forced'

        # 提取语言信息
        # 优先匹配显式的语言代码 (如 .eng., .por.srt)
        for code, lang in self.LANGUAGE_CODES.items():
            # 匹配 .eng. 或 .eng.srt 格式
            pattern = rf'\.{code}\.|\.{code}\.(?:srt|ass|ssa|sub|vtt)$'
            if re.search(pattern, filename_lower):
                result['language_code'] = code
                result['language'] = lang
                break

        # 如果没有找到语言代码，尝试从文件名中提取
        if not result['language']:
            # 匹配语言名称 (如 English, Portuguese)
            for lang_name in set(self.LANGUAGE_CODES.values()):
                # 只匹配完整的语言名称
                pattern = rf'\b{re.escape(lang_name.lower())}\b'
                if re.search(pattern, filename_lower):
                    result['language'] = lang_name
                    # 反向查找语言代码
                    for code, lang in self.LANGUAGE_CODES.items():
                        if lang == lang_name:
                            result['language_code'] = code
                            break
                    break

        return result

    def find_matching_video(self, subtitle_path: Path, video_extensions: Tuple[str, ...] = ('.mp4', '.mkv', '.avi', '.mov', '.wmv')) -> Optional[Path]:
        """
        查找与字幕文件匹配的视频文件

        Args:
            subtitle_path: 字幕文件路径
            video_extensions: 视频文件扩展名列表

        Returns:
            匹配的视频文件路径，如果没有找到则返回 None
        """
        if not subtitle_path.exists():
            return None

        directory = subtitle_path.parent
        subtitle_stem = subtitle_path.stem  # 不包含扩展名的文件名

        # 尝试不同的匹配策略
        candidates = []

        for video_file in directory.iterdir():
            if not video_file.is_file() or video_file.suffix.lower() not in video_extensions:
                continue

            video_stem = video_file.stem

            # 策略1: 完全匹配（字幕文件名与视频文件名完全相同）
            if video_stem == subtitle_stem:
                candidates.append((video_file, 100))  # 最高优先级
                continue

            # 策略2: 去除语言标识后匹配
            # 从字幕文件名中移除语言标识
            cleaned_subtitle_stem = subtitle_stem
            for code, lang in self.LANGUAGE_CODES.items():
                # 移除 .eng. 格式
                cleaned_subtitle_stem = re.sub(rf'\.{code}\.', '.', cleaned_subtitle_stem, flags=re.IGNORECASE)
                # 移除 .eng.srt 格式
                cleaned_subtitle_stem = re.sub(rf'\.{code}$', '', cleaned_subtitle_stem, flags=re.IGNORECASE)

            # 移除 SDH/HI 标识
            cleaned_subtitle_stem = re.sub(r'\.sdh\.|\.hi\.|\.sdh$|\.hi$', '', cleaned_subtitle_stem, flags=re.IGNORECASE)

            if video_stem == cleaned_subtitle_stem:
                candidates.append((video_file, 90))  # 高优先级
                continue

            # 策略3: 视频文件名包含字幕文件名（处理 YTS 等命名格式）
            if video_stem in cleaned_subtitle_stem or cleaned_subtitle_stem in video_stem:
                # 计算相似度得分
                similarity = self._calculate_similarity(video_stem, cleaned_subtitle_stem)
                if similarity > 0.7:  # 相似度阈值
                    candidates.append((video_file, int(similarity * 80)))
                continue

            # 策略4: 目录中只有一个视频文件，字幕文件名只是语言标识
            # 这种情况下，字幕文件应该关联到唯一的视频文件
            video_count = sum(1 for f in directory.iterdir() if f.is_file() and f.suffix.lower() in video_extensions)
            if video_count == 1:
                # 检查字幕文件名是否只是语言标识（如 English.srt, Portuguese.srt）
                # 或者包含已知的语言代码
                is_language_only = False
                subtitle_lower = subtitle_stem.lower()
                for code, lang in self.LANGUAGE_CODES.items():
                    if subtitle_lower == code or subtitle_lower == lang.lower():
                        is_language_only = True
                        break

                if is_language_only:
                    candidates.append((video_file, 70))  # 中等优先级

        # 按优先级排序，返回最佳匹配
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            # 返回所有匹配的视频文件（按优先级排序）
            return candidates[0][0]

        return None

    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """
        计算两个字符串的相似度（简单的字符匹配）

        Args:
            str1: 字符串1
            str2: 字符串2

        Returns:
            相似度得分 (0-1)
        """
        # 简单的 Jaccard 相似度
        set1 = set(str1.lower())
        set2 = set(str2.lower())
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0

    def generate_subtitle_name(self, video_filename: str, subtitle_info: Dict[str, Optional[str]], keep_original: bool = True) -> str:
        """
        为字幕文件生成新的文件名

        Args:
            video_filename: 视频文件名
            subtitle_info: 字幕信息字典
            keep_original: 是否保留原始文件名中的语言标识

        Returns:
            新的字幕文件名
        """
        video_path = Path(video_filename)
        video_stem = video_path.stem
        video_ext = video_path.suffix

        # 获取字幕扩展名
        subtitle_ext = '.srt'  # 默认使用 .srt

        # 构建新的字幕文件名
        new_name = video_stem

        # 添加语言标识
        if subtitle_info.get('language'):
            lang = subtitle_info['language']
            # 简化语言名称（如 Chinese.Simplified -> Chinese）
            lang_simple = lang.split('.')[0]

            # 如果不是标准字幕，添加类型标识
            if subtitle_info.get('type') != 'Normal':
                subtitle_type = subtitle_info['type']
                new_name = f"{new_name}.{lang}.{subtitle_type}{subtitle_ext}"
            else:
                new_name = f"{new_name}.{lang}{subtitle_ext}"
        else:
            # 如果没有语言信息，保持原样或添加通用标识
            new_name = f"{new_name}{subtitle_ext}"

        return new_name

    def process_subtitle_file(self, subtitle_path: Path, output_dir: Path, video_extensions: Tuple[str, ...] = ('.mp4', '.mkv', '.avi', '.mov', '.wmv')) -> Optional[Path]:
        """
        处理字幕文件：查找匹配的视频文件并重命名

        Args:
            subtitle_path: 字幕文件路径
            output_dir: 输出目录
            video_extensions: 视频文件扩展名列表

        Returns:
            处理后的字幕文件路径，如果处理失败则返回 None
        """
        if not self.is_subtitle_file(subtitle_path):
            self.logger.warning(f"文件不是字幕文件: {subtitle_path}")
            return None

        # 解析字幕文件信息
        subtitle_info = self.parse_subtitle_filename(subtitle_path.name)
        self.logger.info(f"解析字幕文件: {subtitle_path.name}")
        self.logger.info(f"  语言: {subtitle_info.get('language', 'Unknown')}")
        self.logger.info(f"  类型: {subtitle_info.get('type', 'Normal')}")

        # 查找匹配的视频文件
        video_path = self.find_matching_video(subtitle_path, video_extensions)

        if not video_path:
            self.logger.warning(f"未找到匹配的视频文件: {subtitle_path.name}")
            # 如果没有找到视频文件，直接复制字幕文件
            dest_path = output_dir / subtitle_path.name
            return dest_path

        self.logger.info(f"找到匹配的视频文件: {video_path.name}")

        # 生成新的字幕文件名
        new_subtitle_name = self.generate_subtitle_name(video_path.name, subtitle_info)
        dest_path = output_dir / new_subtitle_name

        self.logger.info(f"字幕文件将重命名为: {new_subtitle_name}")

        return dest_path

    def batch_process_subtitles(self, directory: Path, output_dir: Optional[Path] = None) -> List[Tuple[Path, Optional[Path]]]:
        """
        批量处理目录中的所有字幕文件

        Args:
            directory: 要扫描的目录
            output_dir: 输出目录，如果为 None 则使用视频文件所在的目录

        Returns:
            处理结果列表 (原始路径, 目标路径)
        """
        results = []

        for file_path in directory.iterdir():
            if not self.is_subtitle_file(file_path):
                continue

            # 确定输出目录
            if output_dir:
                dest_path = self.process_subtitle_file(file_path, output_dir)
            else:
                # 查找视频文件，使用视频文件所在的目录作为输出目录
                video_path = self.find_matching_video(file_path)
                if video_path:
                    dest_path = self.process_subtitle_file(file_path, video_path.parent)
                else:
                    dest_path = None

            results.append((file_path, dest_path))

        return results