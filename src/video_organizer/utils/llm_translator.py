import logging
import requests
import json
from typing import List, Union, Optional

logger = logging.getLogger(__name__)

class LLMTranslator:
    """
    LLM translator using Zhipu AI (BigModel) API.
    """
    
    def __init__(self, api_key: str, api_url: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions", model: str = "GLM-4.5-Flash"):
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.enabled = bool(api_key)
        
    def translate_video_name(self, text: Union[str, List[str]], target_language: str = "Chinese") -> Union[str, List[str], None]:
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
        target_lang_str = "中文名" if target_language.lower() in ['chinese', 'zh', 'cn'] else "英文名"
        content = "\n".join([f"{t}（这是一个视频名，请直接翻译成{target_lang_str}返回）" for t in texts])
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个视频名翻译专家。"
                },
                {
                    "role": "user",
                    "content": content
                }
            ],
            "temperature": 0.6,
            "top_p": 0.95
        }
        
        try:
            logger.info(f"LLMTranslator: Translating {len(texts)} video names...")
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if "choices" in result and len(result["choices"]) > 0:
                translated_content = result["choices"][0]["message"]["content"].strip()
                
                # 如果是多行返回（对应多个视频名），则拆分
                translated_lines = [line.strip() for line in translated_content.split('\n') if line.strip()]
                
                if isinstance(text, str):
                    return translated_lines[0] if translated_lines else translated_content
                return translated_lines
                
            return None
        except Exception as e:
            logger.error(f"LLMTranslator: Translation failed: {e}")
            return None
