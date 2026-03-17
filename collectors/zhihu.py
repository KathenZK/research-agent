#!/usr/bin/env python3
"""知乎痛点采集器 -- 搜索"有没有什么工具"类高需求问题和热榜痛点话题。"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

PAIN_QUERIES = [
    "有没有什么工具可以",
    "有没有好用的软件",
    "求推荐一个自动化",
    "效率工具推荐",
    "有什么替代方案",
    "太难用了 有没有",
    "手动操作太麻烦",
    "一个人怎么做",
    "独立开发者 工具",
    "SaaS 推荐",
]

HOT_LIST_URL = "https://www.zhihu.com/api/v3/feed/topstory/hot-list"
SEARCH_URL = "https://www.zhihu.com/api/v4/search_v3"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.zhihu.com/",
}

PAIN_KEYWORDS = [
    "工具", "软件", "推荐", "替代", "效率", "自动化",
    "难用", "痛点", "怎么解决", "手动", "重复", "浪费时间",
    "有没有", "求推荐", "一个人", "独立开发", "副业", "赚钱",
]


class ZhihuCollector:
    """从知乎热榜和搜索接口采集痛点信号。"""

    def __init__(self):
        pass

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

    def fetch(self, limit: int = 15) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []

        session = self._session()
        session.headers.update(_HEADERS)
        items: List[Dict[str, Any]] = []
        seen: set[str] = set()

        hot_items = self._fetch_hot_list(session, limit=max(5, limit // 2))
        for item in hot_items:
            if item["id"] not in seen:
                seen.add(item["id"])
                items.append(item)

        queries_to_try = PAIN_QUERIES[:max(3, (limit - len(items)) // 2 + 1)]
        for query in queries_to_try:
            if len(items) >= limit:
                break
            try:
                search_items = self._search(session, query, per_query=3)
            except Exception as exc:
                print(f"Zhihu search error ({query!r}): {exc}")
                continue
            for item in search_items:
                if item["id"] not in seen:
                    seen.add(item["id"])
                    items.append(item)
                if len(items) >= limit:
                    break
            time.sleep(1.0)

        items.sort(key=lambda x: x.get("score", 0), reverse=True)
        return items[:limit]

    def _fetch_hot_list(self, session: requests.Session, limit: int) -> List[Dict[str, Any]]:
        """从知乎热榜抓取带痛点信号的话题。"""
        try:
            resp = session.get(HOT_LIST_URL, params={"limit": 50}, timeout=15)
            if resp.status_code != 200:
                return self._fetch_hot_list_fallback(session, limit)
            data = resp.json()
        except Exception:
            return self._fetch_hot_list_fallback(session, limit)

        items: List[Dict[str, Any]] = []
        hot_data = data.get("data", [])
        for entry in hot_data:
            target = entry.get("target", {}) or {}
            title = target.get("title", "") or entry.get("title", "")
            if not title:
                continue

            combined = title.lower()
            excerpt = (target.get("excerpt", "") or "")[:400]
            combined_full = f"{title} {excerpt}".lower()
            is_pain = any(kw in combined_full for kw in PAIN_KEYWORDS)
            if not is_pain:
                continue

            qid = str(target.get("id", "") or hashlib.md5(title.encode()).hexdigest()[:10])
            heat = entry.get("detail_text", "")
            heat_num = 0
            if heat:
                import re
                m = re.search(r'([\d.]+)\s*万', heat)
                heat_num = int(float(m.group(1)) * 10000) if m else 0

            items.append({
                "id": f"zhihu_hot_{qid}",
                "title": f"[知乎热榜] {title}"[:200],
                "source": "zhihu",
                "url": f"https://www.zhihu.com/question/{qid}" if qid.isdigit() else "",
                "score": heat_num // 1000 + (10 if is_pain else 0),
                "description": (
                    f"热度: {heat} | 摘要: {excerpt[:420]}"
                ),
            })

        return items[:limit]

    def _fetch_hot_list_fallback(self, session: requests.Session, limit: int) -> List[Dict[str, Any]]:
        """备用：通过第三方热榜 API。"""
        try:
            resp = session.get("https://www.tianchenw.com/hot/zhihu/", timeout=10)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception:
            return []

        items: List[Dict[str, Any]] = []
        entries = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(entries, list):
            return []

        for entry in entries[:50]:
            title = entry.get("title", "") or entry.get("name", "")
            if not title:
                continue
            combined = title.lower()
            is_pain = any(kw in combined for kw in PAIN_KEYWORDS)
            if not is_pain:
                continue

            url = entry.get("url", entry.get("link", ""))
            hot = entry.get("hot", 0)
            qid = hashlib.md5(title.encode()).hexdigest()[:10]

            items.append({
                "id": f"zhihu_hot_{qid}",
                "title": f"[知乎热榜] {title}"[:200],
                "source": "zhihu",
                "url": url,
                "score": int(hot) if isinstance(hot, (int, float)) else 5,
                "description": f"热度: {hot}",
            })

        return items[:limit]

    def _search(self, session: requests.Session, query: str, per_query: int = 3) -> List[Dict[str, Any]]:
        """通过知乎搜索接口搜索痛点问题。"""
        try:
            resp = session.get(
                SEARCH_URL,
                params={"t": "general", "q": query, "correction": 1, "offset": 0, "limit": 10},
                timeout=15,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception:
            return []

        items: List[Dict[str, Any]] = []
        results = data.get("data", [])
        for result in results:
            obj = result.get("object", {}) or {}
            question = obj.get("question", obj)
            title = question.get("title", obj.get("title", ""))
            if not title:
                continue

            title = title.replace("<em>", "").replace("</em>", "")
            qid = str(question.get("id", "") or hashlib.md5(title.encode()).hexdigest()[:10])
            excerpt = (obj.get("excerpt", "") or obj.get("content", "") or "")[:400]
            excerpt = excerpt.replace("<em>", "").replace("</em>", "")
            follower_count = question.get("follower_count", 0) or 0
            answer_count = question.get("answer_count", 0) or 0

            items.append({
                "id": f"zhihu_search_{qid}",
                "title": f"[知乎搜索] {title}"[:200],
                "source": "zhihu",
                "url": f"https://www.zhihu.com/question/{qid}" if qid.isdigit() else "",
                "score": follower_count + answer_count,
                "description": (
                    f"关注: {follower_count} | 回答: {answer_count} | "
                    f"搜索词: {query} | 摘要: {excerpt[:350]}"
                ),
            })

        return items[:per_query]
