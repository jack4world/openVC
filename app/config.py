import logging
import os
from pathlib import Path

VERSION = "v1.4.0"
YEAR = 2025
APP_NAME = "openVC"
AUTHOR = "jack4world"

HELP_URL = "https://github.com/jack4world/openVC"
GITHUB_REPO_URL = "https://github.com/jack4world/openVC"
RELEASE_URL = "https://github.com/jack4world/openVC/releases/latest"
FEEDBACK_URL = "https://github.com/jack4world/openVC/issues"

# 路径
ROOT_PATH = Path(__file__).parent.parent

RESOURCE_PATH = ROOT_PATH / "resource"
APPDATA_PATH = ROOT_PATH / "AppData"
WORK_PATH = ROOT_PATH / "work-dir"


SUBTITLE_STYLE_PATH = RESOURCE_PATH / "subtitle_style"

LOG_PATH = APPDATA_PATH / "logs"
SETTINGS_PATH = APPDATA_PATH / "settings.json"
CACHE_PATH = APPDATA_PATH / "cache"
MODEL_PATH = APPDATA_PATH / "models"

# 日志配置
LOG_LEVEL = logging.INFO
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# 创建路径
for p in [CACHE_PATH, LOG_PATH, WORK_PATH, MODEL_PATH]:
    p.mkdir(parents=True, exist_ok=True)
