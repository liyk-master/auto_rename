"""
AI 辅助解析 — 使用 LLM 从文件名提取元数据
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


def extract_with_ai(filename: str, existing_metadata: Dict) -> Dict:
    """
    Use AI service to extract metadata from filename.
    """
    logger.warning("AI extraction not implemented, using regex results only")
    return existing_metadata