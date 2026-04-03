import logging
import requests
import json
import random
import re
from typing import List, Union, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class LoadBalanceStrategy(Enum):
    """负载均衡策略"""
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    FAILOVER = "failover"
    WEIGHTED = "weighted"


@dataclass
class LLMProvider:
    """LLM Provider配置"""
    name: str
    api_key: str
    api_url: str
    model: str
    weight: int = 1
    response_format: str = "openai"
    response_path: str = "choices[0].message.content"
    enabled: bool = True
    timeout: int = 30
    max_retries: int = 2
    
    def __post_init__(self):
        if not self.api_key:
            self.enabled = False


class ResponseParser:
    """响应解析器，支持多种API格式"""
    
    @staticmethod
    def parse(json_response: dict, path: str) -> Optional[str]:
        """
        使用路径从JSON响应中提取内容
        
        Args:
            json_response: API返回的JSON响应
            path: JSONPath风格的路径，如 "choices[0].message.content"
        
        Returns:
            提取的内容字符串，失败返回None
        """
        try:
            # 将路径转换为键列表
            # "choices[0].message.content" -> ["choices", "0", "message", "content"]
            keys = []
            # 先按.分割
            parts = path.split(".")
            for part in parts:
                # 处理数组索引
                if "[" in part:
                    # "choices[0]" -> "choices", "0"
                    match = re.match(r"(\w+)\[(\d+)\]", part)
                    if match:
                        keys.append(match.group(1))
                        keys.append(match.group(2))
                    else:
                        keys.append(part)
                else:
                    keys.append(part)
            
            # 遍历路径提取值
            result = json_response
            for key in keys:
                if key.isdigit():
                    result = result[int(key)]
                elif isinstance(result, dict):
                    result = result.get(key)
                else:
                    return None
                if result is None:
                    return None
            
            return str(result).strip() if result else None
        except Exception as e:
            logger.error(f"ResponseParser: Failed to parse path '{path}': {e}")
            return None


