from setuptools import setup, find_packages
import os

# 读取README.md作为长描述
try:
    with open('README.md', 'r', encoding='utf-8') as f:
        long_description = f.read()
except Exception:
    long_description = "自动视频文件重命名和组织工具"

setup(
    name="video-organizer",
    version="1.0.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="一个强大的视频文件自动重命名和组织工具",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/video-organizer",
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    include_package_data=True,
    package_data={
        'video_organizer': ['config.ini'],
    },
    install_requires=[
        'requests>=2.28.0',
        'watchdog>=3.0.0',
    ],
    entry_points={
        'console_scripts': [
            'video-organizer=video_organizer.main:main',
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: Chinese (Simplified)",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Desktop Environment :: File Managers",
        "Topic :: Multimedia :: Video",
        "Topic :: Utilities",
    ],
    python_requires='>=3.8',
)
