#!/usr/bin/env python3
"""配置文件"""

import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 阿里百炼配置
BAILIAN_API_KEY = os.getenv("BAILIAN_API_KEY", "")
BAILIAN_MODEL = os.getenv("BAILIAN_MODEL", "qwen-plus")
BAILIAN_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"

# 飞书配置
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_USER_ID = os.getenv("FEISHU_USER_ID", "")

# 数据源配置
HN_API_URL = "https://hacker-news.firebaseio.com/v0"
PH_RSS_URL = "https://www.producthunt.com/rss"

# 本地配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")

# 创建目录
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# 调试模式
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
