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
        # Create the full destination path
        dest_path = self.base_path / relative_dest_path
        
        # Ensure the destination directory exists
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Handle filename conflicts
        final_dest_path = self._handle_conflicts(dest_path)
        
        # Move the file
        try:
            shutil.move(str(source_path), str(final_dest_path))
            logger.info(f"Moved {source_path} to {final_dest_path}")
            return final_dest_path
        except Exception as e:
            logger.error(f"Error moving file {source_path} to {final_dest_path}: {e}")
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