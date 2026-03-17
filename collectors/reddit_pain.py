#!/usr/bin/env python3
"""Reddit pain-signal collector -- searches for unmet-need expressions across subreddits."""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class RedditPainCollector:
    """Search Reddit for pain-signal posts: explicit complaints, tool requests, and frustrations."""

    SUBREDDITS = [
        "smallbusiness",
        "webdev",
        "freelance",
        "ecommerce",
        "startups",
        "accounting",
        "SaaS",
        "entrepreneur",
        "sysadmin",
        "devops",
    ]

    PAIN_QUERIES = [
        "I wish there was",
        "looking for a tool",
        "frustrated with",
        "any alternative to",
        "hate using",
        "manual process",
        "wasting time on",
        "is there a way to automate",
        "need a better",
        "sick of",
    ]

    def __init__(self):
        self.headers = {"User-Agent": "ResearchAgent/2.0 (pain-collector)"}

    @staticmethod
    def _session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=1.0,
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
        seen_ids: set[str] = set()

        queries_to_try = self.PAIN_QUERIES[: max(3, limit // 2)]

        for query in queries_to_try:
            if len(items) >= limit:
                break
            try:
                new_items = self._search(session, query, per_query=max(3, limit // len(queries_to_try)))
            except Exception as exc:
                print(f"Reddit pain search error ({query!r}): {exc}")
                continue

            for item in new_items:
                if item["id"] not in seen_ids:
                    seen_ids.add(item["id"])
                    items.append(item)
                if len(items) >= limit:
                    break

            time.sleep(1.5)

        items.sort(key=lambda x: x.get("score", 0), reverse=True)
        return items[:limit]

    def _search(self, session: requests.Session, query: str, per_query: int = 5) -> List[Dict[str, Any]]:
        subreddits_str = "+".join(self.SUBREDDITS)
        url = f"https://www.reddit.com/r/{subreddits_str}/search.json"

        response = session.get(
            url,
            params={
                "q": query,
                "sort": "new",
                "t": "week",
                "restrict_sr": "on",
                "limit": min(per_query * 2, 25),
            },
            timeout=20,
        )

        if response.status_code != 200:
            return []

        data = response.json()
        items: List[Dict[str, Any]] = []

        for post in data.get("data", {}).get("children", []):
            pd = post.get("data", {})
            if pd.get("stickied") or pd.get("is_video") or pd.get("over_18"):
                continue
            title = pd.get("title", "")
            if not title:
                continue

            selftext = (pd.get("selftext") or "")[:600]
            subreddit = pd.get("subreddit", "unknown")
            post_id = pd.get("id", hashlib.md5(title.encode()).hexdigest()[:8])
            score = pd.get("score", 0)
            num_comments = pd.get("num_comments", 0)

            items.append({
                "id": f"reddit_pain_{post_id}",
                "title": f"[Reddit Pain] r/{subreddit}: {title}"[:200],
                "source": "reddit_pain",
                "url": f"https://www.reddit.com{pd.get('permalink', '')}",
                "score": score + num_comments,
                "description": (
                    f"Subreddit: r/{subreddit} | Upvotes: {score} | "
                    f"Comments: {num_comments} | Query: {query} | "
                    f"Post: {selftext[:420]}"
                ),
            })

        return items[:per_query]
