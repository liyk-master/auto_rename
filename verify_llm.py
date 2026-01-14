import logging
import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.video_organizer.utils.llm_translator import LLMTranslator
from src.video_organizer.core.config_loader import load_config

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def verify():
    # 加载配置
    config = load_config("config.ini")
    llm_config = config.get("llm_translation", {})

    if not llm_config.get("api_key"):
        print("❌ 错误: 未在 config.ini 中配置 llm_translation.api_key")
        print("请在 [llm_translation] 节下添加 api_key = 您的密钥")
        return

    translator = LLMTranslator(
        api_key=llm_config["api_key"],
        api_url=llm_config.get("api_url"),
        model=llm_config.get("model"),
    )

    test_cases = [
        "The Daily Life of the Immortal King",
        "Spy x Family",
        ["One Piece", "Naruto", "Bleach"],
    ]

    for case in test_cases:
        print(f"\n--- 测试输入: {case} ---")
        result = translator.translate_video_name(case)
        print(f"翻译结果: {result}")


if __name__ == "__main__":
    verify()
