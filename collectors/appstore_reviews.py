#!/usr/bin/env python3
"""App Store reviews collector."""

from __future__ import annotations

import math
from typing import Any, Dict, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class AppStoreReviewsCollector:
    """Collect low-rated App Store reviews from top apps in relevant categories."""

    GENRES = [
        ("business", "6000"),
        ("productivity", "6007"),
        ("developer-tools", "6026"),
        ("finance", "6015"),
        ("health-fitness", "6013"),
    ]

    def __init__(self, storefront: str = "us"):
        self.storefront = storefront

    @staticmethod
    def _session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.8,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def fetch(self, limit: int = 12, per_app_reviews: int = 2) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []

        session = self._session()
        apps_per_genre = max(1, math.ceil(limit / max(1, len(self.GENRES) * max(1, per_app_reviews))))
        items: List[Dict[str, Any]] = []
        seen_ids = set()

        for genre_name, genre_id in self.GENRES:
            try:
                top_apps = self._fetch_top_apps(session, genre_id=genre_id, limit=apps_per_genre)
            except Exception as exc:
                print(f"App Store top apps error ({genre_name}): {exc}")
                continue

            for app in top_apps:
                if len(items) >= limit:
                    return items[:limit]
                try:
                    reviews = self._fetch_reviews(
                        session,
                        app_id=app["app_id"],
                        app_name=app["app_name"],
                        app_url=app["app_url"],
                        genre_name=genre_name,
                        limit=per_app_reviews,
                    )
                except Exception as exc:
                    print(f"App Store reviews error ({app.get('app_name', 'unknown')}): {exc}")
                    continue

                for review in reviews:
                    review_id = review.get("id")
                    if not review_id or review_id in seen_ids:
                        continue
                    seen_ids.add(review_id)
                    items.append(review)
                    if len(items) >= limit:
                        return items[:limit]
        return items[:limit]

    def _fetch_top_apps(self, session: requests.Session, genre_id: str, limit: int) -> List[Dict[str, str]]:
        url = f"https://itunes.apple.com/{self.storefront}/rss/topfreeapplications/limit={limit}/genre={genre_id}/json"
        response = session.get(url, timeout=20)
        response.raise_for_status()
        payload = response.json()

        raw_entries = payload.get("feed", {}).get("entry", [])
        if isinstance(raw_entries, dict):
            raw_entries = [raw_entries]

        apps: List[Dict[str, str]] = []
        for entry in raw_entries[:limit]:
            app_id = (((entry.get("id") or {}).get("attributes") or {}).get("im:id")) or ""
            if not app_id:
                continue
            apps.append(
                {
                    "app_id": app_id,
                    "app_name": ((entry.get("im:name") or {}).get("label")) or entry.get("title", {}).get("label", ""),
                    "app_url": (((entry.get("link") or {}).get("attributes") or {}).get("href")) or "",
                }
            )
        return apps

    def _fetch_reviews(
        self,
        session: requests.Session,
        app_id: str,
        app_name: str,
        app_url: str,
        genre_name: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        url = f"https://itunes.apple.com/{self.storefront}/rss/customerreviews/page=1/id={app_id}/sortby=mostrecent/json"
        response = session.get(url, timeout=20)
        response.raise_for_status()
        payload = response.json()
        entries = payload.get("feed", {}).get("entry", []) or []

        reviews: List[Dict[str, Any]] = []
        for entry in entries:
            rating_text = ((entry.get("im:rating") or {}).get("label")) or ""
            if not rating_text.isdigit():
                continue
            rating = int(rating_text)
            content = ((entry.get("content") or {}).get("label")) or ""
            if rating > 3 or len(content.strip()) < 40:
                continue

            title = ((entry.get("title") or {}).get("label")) or ""
            review_id = ((entry.get("id") or {}).get("label")) or ""
            author = (((entry.get("author") or {}).get("name") or {}).get("label")) or "unknown"
            review_url = (((entry.get("link") or {}).get("attributes") or {}).get("href")) or app_url
            body = content.replace("\n", " ").strip()
            reviews.append(
                {
                    "id": f"appstore_review_{app_id}_{review_id or len(reviews)}",
                    "title": f"[App Store Review] {app_name}: {title}"[:200],
                    "source": "appstore_reviews",
                    "url": review_url or app_url,
                    "score": max(1, 6 - rating),
                    "description": (
                        f"App: {app_name} | Category: {genre_name} | Rating: {rating}/5 | "
                        f"Reviewer: {author} | Complaint: {body[:420]}"
                    ),
                }
            )
            if len(reviews) >= limit:
                break
        return reviews
