#!/usr/bin/env python3
"""Simple debug script for episode extraction."""
import re

name_only = 'The Office Season 3 Episode 22'

patterns = [
    (r'(?P<show_name>.*?)\s*Season\s*(?P<season>\d+)', 'Season'),
    (r'(?P<show_name>.*?)\s*Episode\s*(?P<episode>\d+)', 'Episode'),
]

metadata = {'season': None, 'episode': None}

for pattern, name in patterns:
    match = re.search(pattern, name_only, re.IGNORECASE)
    if match:
        print(f'{name} pattern matched: {match.groupdict()}')
        for key, value in match.groupdict().items():
            if value:
                # Only set if not already set
                if not metadata.get(key):
                    metadata[key] = value
                    print(f'  Set metadata[{key}] = {value}')
                else:
                    print(f'  Skipped: metadata[{key}] already = {metadata[key]}')

print(f'Result: season={metadata["season"]}, episode={metadata["episode"]}')
