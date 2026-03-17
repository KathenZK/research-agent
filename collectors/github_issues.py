#!/usr/bin/env python3
"""GitHub issue pain collector."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import GITHUB_TOKEN


class GitHubIssuesCollector:
    """Collect high-signal open GitHub issues from curated repos."""

    DEFAULT_REPOS = [
        "langgenius/dify",
        "n8n-io/n8n",
        "supabase/supabase",
        "calcom/cal.com",
    ]

    KEYWORDS = [
        "can't",
        "cannot",
        "missing",
        "lack",
        "need",
        "support",
        "broken",
        "friction",
        "slow",
        "error",
        "fails",
    ]

    LABEL_HINTS = [
        "bug",
        "enhancement",
        "feature",
        "request",
        "ux",
        "discussion",
    ]

    def __init__(self, repos: Optional[List[str]] = None, token: Optional[str] = None):
        self.repos = repos or list(self.DEFAULT_REPOS)
        self.token = token or GITHUB_TOKEN

    def _session(self) -> requests.Session:
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
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ResearchAgent/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        session.headers.update(headers)
        return session

    def fetch(self, limit: int = 12, min_comments: int = 3) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []

        session = self._session()
        per_repo = max(4, math.ceil(limit / max(1, len(self.repos))) * 2)
        items: List[Dict[str, Any]] = []

        for repo in self.repos:
            try:
                repo_items = self._fetch_repo_issues(
                    session=session,
                    repo=repo,
                    per_page=per_repo,
                    min_comments=min_comments,
                )
            except Exception as exc:
                print(f"GitHub issues error ({repo}): {exc}")
                continue

            items.extend(repo_items)
            if len(items) >= limit:
                break

        items.sort(key=lambda item: item.get("score", 0), reverse=True)
        return items[:limit]

    def _fetch_repo_issues(
        self,
        session: requests.Session,
        repo: str,
        per_page: int,
        min_comments: int,
    ) -> List[Dict[str, Any]]:
        url = f"https://api.github.com/repos/{repo}/issues"
        response = session.get(
            url,
            params={
                "state": "open",
                "sort": "updated",
                "direction": "desc",
                "per_page": per_page,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        items: List[Dict[str, Any]] = []

        for issue in payload:
            if issue.get("pull_request"):
                continue
            comments = int(issue.get("comments", 0) or 0)
            title = issue.get("title", "") or ""
            body = (issue.get("body") or "").strip()
            labels = [((label or {}).get("name") or "").lower() for label in issue.get("labels", [])]

            if comments < min_comments:
                continue
            if not self._looks_like_pain_signal(title, body, labels):
                continue

            items.append(
                {
                    "id": f"github_issue_{repo.replace('/', '_')}_{issue.get('number')}",
                    "title": f"[GitHub Issue] {repo}: {title}"[:200],
                    "source": "github_issues",
                    "url": issue.get("html_url", ""),
                    "score": comments,
                    "description": (
                        f"Repo: {repo} | Comments: {comments} | Labels: {', '.join(labels[:4]) or 'none'} | "
                        f"Issue: {body[:420]}"
                    ),
                }
            )
        return items

    def _looks_like_pain_signal(self, title: str, body: str, labels: List[str]) -> bool:
        normalized = f"{title} {body}".lower()
        if len(normalized.strip()) < 40:
            return False
        if any(label in " ".join(labels) for label in self.LABEL_HINTS):
            return True
        return any(keyword in normalized for keyword in self.KEYWORDS)
