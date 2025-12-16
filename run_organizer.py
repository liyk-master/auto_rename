import sys
import os

# Ensure the src directory is in the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.video_organizer.main import main

if __name__ == "__main__":
    main()
