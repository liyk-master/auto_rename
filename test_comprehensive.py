#!/usr/bin/env python3
"""
Comprehensive test script to verify Chinese title handling and quality tag preservation.
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
    
    # Mock response for "The Immortal Ascension" -> "凡人修仙传"
    if metadata.get('show_name', '').lower() == 'the immortal ascension':
        metadata['show_name'] = '凡人修仙传'
        metadata['year'] = '2025'
        metadata['tmdb_id'] = '243224'
        metadata['media_type'] = 'tv'
        metadata['original_show_name'] = 'The Immortal Ascension'
        metadata['quality_tags'] = original_quality_tags  # Preserve original quality tags
    
    # Mock response for "Wednesday" -> "星期三"
    elif metadata.get('show_name', '').lower() == 'wednesday':
        metadata['show_name'] = '星期三'
        metadata['year'] = '2022'
        metadata['tmdb_id'] = '204889'
        metadata['media_type'] = 'tv'
        metadata['original_show_name'] = 'Wednesday'
        metadata['quality_tags'] = original_quality_tags  # Preserve original quality tags
    
    return metadata


# Monkey patch the _enrich_with_tmdb method to use our mock
VideoRenamer._enrich_with_tmdb = mock_enrich_with_tmdb


def test_scenarios():
    """Test various scenarios for Chinese title handling."""
    # Initialize the renamer with a dummy API key
    renamer = VideoRenamer("dummy_key")
    
    # Test scenarios
    test_cases = [
        {
            "name": "English title with Chinese episode info",
            "file_path": Path("/mnt/media/test/The Immortal Ascension S01E07 - 第 7 集 - 2160p WEB-DL HQ H265 AAC.strm"),
            "expected_title": "凡人修仙传"
        },
        {
            "name": "English title only",
            "file_path": Path("/mnt/media/test/Wednesday S01E01 - Pilot - 1080p WEB-DL H264 AAC.strm"),
            "expected_title": "星期三"
        },
        {
            "name": "Chinese title with quality tags",
            "file_path": Path("/mnt/media/test/凡人修仙传 S01E01 - 第 1 集 - 4K HDR WEB-DL H265 DDP5.1.strm"),
            "expected_title": "凡人修仙传"
        },
        {
            "name": "Simple filename with resolution",
            "file_path": Path("/mnt/media/test/星期三 S01E01 2160p.strm"),
            "expected_title": "星期三"
        }
    ]
    
    for test_case in test_cases:
        print(f"\n{'='*60}")
        print(f"Test: {test_case['name']}")
        print(f"File: {test_case['file_path']}")
        print(f"Expected Chinese Title: {test_case['expected_title']}")
        print(f"{'='*60}")
        
        try:
            # Extract metadata
            metadata = renamer.extract_metadata(test_case['file_path'])
            
            # Generate new path
            new_path = renamer.generate_new_path(metadata, original_path=test_case['file_path'])
            
            # Print results
            print(f"✓ Original Filename: {test_case['file_path'].name}")
            print(f"✓ Extracted Show Name: {metadata.get('show_name')}")
            print(f"✓ Quality Tags: {metadata.get('quality_tags')}")
            print(f"✓ Year: {metadata.get('year')}")
            print(f"✓ TMDB ID: {metadata.get('tmdb_id')}")
            print(f"✓ Media Type: {metadata.get('media_type')}")
            print(f"✓ Generated Path: {new_path}")
            
            # Verify results
            if test_case['expected_title'] in str(new_path):
                print(f"✅ PASS: Chinese title '{test_case['expected_title']}' is correctly used")
            else:
                print(f"❌ FAIL: Chinese title '{test_case['expected_title']}' is not used")
            
            # Check quality tags preservation
            if metadata.get('quality_tags') in str(new_path):
                print(f"✅ PASS: Quality tags are preserved")
            else:
                print(f"❌ FAIL: Quality tags are not preserved")
            
            # Check if year is added when available
            if metadata.get('year') and metadata.get('year') in str(new_path):
                print(f"✅ PASS: Year {metadata.get('year')} is correctly added")
            
        except Exception as e:
            print(f"❌ ERROR: {e}")
    
    print(f"\n{'='*60}")
    print("All tests completed!")
    print(f"{'='*60}")


if __name__ == "__main__":
    test_scenarios()
