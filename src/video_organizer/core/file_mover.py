"""
Module for safely moving files to organized locations.
"""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class FileMover:
    """Handles moving files to organized directory structures."""

    def __init__(self, base_path: Path):
        self.base_path = base_path

    def move_file(self, source_path: Path, relative_dest_path: Path) -> Path:
        """
        Move a file to a new organized location.

        Args:
            source_path: Path to the source file
            relative_dest_path: Relative path for the destination

        Returns:
            Path to the moved file
        """
        # 确保源文件存在
        if not source_path.exists():
            logger.error(f"源文件不存在: {source_path}")
            raise FileNotFoundError(f"源文件不存在: {source_path}")

        # 确保源文件是文件而不是目录
        if not source_path.is_file():
            logger.error(f"源路径不是文件: {source_path}")
            raise IsADirectoryError(f"源路径不是文件: {source_path}")

        # 规范化源文件路径，确保路径格式正确
        source_path = source_path.resolve()
        logger.info(f"准备移动文件: {source_path}")

        # Create the full destination path
        dest_path = self.base_path / relative_dest_path

        # Ensure the destination directory exists
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Handle filename conflicts
        final_dest_path = self._handle_conflicts(dest_path)

        # 重试机制：尝试多次移动文件，防止临时文件锁定
        max_retries = 3
        retry_delay = 1  # 秒

        for attempt in range(max_retries):
            try:
                shutil.move(str(source_path), str(final_dest_path))
                logger.info(
                    f"Moved {source_path} to {final_dest_path} (尝试 {attempt + 1}/{max_retries})"
                )
                return final_dest_path
            except Exception as e:
                logger.warning(
                    f"第 {attempt + 1}/{max_retries} 次尝试移动文件失败: {e}"
                )
                if attempt < max_retries - 1:
                    import time

                    time.sleep(retry_delay)
                else:
                    logger.error(
                        f"所有尝试都失败了，无法移动文件 {source_path} to {final_dest_path}: {e}"
                    )
                    raise

    def _handle_conflicts(self, path: Path) -> Path:
        """
        Handle filename conflicts by raising an error when file exists.

        Args:
            path: Original proposed path

        Returns:
            Original path if no conflict

        Raises:
            FileExistsError: When file already exists
        """
        if path.exists():
            logger.warning(f"文件已存在，无法覆盖: {path}")
            # 不自动生成新名称，而是提醒冲突
            raise FileExistsError(f"文件已存在，无法覆盖: {path}")

        # If file doesn't exist, return the original path
        return path