class LLMTranslator:
    """
    多Provider LLM翻译器
    支持负载均衡和故障转移
    """
    
    # 预定义的响应格式模板
    RESPONSE_TEMPLATES = {
        "openai": "choices[0].message.content",
        "ollama": "message.content",
        "anthropic": "content[0].text",
        "deepseek": "choices[0].message.content",
        "zhipu": "choices[0].message.content",
    }
    
    def __init__(
        self,
        api_key: str = "",
        api_url: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        model: str = "GLM-4.5-Flash",
        providers: Optional[List[Dict[str, Any]]] = None,
        strategy: str = "round_robin",
        config: Optional[Dict] = None,
    ):
        """
        初始化LLM翻译器
        
        Args:
            api_key: 单Provider时的API密钥（兼容旧配置）
            api_url: 单Provider时的API URL
            model: 单Provider时的模型名称
            providers: 多Provider配置列表
            strategy: 负载均衡策略 (round_robin/random/failover/weighted)
            config: 完整配置对象（用于提取providers配置）
        """
        self.providers: List[LLMProvider] = []
        self.strategy = LoadBalanceStrategy(strategy)
        self._current_index = 0  # 用于round_robin
        self._enabled = False
        
        # 优先使用providers配置
        if providers:
            self._init_providers(providers)
        elif config and isinstance(config, dict):
            # 从config中提取providers配置
            llm_config = config.get("llm_translation", {})
            provider_configs = llm_config.get("providers", [])
            if provider_configs:
                self._init_providers(provider_configs)
                strategy_config = llm_config.get("strategy", "round_robin")
                self.strategy = LoadBalanceStrategy(strategy_config)
            elif llm_config.get("api_key") or api_key:
                # 兼容旧的单Provider配置
                self._init_single_provider(
                    api_key or llm_config.get("api_key", ""),
                    api_url or llm_config.get("api_url", api_url),
                    model or llm_config.get("model", model)
                )
        elif api_key:
            # 兼容旧的单Provider初始化方式
            self._init_single_provider(api_key, api_url, model)
        
        # 检查是否有可用的Provider
        self._enabled = any(p.enabled for p in self.providers)
        
        if self._enabled:
            logger.info(f"LLMTranslator: 已初始化 {len(self.providers)} 个Provider, 策略={self.strategy.value}")
        else:
            logger.warning("LLMTranslator: 没有可用的Provider")
    
    def _init_providers(self, provider_configs: List[Dict[str, Any]]):
        """初始化多个Provider"""
        for i, cfg in enumerate(provider_configs):
            # 处理response_format，自动填充response_path
            response_format = cfg.get("response_format", "openai")
            response_path = cfg.get("response_path")
            
            if not response_path and response_format in self.RESPONSE_TEMPLATES:
                response_path = self.RESPONSE_TEMPLATES[response_format]
            elif not response_path:
                response_path = "choices[0].message.content"
            
            provider = LLMProvider(
                name=cfg.get("name", f"provider_{i}"),
                api_key=cfg.get("api_key", ""),
                api_url=cfg.get("api_url", ""),
                model=cfg.get("model", ""),
                weight=cfg.get("weight", 1),
                response_format=response_format,
                response_path=response_path,
                enabled=cfg.get("enabled", True),
                timeout=cfg.get("timeout", 30),
                max_retries=cfg.get("max_retries", 2),
            )
            
            if provider.enabled and provider.api_key and provider.api_url:
                self.providers.append(provider)
                logger.debug(f"LLMTranslator: 添加Provider '{provider.name}' (model={provider.model})")
            else:
                logger.debug(f"LLMTranslator: 跳过Provider '{provider.name}' (enabled={provider.enabled})")
    
    def _init_single_provider(self, api_key: str, api_url: str, model: str):
        """初始化单个Provider（兼容旧配置）"""
        provider = LLMProvider(
            name="default",
            api_key=api_key,
            api_url=api_url,
            model=model,
        )
        self.providers.append(provider)
        logger.info(f"LLMTranslator: 使用单Provider配置 (model={model})")
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    def _select_provider(self) -> Optional[LLMProvider]:
        """根据负载均衡策略选择Provider"""
        available_providers = [p for p in self.providers if p.enabled]
        if not available_providers:
            return None
        
        if self.strategy == LoadBalanceStrategy.ROUND_ROBIN:
            provider = available_providers[self._current_index % len(available_providers)]
            self._current_index += 1
            return provider
        
        elif self.strategy == LoadBalanceStrategy.RANDOM:
            return random.choice(available_providers)
        
        elif self.strategy == LoadBalanceStrategy.FAILOVER:
            # 总是返回第一个可用的Provider，失败时调用_next_provider
            return available_providers[0]
        
        elif self.strategy == LoadBalanceStrategy.WEIGHTED:
            # 根据权重随机选择
            total_weight = sum(p.weight for p in available_providers)
            r = random.uniform(0, total_weight)
            cumulative = 0
            for provider in available_providers:
                cumulative += provider.weight
                if r <= cumulative:
                    return provider
            return available_providers[-1]
        
        return available_providers[0]
    
    def _call_api(
        self,
        provider: LLMProvider,
        messages: List[Dict],
        temperature: float = 0.6,
        top_p: float = 0.95,
    ) -> Optional[str]:
        """
        调用单个Provider的API
        
        Args:
            provider: Provider配置
            messages: 消息列表
            temperature: 温度参数
            top_p: top_p参数
        
        Returns:
            API响应内容，失败返回None
        """
        headers = {
            "Content-Type": "application/json",
        }
        if provider.api_key:
            headers["Authorization"] = f"Bearer {provider.api_key}"
        
        payload = {
            "model": provider.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
        }
        
        for attempt in range(provider.max_retries):
            try:
                logger.debug(f"LLMTranslator: 调用Provider '{provider.name}' (attempt={attempt+1})")
                response = requests.post(
                    provider.api_url,
                    headers=headers,
                    json=payload,
                    timeout=provider.timeout,
                )
                response.raise_for_status()
                
                result = response.json()
                content = ResponseParser.parse(result, provider.response_path)
                
                if content:
                    logger.debug(f"LLMTranslator: Provider '{provider.name}' 返回成功")
                    return content
                else:
                    logger.warning(f"LLMTranslator: Provider '{provider.name}' 返回格式异常: {result}")
                    
            except requests.exceptions.Timeout:
                logger.warning(f"LLMTranslator: Provider '{provider.name}' 超时 (attempt={attempt+1})")
            except requests.exceptions.RequestException as e:
                logger.warning(f"LLMTranslator: Provider '{provider.name}' 请求失败: {e}")
            except Exception as e:
                logger.error(f"LLMTranslator: Provider '{provider.name}' 未知错误: {e}")
        
        return None
    
    def _call_with_failover(
        self,
        messages: List[Dict],
        temperature: float = 0.6,
        top_p: float = 0.95,
    ) -> Optional[str]:
        """带故障转移的API调用"""
        tried_providers = set()
        
        for _ in range(len(self.providers)):
            provider = self._select_provider()
            if not provider or provider.name in tried_providers:
                continue
            
            tried_providers.add(provider.name)
            content = self._call_api(provider, messages, temperature, top_p)
            
            if content:
                return content
        
        logger.error("LLMTranslator: 所有Provider都失败")
        return None
    
    def translate_video_name(
        self,
        text: Union[str, List[str]],
        target_language: str = "Chinese"
    ) -> Union[str, List[str], None]:
        """
        翻译视频名称
        
        Args:
            text: 单个视频名或视频名列表（最多3个）
            target_language: 目标语言 (Chinese, English)
        
        Returns:
            翻译后的字符串或列表，失败返回None
        """
        if not self._enabled:
            return None
        
        texts = [text] if isinstance(text, str) else text
        if not texts:
            return None
        
        if len(texts) > 3:
            logger.warning("LLMTranslator: 批量翻译超过3个，截断")
            texts = texts[:3]
        
        target_lang_str = (
            "中文名" if target_language.lower() in ["chinese", "zh", "cn"] else "英文名"
        )
        content = "\n".join(
            [f"{t}（这是一个视频名，请直接翻译成{target_lang_str}返回）" for t in texts]
        )
        
        messages = [
            {"role": "system", "content": "你是一个视频名翻译专家。"},
            {"role": "user", "content": content},
        ]
        
        logger.info(f"LLMTranslator: 翻译 {len(texts)} 个视频名...")
        translated_content = self._call_with_failover(messages, temperature=0.6, top_p=0.95)
        
        if not translated_content:
            return None
        
        translated_lines = [
            line.strip() for line in translated_content.split("\n") if line.strip()
        ]
        
        if isinstance(text, str):
            return translated_lines[0] if translated_lines else translated_content
        return translated_lines
    
    def parse_filename(self, filename: str) -> Optional[dict]:
        """
        使用LLM解析视频文件名，提取元数据
        
        Args:
            filename: 视频文件名
        
        Returns:
            包含元数据的字典，失败返回None
        """
        if not self._enabled:
            return None
        
        prompt = f"""分析这个视频文件名，提取元数据。

文件名: {filename}

重要规则：
1. show_name 必须是剧名/电影名，不包含季集信息(SxxExx)、年份、分辨率、来源、编码、发布组
2. 如果文件名格式是 "剧名 SxxExx 集名"，只提取"剧名"作为show_name
3. 集名/副标题不要放在show_name里
4. release_group 是最后的发布组名称（如FLUX、ANi等）

请返回JSON格式。

{{
    "show_name": "剧名/电影名（不要包含季集信息、分辨率、来源、编码）",
    "season": "季号数字或null",
    "episode": "集号数字或null",
    "year": "null",
    "release_group": "发布组名称",
    "media_type": "tv"
}}

示例：
- "Fallout S02E04 The the Snow 1080p AMZN WEB-DL DDP5 Atmos H 264-FLUX.mkv" → {{"show_name": "Fallout", "season": "2", "episode": "4", "release_group": "FLUX"}}
- "www.UIndex.org - Fallout S02E04 The the Snow 1080p AMZN WEB-DL-FLUX.mkv" → {{"show_name": "Fallout", "season": "2", "episode": "4", "release_group": "FLUX"}}
- "[Furretar] 空之境界 俯瞰风景.mkv" → {{"show_name": "空之境界", "season": "1", "episode": "1"}}
- "[Bird] Ganzo! Bandori-chan - 14.mkv" → {{"show_name": "Ganzo Bandori-chan", "season": "1", "episode": "14"}}

只返回JSON，不要其他内容。"""

        messages = [
            {"role": "system", "content": "你是一个视频文件元数据提取专家，擅长从各种格式的文件名中提取信息。"},
            {"role": "user", "content": prompt},
        ]
        
        logger.info(f"LLMTranslator: 解析文件名: {filename}")
        content = self._call_with_failover(messages, temperature=0.3, top_p=0.9)
        
        if not content:
            return None
        
        try:
            # 清理markdown代码块标记
            content = content.replace("```json", "").replace("```", "").strip()
            metadata = json.loads(content)
            
            # 确保所有字段存在
            required_fields = [
                "show_name", "season", "episode", "year",
                "release_group", "media_type", "original_language",
            ]
            for field in required_fields:
                if field not in metadata:
                    metadata[field] = None
            
            logger.info(f"LLMTranslator: 解析成功: show_name={metadata.get('show_name')}")
            return metadata
            
        except json.JSONDecodeError as e:
            logger.error(f"LLMTranslator: JSON解析失败: {e}")
            logger.debug(f"原始响应: {content}")
            return None
