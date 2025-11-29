"""
Module for extracting metadata from video files and generating new names.
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, Optional

from src.video_organizer.core.tmdb_client import TMDBClient

logger = logging.getLogger(__name__)


class VideoRenamer:
    """Extracts metadata from video files and generates organized paths."""
    
    # 默认命名规则模板
    DEFAULT_NAMING_RULES = {
        "tv_show": "{show_name}{year_suffix}{tmdbid_suffix}/Season {season:02d}/{show_name} {season_episode} {video_format}{web_source}{edition}{video_codec}{audio_codec}{customization}{release_group}",
        "movie": "{movie_name}{year_suffix}{tmdbid_suffix}/{movie_name}{en_title_suffix}{year_suffix}{web_source}{edition}{part}{video_format}{video_codec}{audio_codec}{customization_suffix}{release_group_suffix}",
        "anime": "{anime_name}/{season_name}/{anime_name} - S{season:02d}E{episode:02d}",
        "simple": "{title}"
    }
    
    def __init__(self, tmdb_api_key: str, ai_service_url: Optional[str] = None, watch_path: Optional[Path] = None, naming_rules: Optional[Dict] = None):
        self.tmdb_client = TMDBClient(tmdb_api_key)
        self.ai_service_url = ai_service_url
        self.watch_path = watch_path
        # 使用提供的命名规则或默认规则
        self.naming_rules = naming_rules if naming_rules else self.DEFAULT_NAMING_RULES
        
    def extract_metadata(self, file_path: Path, media_type_hint: Optional[str] = None) -> Dict:
        """
        从视频文件路径中提取元数据。
        
        Args:
            file_path (Path): 文件路径
            media_type_hint (str, optional): 媒体类型提示（tv, movie等）
            
        Returns:
            Dict: 提取的元数据
        """
        # First try to extract using regex patterns
        metadata = self._extract_with_regex(file_path.name)
        
        # 如果提供了媒体类型提示，添加到元数据中
        if media_type_hint:
            metadata['media_type'] = media_type_hint
        # 如果没有show_name就使用文件名
        if not metadata.get('show_name'):
            if self.watch_path:
                relative_path = file_path.relative_to(self.watch_path)
                # 使用相对路径的第一级目录名称作为视频名称
                if len(relative_path.parts) > 1:
                    metadata['show_name'] = relative_path.parts[0]  # 第一级目录名称
                else:
                    metadata['show_name'] = file_path.stem  # 如果文件直接在watch_path下，使用文件名

        # 从tmdb中获取视频信息生成刮削元数据
        if metadata.get('show_name'):
            metadata = self._enrich_with_tmdb(metadata)
            # 如果没有季号就使用1
            if not metadata.get('season'):
                metadata['season'] = 1
        # If regex fails or results are incomplete, try AI service
        if (self.ai_service_url and 
            (not metadata.get('show_name') or not metadata.get('season') or not metadata.get('episode'))):
            # 获取相对于watch_path的路径作为视频名称
            if self.watch_path:
                try:
                    # 计算相对路径
                    relative_path = file_path.relative_to(self.watch_path)
                    # 使用相对路径的第一级目录名称作为视频名称
                    if len(relative_path.parts) > 1:
                        video_name = relative_path.parts[0]  # 第一级目录名称
                    else:
                        video_name = file_path.stem  # 如果文件直接在watch_path下，使用文件名
                    logger.info(f"Using directory name as video name: {video_name}")
                    metadata = self._extract_with_ai(video_name, metadata)
                except ValueError:
                    # 如果文件不在watch_path下，使用文件名
                    logger.warning(f"File {file_path} is not under watch_path {self.watch_path}, using filename")
                    metadata = self._extract_with_ai(file_path.name, metadata)
            else:
                metadata = self._extract_with_ai(file_path.name, metadata)
            
        # Enrich with TMDB data if we have a show name
        if metadata.get('show_name'):
            metadata = self._enrich_with_tmdb(metadata)
            
        return metadata
    
    def _extract_with_regex(self, filename: str) -> Dict:
        """Extract metadata using regular expressions."""
        metadata = {}
        
        # 提取文件基本信息
        base_name, ext = os.path.splitext(filename)
        metadata['extension'] = ext.lower()
        metadata['original_filename'] = filename
        
        # 清理文件名，移除常见的修饰词和标记
        cleaned_name = self._clean_filename_for_search(base_name)
        metadata['cleaned_name'] = cleaned_name
        
        # Common patterns for TV shows
        patterns = [
            # Pattern: 中文名 S01E01
            r"^(?P<show_name>[\w\s\u4e00-\u9fff]+)\s*S(?P<season>\d+)E(?P<episode>\d+)",
            # Pattern: 中文名 Season 1 Episode 2
            r"^(?P<show_name>[\w\s\u4e00-\u9fff]+)\s+Season\s+(?P<season>\d+)\s+Episode\s+(?P<episode>\d+)",
            # Pattern: 中文名 - 第1季第2集
            r"^(?P<show_name>[\w\s\u4e00-\u9fff]+)\s*-\s*第(?P<season>\d+)季第(?P<episode>\d+)集",
            # Pattern: 中文名 第1集
            r"^(?P<show_name>[\w\s\u4e00-\u9fff]+)\s*第(?P<episode>\d+)集",
            # Pattern: S01E01.ext (simple format without show name)
            r"^S(?P<season>\d+)E(?P<episode>\d+)",
            r"^E(?P<episode>\d+)",
            r"^(?P<episode>\d+)",
            # Pattern: Show.Name.S01E02.quality-group.ext
            r"(?P<show_name>[\w\.]+)\.S(?P<season>\d+)E(?P<episode>\d+)",
            # Pattern: Show Name - s01e02 - Episode Title.ext
            r"(?P<show_name>[\w\s]+)\s*-\s*s(?P<season>\d+)e(?P<episode>\d+)",
            # Pattern: Show Name Season 1 Episode 2.ext
            r"(?P<show_name>[\w\s]+)\s+Season\s+(?P<season>\d+)\s+Episode\s+(?P<episode>\d+)",
            # Pattern: Show Name - Season 1 - Episode 2.ext
            r"(?P<show_name>[\w\s]+)\s*-\s*Season\s+(?P<season>\d+)\s*-\s*Episode\s+(?P<episode>\d+)",
            # Pattern: Show Name - S01E02 - Episode Title.ext
            r"(?P<show_name>[\w\s]+)\s*-\s*S(?P<season>\d+)E(?P<episode>\d+)"
        ]
        
        # 优先使用中文模式匹配
        for pattern in patterns:
            match = re.search(pattern, cleaned_name, re.IGNORECASE)
            if match:
                metadata.update(match.groupdict())
                # Clean up show name
                if 'show_name' in metadata:
                    # 特别处理中文名称，不进行title()转换
                    if re.search(r'[\u4e00-\u9fff]', metadata['show_name']):
                        metadata['show_name'] = metadata['show_name'].replace('.', ' ').strip()
                    else:
                        metadata['show_name'] = metadata['show_name'].replace('.', ' ').title()
                break
                
        # 如果没有匹配到show_name但有cleaned_name，尝试提取show_name
        if not metadata.get('show_name') and cleaned_name:
            # 从清理后的名称中提取可能的剧集信息，然后获取show_name
            season_episode_pattern = r'(S\d+E\d+|第\d+季第\d+集|第\d+集)'
            match = re.search(season_episode_pattern, cleaned_name, re.IGNORECASE)
            if match:
                # 提取show_name为剧集信息前的部分
                show_name = cleaned_name[:match.start()].strip()
                if show_name:
                    metadata['show_name'] = show_name
            else:
                # 如果没有找到剧集信息，使用整个cleaned_name作为show_name
                metadata['show_name'] = cleaned_name
                
        return metadata
    
    def _extract_with_ai(self, filename: str, existing_metadata: Dict) -> Dict:
        """
        Use AI service to extract metadata from filename.
        """
        logger.warning("AI extraction not implemented, using regex results only")

        
        return existing_metadata
    
    def _clean_filename_for_search(self, filename: str) -> str:
        """清理文件名，移除常见的修饰词和标记，为搜索做准备"""
        # 移除常见的质量标记和标签
        quality_markers = [
            r'(?:\b(?:HD|FHD|UHD|4K|1080p|720p|480p|360p|240p)\b)',
            r'(?:\b(?:HDR|SDR|HDR10|Dolby\s*Vision)\b)',
            r'(?:\b(?:x264|x265|h264|h265|HEVC|AVC|MPEG4)\b)',
            r'(?:\b(?:AAC|DTS|DDP|TrueHD|Atmos)\b)',
            r'(?:\b(?:BD|BDRip|BluRay|DVD|DVDRip|WEB|WEBRip)\b)',
            r'(?:\b(?:REPACK|PROPER|INTERNAL)\b)',
            r'(?:\b(?:CHS|ENG|双语|字幕|中字|英字)\b)',
            r'(?:\b(?:AC3|DTS-HD)\b)',
            r'(?:\b(?:MP4|MKV|AVI)\b)'
        ]
        
        cleaned = filename
        
        # 移除质量标记
        for marker in quality_markers:
            cleaned = re.sub(marker, '', cleaned, flags=re.IGNORECASE)
        
        # 移除括号及内容
        cleaned = re.sub(r'\[[^\]]+\]', '', cleaned)
        cleaned = re.sub(r'\([^\)]+\)', '', cleaned)
        
        # 移除多余的空格和特殊字符
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = re.sub(r'[^\w\s\u4e00-\u9fff\-]', '', cleaned)
        cleaned = cleaned.strip()
        
        return cleaned
        
    def _prepare_search_term(self, search_term: str) -> str:
        """准备搜索词，为TMDB搜索优化"""
        # 移除多余空格
        prepared = re.sub(r'\s+', ' ', search_term).strip()
        
        # 对于中文，保留原始格式
        if re.search(r'[\u4e00-\u9fff]', prepared):
            # 对于中文名称，移除可能的季集信息
            prepared = re.sub(r'S\d+E\d+', '', prepared, flags=re.IGNORECASE)
            prepared = re.sub(r'第\d+季(第\d+集)?', '', prepared, flags=re.IGNORECASE)
            prepared = re.sub(r'\d+集', '', prepared)
            prepared = prepared.strip()
        else:
            # 对于英文，确保空格分离
            prepared = prepared.title()
            
        return prepared
        
    def _enrich_with_tmdb(self, metadata: Dict) -> Dict:
        """使用TMDB API丰富元数据信息，获取更完整的视频详情"""
        try:
            # 优先使用show_name搜索，否则使用title
            search_term = metadata.get('show_name', metadata.get('title', ''))
            if not search_term:
                return metadata
            
            # 准备优化后的搜索词
            prepared_search_term = self._prepare_search_term(search_term)
            logger.info(f"搜索TMDB: 原始搜索词='{search_term}', 优化后搜索词='{prepared_search_term}'")
            
            # 搜索匹配的视频信息
            # 首先尝试明确的类型搜索
            media_type_hint = metadata.get('media_type', metadata.get('type', ''))
            year = metadata.get('year')
            
            results = []
            
            # 智能搜索策略：先使用优化后的搜索词搜索
            if media_type_hint == 'tv':
                # 使用专门的电视剧搜索
                search_results = self.tmdb_client.search_tv(prepared_search_term, int(year) if year else None)
                if search_results and 'results' in search_results:
                    results = search_results['results']
            elif media_type_hint == 'movie':
                # 使用专门的电影搜索
                search_results = self.tmdb_client.search_movie(prepared_search_term, int(year) if year else None)
                if search_results and 'results' in search_results:
                    results = search_results['results']
            
            # 如果没有专门类型的搜索结果，使用通用搜索
            if not results:
                results = self.tmdb_client.search_video_show(prepared_search_term, year)
            
            # 如果第一次搜索失败，尝试使用原始搜索词作为备选
            if not results and search_term != prepared_search_term:
                logger.info(f"优化搜索词未找到结果，尝试原始搜索词: '{search_term}'")
                if media_type_hint == 'tv':
                    search_results = self.tmdb_client.search_tv(search_term, int(year) if year else None)
                    if search_results and 'results' in search_results:
                        results = search_results['results']
                elif media_type_hint == 'movie':
                    search_results = self.tmdb_client.search_movie(search_term, int(year) if year else None)
                    if search_results and 'results' in search_results:
                        results = search_results['results']
                if not results:
                    results = self.tmdb_client.search_video_show(search_term, year)
            
            if not results:
                logger.warning(f"没有找到匹配 '{search_term}' 的结果")
                return metadata
            
            # 寻找最匹配的结果
            best_match = None
            for result in results:
                # 尝试匹配年份
                date_field = 'first_air_date' if result.get('media_type') == 'tv' else 'release_date'
                if date_field in result and result[date_field]:
                    result_year = result[date_field].split('-')[0]
                    if result_year == metadata.get('year'):
                        best_match = result
                        break
            
            # 如果没有找到年份匹配，使用第一个结果
            if not best_match:
                best_match = results[0]
            
            # 获取详细信息
            media_type = best_match.get('media_type', 'tv')
            
            # 使用专门的API获取更详细的信息
            if media_type == 'tv':
                # 获取电视剧详细信息
                details = self.tmdb_client.get_tv_details(best_match['id'])
                if details:
                    # 保存原始标题
                    original_name = metadata.get('show_name')
                    metadata['original_show_name'] = original_name
                    # 丰富元数据，但保留原始标题
                    metadata['show_name'] = original_name  # 优先使用原始标题，不覆盖为英文
                    metadata['overview'] = details.get('overview', '')
                    metadata['rating'] = details.get('vote_average', 0)
                    metadata['genres'] = [genre['name'] for genre in details.get('genres', [])]
                    metadata['original_name'] = details.get('original_name', '')
                    metadata['first_air_date'] = details.get('first_air_date', '')
                    metadata['last_air_date'] = details.get('last_air_date', '')
                    metadata['status'] = details.get('status', '')
                    metadata['number_of_seasons'] = details.get('number_of_seasons', 0)
                    metadata['number_of_episodes'] = details.get('number_of_episodes', 0)
                    
                    # 获取网络信息
                    if 'networks' in details:
                        metadata['networks'] = [network['name'] for network in details['networks']]
                    
                    # 获取演职人员信息
                    credits = self.tmdb_client.get_tv_credits(best_match['id'])
                    if credits:
                        # 只取前10位演员
                        metadata['cast'] = [
                            {'name': actor['name'], 'character': actor.get('character', ''), 'profile_path': actor.get('profile_path', '')}
                            for actor in credits.get('cast', [])[:10]
                        ]
                        # 只取导演和编剧
                        metadata['crew'] = [
                            {'name': crew['name'], 'job': crew.get('job', '')}
                            for crew in credits.get('crew', []) 
                            if crew.get('job') in ['Director', 'Writer', 'Creator']
                        ][:5]  # 限制数量
                    
                    # 如果有剧集信息，尝试找到对应的剧集
                    if 'season' in metadata and 'episode' in metadata:
                        try:
                            # 获取剧集详细信息
                            episode_details = self.tmdb_client.get_tv_episode_details(
                                best_match['id'], 
                                metadata['season'], 
                                metadata['episode']
                            )
                            if episode_details:
                                # 设置剧集名称
                                metadata['episode_name'] = episode_details.get('name', '')
                                metadata['episode_overview'] = episode_details.get('overview', '')
                                metadata['air_date'] = episode_details.get('air_date', '')
                                metadata['episode_rating'] = episode_details.get('vote_average', 0)
                        except Exception as e:
                            logger.warning(f"获取剧集详情失败: {e}")
            else:
                # 获取电影详细信息
                details = self.tmdb_client.get_movie_details(best_match['id'])
                if details:
                    # 保存原始标题
                    original_title = metadata.get('title')
                    metadata['original_title'] = original_title
                    # 丰富元数据，但保留原始标题
                    metadata['title'] = original_title  # 优先使用原始标题，不覆盖为英文
                    metadata['overview'] = details.get('overview', '')
                    metadata['rating'] = details.get('vote_average', 0)
                    metadata['genres'] = [genre['name'] for genre in details.get('genres', [])]
                    metadata['original_title'] = details.get('original_title', '')
                    metadata['release_date'] = details.get('release_date', '')
                    metadata['runtime'] = details.get('runtime', 0)
                    metadata['status'] = details.get('status', '')
                    metadata['budget'] = details.get('budget', 0)
                    metadata['revenue'] = details.get('revenue', 0)
                    
                    # 获取外部ID信息
                    external_ids = self.tmdb_client.get_external_ids(best_match['id'], 'movie')
                    if external_ids:
                        metadata['imdb_id'] = external_ids.get('imdb_id', '')
                        metadata['tmdb_id'] = external_ids.get('id', '')
                    
                    # 获取评论（如果可用）
                    if 'reviews' in details and details['reviews'].get('results'):
                        metadata['reviews'] = [
                            {'author': review['author'], 'content': review['content']}
                            for review in details['reviews']['results'][:3]  # 只取前3条评论
                        ]
            
            return metadata
        except Exception as e:
            logger.error(f"TMDB enrichment failed: {e}")
            return metadata
    
    def _determine_category(self, metadata: Dict) -> str:
        """
        根据元数据确定视频的分类目录
        
        Args:
            metadata (Dict): 包含视频元数据的字典
            
        Returns:
            str: 分类目录路径
        """
        # 确定基础分类（电视剧/电影）
        media_type = metadata.get('media_type')
        base_category = 'Movies' if media_type == 'movie' else 'TV Shows'
        
        # 获取语言和地区信息
        original_language = metadata.get('original_language', '').lower()
        origin_countries = metadata.get('origin_country', [])
        
        # 扩展的国家/地区识别列表
        chinese_countries = ['CN', 'HK', 'TW']
        english_countries = ['US', 'GB', 'CA', 'AU', 'NZ']
        asian_countries = ['JP', 'KR', 'TH', 'IN']
        
        # 子分类逻辑
        sub_category = ''
        
        if base_category == 'TV Shows':
            # 电视剧子分类
            # 1. 检查是否有原始中文名（更可靠的方法）
            original_show_name = metadata.get('original_show_name', '')
            if original_show_name and re.search(r'[\u4e00-\u9fff]', original_show_name):
                sub_category = '国产剧'
            # 2. 检查语言和地区
            elif original_language in ['zh', 'cn'] or any(country in chinese_countries for country in origin_countries):
                sub_category = '国产剧'
            elif original_language in ['en'] or any(country in english_countries for country in origin_countries):
                sub_category = '欧美剧'
            elif original_language in ['ja', 'ko', 'th', 'hi'] or any(country in asian_countries for country in origin_countries):
                sub_category = '日韩剧'
            else:
                sub_category = '其他剧'
        else:
            # 电影子分类
            original_title = metadata.get('original_title', '')
            if original_title and re.search(r'[\u4e00-\u9fff]', original_title):
                sub_category = '华语电影'
            elif original_language in ['zh', 'cn'] or any(country in chinese_countries for country in origin_countries):
                sub_category = '华语电影'
            else:
                sub_category = '外语电影'
        
        # 组合分类路径
        return f"{base_category}/{sub_category}"
    
    def generate_new_path(self, metadata: Dict, rule_type: Optional[str] = None, original_path: Optional[Path] = None, output_dir: Optional[Path] = None) -> Path:
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
        # 确定媒体类型和适当的命名规则
        media_type = metadata.get('media_type')
        if rule_type is None:
            if media_type == 'tv' or (metadata.get('season') and metadata.get('episode')):
                rule_type = 'tv_show'
            elif media_type == 'movie':
                rule_type = 'movie'
            else:
                rule_type = 'simple'
        
        # 获取对应的命名模板
        template = self.naming_rules.get(rule_type, self.naming_rules['simple'])
        
        # 准备用于格式化的变量字典，优先使用原始标题
        season = int(metadata.get('season', 1)) if metadata.get('season') else 1
        episode = int(metadata.get('episode', 1)) if metadata.get('episode') else 1
        
        # 处理各种条件后缀
        year_suffix = f" ({metadata.get('year')})" if metadata.get('year') else ""
        tmdbid_suffix = f" {{tmdbid={metadata.get('tmdb_id')}}}" if metadata.get('tmdb_id') else ""
        en_title_suffix = f".{metadata.get('en_title')}" if metadata.get('en_title') else ""
        web_source = f".{metadata.get('web_source')}" if metadata.get('web_source') else ""
        edition = f".{metadata.get('edition')}" if metadata.get('edition') else ""
        part = f".{metadata.get('part')}" if metadata.get('part') else ""
        video_format = f"{metadata.get('video_format')}" if metadata.get('video_format') else ""
        video_codec = f".{metadata.get('video_codec')}" if metadata.get('video_codec') else ""
        audio_codec = f".{metadata.get('audio_codec')}" if metadata.get('audio_codec') else ""
        customization = f".{metadata.get('customization')}" if metadata.get('customization') else ""
        customization_suffix = f"-{metadata.get('customization')}" if metadata.get('customization') else ""
        release_group = f"-{metadata.get('release_group')}" if metadata.get('release_group') else ""
        release_group_suffix = f"-{metadata.get('release_group')}" if metadata.get('release_group') else ""
        
        # 电视剧季集格式
        season_episode = f"S{season:02d}E{episode:02d}"
        
        format_vars = {
            'title': self._sanitize_filename(metadata.get('original_title', metadata.get('title', metadata.get('show_name', 'Unknown Title')))),
            'year': metadata.get('year', ''),
            'year_suffix': year_suffix,
            'tmdbid_suffix': tmdbid_suffix,
            'en_title_suffix': en_title_suffix,
            'web_source': web_source,
            'edition': edition,
            'part': part,
            'video_format': video_format,
            'video_codec': video_codec,
            'audio_codec': audio_codec,
            'customization': customization,
            'customization_suffix': customization_suffix,
            'release_group': release_group,
            'release_group_suffix': release_group_suffix,
            'season_episode': season_episode,
            'show_name': self._sanitize_filename(metadata.get('original_show_name', metadata.get('show_name', 'Unknown Show'))),
            'season': season,
            'episode': episode,
            'episode_name': self._sanitize_filename(metadata.get('episode_name', '')),
            'movie_name': self._sanitize_filename(metadata.get('original_title', metadata.get('title', 'Unknown Movie'))),
            'anime_name': self._sanitize_filename(metadata.get('original_show_name', metadata.get('show_name', 'Unknown Anime'))),
            'season_name': f"Season {season:02d}"
        }
        
        try:
            # 使用模板生成路径
            path_str = template.format(**format_vars)
            path = Path(path_str)
            
            # 如果提供了原始路径，保留扩展名
            if original_path and original_path.suffix:
                path = path.with_suffix(original_path.suffix)
            
            # 添加分类目录前缀
            category = self._determine_category(metadata)
            full_path = Path(category) / path
            
            # 检测并处理文件冲突
            if output_dir:
                full_output_path = output_dir / full_path
                full_path = self._handle_file_conflict(full_output_path)
            
            return full_path
        except KeyError as e:
            logger.error(f"Naming template missing required variable: {e}. Using default path structure.")
            # 如果模板格式失败，使用默认结构
            if not metadata.get('show_name'):
                raise ValueError("Cannot generate path without show name")
                
            # Base structure: Show Name/Season X/Show Name - SXXEXX - Episode Name
            show_name = self._sanitize_filename(metadata['show_name'])
            season = metadata.get('season', '1')
            episode = metadata.get('episode', '1')
            episode_name = self._sanitize_filename(metadata.get('episode_name', ''))
            
            # Format season and episode numbers
            season_str = f"Season {int(season):02d}" if str(season).isdigit() else f"Season {season}"
            episode_str = f"E{int(episode):02d}" if str(episode).isdigit() else f"E{episode}"
            
            # Build filename
            filename_parts = [show_name, f"S{int(season):02d}{episode_str}"]
            if episode_name:
                filename_parts.append(episode_name)
                
            filename = " - ".join(filename_parts)
            
            # 如果提供了原始路径，保留扩展名
            if original_path and original_path.suffix:
                filename += original_path.suffix
            
            # Build full path
            base_path = Path(show_name) / season_str / f"{filename}"
            
            # 添加分类目录前缀
            category = self._determine_category(metadata)
            return Path(category) / base_path
        
        return path
    
    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string to be safe for use as a filename."""
        if not name:
            return ""
            
        # Replace problematic characters
        import re
        name = re.sub(r'[<>:/\\|?*]', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
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