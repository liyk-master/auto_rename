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
        Handle filename conflicts by appending a number.
        
        Args:
            path: Original proposed path
            
        Returns:
            Path that doesn't conflict with existing files
        """
        if not path.exists():
            return path
            
        # If file exists, find a new name by appending a number
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        
        counter = 1
        while True:
            new_path = parent / f"{stem} ({counter}){suffix}"
            if not new_path.exists():
                return new_path
            counter += 1