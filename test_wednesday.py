#!/usr/bin/env python3
"""
Test script to verify that "星期三 S01E01.mp4" is correctly identified as "星期三" instead of "星期三的情事".
"""

import sys
import os
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from src.video_organizer.core.renamer import VideoRenamer


def mock_enrich_with_tmdb(self, metadata: dict) -> dict:
    """Mock TMDB enrichment to simulate Chinese title acquisition."""
    # Save original quality tags
    original_quality_tags = metadata.get('quality_tags', '')
    
    # Mock response for "星期三" -> "星期三"
    if metadata.get('show_name', '').strip() == '星期三':
        # Direct match, this is the correct show
        metadata['show_name'] = '星期三'
        metadata['year'] = '2022'
        metadata['tmdb_id'] = '204889'
        metadata['media_type'] = 'tv'
        metadata['original_show_name'] = 'Wednesday'
        metadata['quality_tags'] = original_quality_tags
    
    # Mock response for "星期三的情事" -> "星期三的情事"
    elif metadata.get('show_name', '').strip() == '星期三的情事':
        metadata['show_name'] = '星期三的情事'
        metadata['year'] = '2023'
        metadata['tmdb_id'] = '123456'  # Dummy ID for testing
        metadata['media_type'] = 'tv'
        metadata['original_show_name'] = 'Wednesday Affair'
        metadata['quality_tags'] = original_quality_tags
    
    return metadata


# Monkey patch the _enrich_with_tmdb method to use our mock
VideoRenamer._enrich_with_tmdb = mock_enrich_with_tmdb


def test_wednesday_identification():
    """Test that "星期三 S01E01.mp4" is correctly identified as "星期三"."""
    # Initialize the renamer with a dummy API key
    renamer = VideoRenamer("dummy_key")
    
    # Test case 1: Simple filename "星期三 S01E01.mp4"
    print("=== Test Case 1: 星期三 S01E01.mp4 ===")
    file_path1 = Path("/mnt/media/test/星期三 S01E01.mp4")
    metadata1 = renamer.extract_metadata(file_path1)
    new_path1 = renamer.generate_new_path(metadata1, original_path=file_path1)
    
    print(f"Original filename: {file_path1.name}")
    print(f"Extracted show_name: {metadata1.get('show_name')}")
    print(f"Generated path: {new_path1}")
    
    if metadata1.get('show_name') == '星期三':
        print("✅ PASS: Correctly identified as '星期三'")
    else:
        print(f"❌ FAIL: Incorrectly identified as '{metadata1.get('show_name')}'")
    
    # Test case 2: Filename with quality tags "星期三 S01E01 1080p.WEB-DL.H264.mp4"
    print("\n=== Test Case 2: 星期三 S01E01 1080p.WEB-DL.H264.mp4 ===")
    file_path2 = Path("/mnt/media/test/星期三 S01E01 1080p.WEB-DL.H264.mp4")
    metadata2 = renamer.extract_metadata(file_path2)
    new_path2 = renamer.generate_new_path(metadata2, original_path=file_path2)
    
    print(f"Original filename: {file_path2.name}")
    print(f"Extracted show_name: {metadata2.get('show_name')}")
    print(f"Generated path: {new_path2}")
    
    if metadata2.get('show_name') == '星期三':
        print("✅ PASS: Correctly identified as '星期三'")
    else:
        print(f"❌ FAIL: Incorrectly identified as '{metadata2.get('show_name')}'")
    
    # Test case 3: Compare with "星期三的情事" to ensure it's handled differently
    print("\n=== Test Case 3: 星期三的情事 S01E01.mp4 ===")
    file_path3 = Path("/mnt/media/test/星期三的情事 S01E01.mp4")
    metadata3 = renamer.extract_metadata(file_path3)
    new_path3 = renamer.generate_new_path(metadata3, original_path=file_path3)
    
    print(f"Original filename: {file_path3.name}")
    print(f"Extracted show_name: {metadata3.get('show_name')}")
    print(f"Generated path: {new_path3}")
    
    if metadata3.get('show_name') == '星期三的情事':
        print("✅ PASS: Correctly identified as '星期三的情事'")
    else:
        print(f"❌ FAIL: Incorrectly identified as '{metadata3.get('show_name')}'")
    
    # Summary
    print("\n=== SUMMARY ===")
    print(f"Test Case 1: {'✅ PASS' if metadata1.get('show_name') == '星期三' else '❌ FAIL'}")
    print(f"Test Case 2: {'✅ PASS' if metadata2.get('show_name') == '星期三' else '❌ FAIL'}")
    print(f"Test Case 3: {'✅ PASS' if metadata3.get('show_name') == '星期三的情事' else '❌ FAIL'}")
    
    if metadata1.get('show_name') == '星期三' and metadata2.get('show_name') == '星期三' and metadata3.get('show_name') == '星期三的情事':
        print("\n🎉 ALL TESTS PASSED! The system correctly distinguishes between '星期三' and '星期三的情事'.")
    else:
        print("\n⚠️  SOME TESTS FAILED! The system may still be misidentifying shows.")


if __name__ == "__main__":
    test_wednesday_identification()
