import logging
import requests
import json
from typing import List, Union, Optional

logger = logging.getLogger(__name__)


class LLMTranslator:
    """
    LLM translator using Zhipu AI (BigModel) API.
    """

    def __init__(
        self,
        api_key: str,
        api_url: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        model: str = "GLM-4.5-Flash",
    ):
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.enabled = bool(api_key)

    def translate_video_name(
        self, text: Union[str, List[str]], target_language: str = "Chinese"
    ) -> Union[str, List[str], None]:
        """
        Translate video name(s) using LLM.

        Args:
            text: Single video name string or list of video name strings (max 3).
            target_language: Target language (e.g., "Chinese", "English").

        Returns:
            Translated string or list of strings, or None if failed.
        """
        if not self.enabled:
            return None

        texts = [text] if isinstance(text, str) else text
        if not texts:
            return None

        if len(texts) > 3:
            logger.warning("LLMTranslator: Batch size exceeded 3, truncating.")
            texts = texts[:3]

        # 根据用户提供的参数格式构建请求
        target_lang_str = (
            "中文名" if target_language.lower() in ["chinese", "zh", "cn"] else "英文名"
        )
        content = "\n".join(
            [f"{t}（这是一个视频名，请直接翻译成{target_lang_str}返回）" for t in texts]
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一个视频名翻译专家。"},
                {"role": "user", "content": content},
            ],
            "temperature": 0.6,
            "top_p": 0.95,
        }

        try:
            logger.info(f"LLMTranslator: Translating {len(texts)} video names...")
            response = requests.post(
                self.api_url, headers=headers, json=payload, timeout=30
            )
            response.raise_for_status()

            result = response.json()
            if "choices" in result and len(result["choices"]) > 0:
                translated_content = result["choices"][0]["message"]["content"].strip()

                # 如果是多行返回（对应多个视频名），则拆分
                translated_lines = [
                    line.strip()
                    for line in translated_content.split("\n")
                    if line.strip()
                ]

                if isinstance(text, str):
                    return (
                        translated_lines[0] if translated_lines else translated_content
                    )
                return translated_lines
            else:
                logger.error(f"LLMTranslator: Unexpected response format: {result}")
                return None
        except requests.exceptions.Timeout:
            logger.error("LLMTranslator: Request timeout")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"LLMTranslator: Request failed: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"LLMTranslator: JSON decode error: {e}")
            return None

    def parse_filename(self, filename: str) -> Optional[dict]:
        """
        使用 LLM 解析复杂的视频文件名，提取元数据。

        Args:
            filename: 视频文件名

        Returns:
            包含元数据的字典，或者 None 如果失败。
            字典可能包含: show_name, season, episode, year, release_group, media_type
        """
        if not self.enabled:
            return None

        prompt = f"""分析这个视频文件名，提取元数据。

文件名: {filename}

重要规则：
1. show_name 必须是剧名/电影名，不包含季集信息(SxxExx)、年份、分辨率、来源、编码、发布组
2. 如果文件名格式是 "剧名 SxxExx 集名"，只提取"剧名"作为show_name
3. 集名/副标题不要放在show_name里
4. release_group 是最后的发布组名称（如FLUX、ANi等）

请返回JSON格式。

{{{{
    "show_name": "剧名/电影名（不要包含季集信息、分辨率、来源、编码）",
    "season": "季号数字或null",
    "episode": "集号数字或null",
    "year": "null",
    "release_group": "发布组名称",
    "media_type": "tv"
}}}}

示例：
- "Fallout S02E04 The the Snow 1080p AMZN WEB-DL DDP5 Atmos H 264-FLUX.mkv" → {{"show_name": "Fallout", "season": "2", "episode": "4", "release_group": "FLUX"}}
- "www.UIndex.org - Fallout S02E04 The the Snow 1080p AMZN WEB-DL-FLUX.mkv" → {{"show_name": "Fallout", "season": "2", "episode": "4", "release_group": "FLUX"}}
- "[Furretar] 空之境界 俯瞰风景.mkv" → {{"show_name": "空之境界", "season": "1", "episode": "1"}}
- "[Bird] Ganzo! Bandori-chan - 14.mkv" → {{"show_name": "Ganzo Bandori-chan", "season": "1", "episode": "14"}}

只返回JSON，不要其他内容。"""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个视频文件元数据提取专家，擅长从各种格式的文件名中提取信息。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "top_p": 0.9,
        }

        try:
            logger.info(f"LLMTranslator: Parsing filename: {filename}")
            response = requests.post(
                self.api_url, headers=headers, json=payload, timeout=30
            )
            response.raise_for_status()

            result = response.json()
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"].strip()

                # 尝试解析 JSON
                try:
                    # 清理可能存在的 markdown 代码块标记
                    content = content.replace("```json", "").replace("```", "").strip()
                    metadata = json.loads(content)

                    # 确保所有字段都存在
                    required_fields = [
                        "show_name",
                        "season",
                        "episode",
                        "year",
                        "release_group",
                        "media_type",
                        "original_language",
                    ]
                    for field in required_fields:
                        if field not in metadata:
                            metadata[field] = None

                    logger.info(
                        f"LLMParser: Successfully parsed: show_name={metadata.get('show_name')}"
                    )
                    return metadata
                except json.JSONDecodeError as e:
                    logger.error(f"LLMTranslator: Failed to parse JSON response: {e}")
                    logger.debug(f"Raw response: {content}")
                    return None
            else:
                logger.error(f"LLMTranslator: Unexpected response format: {result}")
                return None
        except requests.exceptions.Timeout:
            logger.error("LLMTranslator: Parse request timeout")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"LLMTranslator: Parse request failed: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"LLMTranslator: JSON decode error: {e}")
            return None
        except Exception as e:
            logger.error(f"LLMTranslator: Translation failed: {e}")
            return None
