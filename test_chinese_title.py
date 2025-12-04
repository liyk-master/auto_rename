#!/usr/bin/env python3
"""
Test script to verify that Chinese titles are correctly used in file naming.
"""

import sys
import os
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from src.video_organizer.core.renamer import VideoRenamer
from src.video_organizer.core.file_mover import FileMover


def test_chinese_title_naming():
    """Test that Chinese titles are correctly used in file naming."""
    # Replace with your actual TMDB API key
    tmdb_api_key = "your_tmdb_api_key"  # Make sure to replace this with a valid key
    
    # Create a mock file path with English title
    mock_file_path = Path("/mnt/media/test/The Immortal Ascension S01E07 - 第 7 集 - 2160p WEB-DL HQ H265 AAC.strm")
    
    # Initialize the renamer
    renamer = VideoRenamer(tmdb_api_key)
    
    # Extract metadata
    print("=== Extracting Metadata ===")
    metadata = renamer.extract_metadata(mock_file_path)
    
    # Print extracted metadata
    print(f"Original filename: {mock_file_path.name}")
    print(f"Extracted show_name: {metadata.get('show_name')}")
    print(f"Year: {metadata.get('year')}")
    print(f"TMDB ID: {metadata.get('tmdb_id')}")
    print(f"Quality tags: {metadata.get('quality_tags')}")
    print(f"Media type: {metadata.get('media_type')}")
    
    # Generate new path
    print("\n=== Generating New Path ===")
    new_path = renamer.generate_new_path(metadata, original_path=mock_file_path)
    print(f"Generated path: {new_path}")
    
    # Check if Chinese title is used
    print("\n=== Verification ===")
    if "凡人修仙传" in str(new_path):
        print("✅ PASS: Chinese title is correctly used in the generated path")
    else:
        print("❌ FAIL: Chinese title is not used in the generated path")
    
    # Check if quality tags are preserved
    expected_quality_tags = "2160p.WEB-DL.H265.AAC"  # Adjust based on actual extraction
    if expected_quality_tags in str(new_path):
        print("✅ PASS: Quality tags are correctly preserved")
    else:
        print("❌ FAIL: Quality tags are not preserved correctly")
    
    return metadata, new_path


if __name__ == "__main__":
    test_chinese_title_naming()
