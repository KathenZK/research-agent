#!/usr/bin/env python3
"""V2EX 痛点采集器 -- 从创意、问与答、程序员等节点抓取需求/吐槽帖。"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

PAIN_NODES = [
    "create",        # 创意 -- 产品 idea 和需求
    "qna",           # 问与答 -- "有没有什么工具…"
    "programmer",    # 程序员 -- 工具链痛点
    "apple",         # Apple -- macOS/iOS 工具需求
    "git",           # Git -- 开发工具痛点
    "devops",        # DevOps -- 运维自动化需求
    "freelance",     # 酷工作（自由） -- 自由职业者需求
    "share",         # 分享发现 -- 用户推荐替代方案
    "autolayout",    # 设计 -- 设计工具需求
]

PAIN_KEYWORDS = [
    "有没有", "推荐", "替代", "难用", "吐槽", "痛点",
    "效率", "自动化", "太慢", "不好用", "求推荐", "有什么好的",
    "怎么解决", "受不了", "能不能", "有没有人做", "想找一个",
    "手动", "重复", "浪费时间", "工具", "需求", "alternative",
]


class V2EXCollector:
    """从 V2EX 痛点相关节点采集帖子。"""

    API_BASE = "https://www.v2ex.com/api/v2"
    API_V1_BASE = "https://www.v2ex.com/api"

    def __init__(self):
        self.headers = {
            "User-Agent": "ResearchAgent/2.0 (v2ex-collector)",
            "Accept": "application/json",
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

    def fetch(self, limit: int = 15) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []

        session = self._session()
        session.headers.update(self.headers)
        items: List[Dict[str, Any]] = []
        seen_ids: set[int] = set()

        per_node = max(3, limit // len(PAIN_NODES) + 1)
        for node in PAIN_NODES:
            if len(items) >= limit:
                break
            try:
                node_items = self._fetch_node(session, node, per_node)
            except Exception as exc:
                print(f"V2EX node {node} error: {exc}")
                continue

            for item in node_items:
                tid = item.get("_tid")
                if tid and tid not in seen_ids:
                    seen_ids.add(tid)
                    items.append(item)
                if len(items) >= limit:
                    break

            time.sleep(0.8)

        items.sort(key=lambda x: x.get("score", 0), reverse=True)
        return items[:limit]

    def _fetch_node(self, session: requests.Session, node_name: str, limit: int) -> List[Dict[str, Any]]:
        url = f"{self.API_V1_BASE}/topics/show.json"
        resp = session.get(url, params={"node_name": node_name}, timeout=15)
        if resp.status_code != 200:
            return []

        raw_topics = resp.json()
        if not isinstance(raw_topics, list):
            return []

        items: List[Dict[str, Any]] = []
        for topic in raw_topics[:limit * 2]:
            title = topic.get("title", "")
            content = topic.get("content", "") or ""
            combined = f"{title} {content}".lower()

            is_pain = any(kw in combined for kw in PAIN_KEYWORDS)
            replies = topic.get("replies", 0) or 0

            if not is_pain and replies < 3:
                continue

            topic_id = topic.get("id", 0)
            node = topic.get("node", {})
            node_label = node.get("title", node_name) if isinstance(node, dict) else node_name
            member = topic.get("member", {})
            author = member.get("username", "unknown") if isinstance(member, dict) else "unknown"

            items.append({
                "id": f"v2ex_{topic_id}",
                "_tid": topic_id,
                "title": f"[V2EX/{node_label}] {title}"[:200],
                "source": "v2ex",
                "url": f"https://www.v2ex.com/t/{topic_id}",
                "score": replies + (5 if is_pain else 0),
                "description": (
                    f"节点: {node_label} | 回复: {replies} | 作者: {author} | "
                    f"内容: {content[:420]}"
                ),
            })

        return items[:limit]
