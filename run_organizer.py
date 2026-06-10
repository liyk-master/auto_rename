import sys
import os

# Ensure the src directory is in the path
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

# 默认启用 Web + 监控模式（端口 8080）
# 用户可通过命令行参数覆盖此行为
if len(sys.argv) <= 1:
    sys.argv.append("--web")

from src.video_organizer.main import main

if __name__ == "__main__":
    main()
