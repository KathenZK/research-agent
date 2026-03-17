#!/usr/bin/env python3
"""少数派（sspai.com）痛点采集器 -- 通过 RSS 抓取效率工具评测和吐槽类文章。"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import feedparser
except ImportError:
    feedparser = None  # type: ignore[misc,assignment]

SSPAI_RSS = "https://sspai.com/feed"

PAIN_KEYWORDS = [
    "替代", "痛点", "难用", "效率", "自动化", "工具",
    "推荐", "对比", "不好用", "缺点", "问题", "吐槽",
    "解决", "需求", "手动", "麻烦", "流程", "选择",
    "生产力", "工作流", "省时", "方案", "一人", "独立开发",
    "副业", "赚钱", "SaaS", "开源替代", "免费替代",
]


class SspaiCollector:
    """从少数派 RSS 抓取效率工具、工作流相关的痛点和需求文章。"""

    def __init__(self):
        self.headers = {
            "User-Agent": "ResearchAgent/2.0 (sspai-collector)",
        }

    @staticmethod
    def _session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=2, connect=2, read=2, backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def fetch(self, limit: int = 10) -> List[Dict[str, Any]]:
        if limit <= 0 or feedparser is None:
            return []

        session = self._session()
        session.headers.update(self.headers)

        try:
            resp = session.get(SSPAI_RSS, timeout=15)
            if resp.status_code != 200:
                print(f"Sspai RSS error: HTTP {resp.status_code}")
                return []
            feed = feedparser.parse(resp.text)
        except Exception as exc:
            print(f"Sspai RSS error: {exc}")
            return []

        items: List[Dict[str, Any]] = []
        for entry in feed.get("entries", []):
            title = entry.get("title", "")
            if not title:
                continue

            link = entry.get("link", "")
            summary = entry.get("summary", "") or entry.get("description", "") or ""
            summary_clean = re.sub(r'<[^>]+>', '', summary)[:500]
            combined = f"{title} {summary_clean}".lower()

            is_pain = any(kw in combined for kw in PAIN_KEYWORDS)
            if not is_pain:
                continue

            entry_id = hashlib.md5(f"{title}{link}".encode()).hexdigest()[:10]
            items.append({
                "id": f"sspai_{entry_id}",
                "title": f"[少数派] {title}"[:200],
                "source": "sspai",
                "url": link,
                "score": 5 + (3 if any(kw in combined for kw in ["替代", "对比", "推荐", "痛点"]) else 0),
                "description": f"来源: 少数派 RSS | 摘要: {summary_clean[:420]}",
            })

            if len(items) >= limit:
                break

        return items[:limit]
