#!/usr/bin/env python3
"""SaaS review complaint collector -- scrapes low-rated reviews from public SaaS directories."""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[misc,assignment]


class SaaSReviewsCollector:
    """Collect low-rated SaaS reviews from AlternativeTo and Capterra public pages.

    G2 requires authentication for bulk scraping so we focus on freely accessible
    review sources that still surface genuine user complaints.
    """

    ALTERNATIVETO_CATEGORIES = [
        ("project-management", "https://alternativeto.net/category/business-and-commerce/project-management/"),
        ("crm", "https://alternativeto.net/category/business-and-commerce/crm/"),
        ("accounting", "https://alternativeto.net/category/business-and-commerce/accounting/"),
        ("email-marketing", "https://alternativeto.net/category/business-and-commerce/email-marketing/"),
        ("customer-support", "https://alternativeto.net/category/business-and-commerce/customer-support/"),
    ]

    CAPTERRA_CATEGORIES = [
        ("project-management", "https://www.capterra.com/project-management-software/reviews/?rating=1"),
        ("crm", "https://www.capterra.com/customer-relationship-management-software/reviews/?rating=1"),
        ("accounting", "https://www.capterra.com/accounting-software/reviews/?rating=1"),
        ("helpdesk", "https://www.capterra.com/help-desk-software/reviews/?rating=1"),
    ]

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

    @staticmethod
    def _session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def fetch(self, limit: int = 12) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []

        session = self._session()
        session.headers.update(self.headers)
        items: List[Dict[str, Any]] = []
        seen: set[str] = set()

        capterra_items = self._fetch_capterra(session, limit=max(4, limit // 2))
        for item in capterra_items:
            if item["id"] not in seen:
                seen.add(item["id"])
                items.append(item)

        if BeautifulSoup is not None:
            alt_items = self._fetch_alternativeto_dislikes(session, limit=max(4, limit // 2))
            for item in alt_items:
                if item["id"] not in seen:
                    seen.add(item["id"])
                    items.append(item)

        items.sort(key=lambda x: x.get("score", 0), reverse=True)
        return items[:limit]

    def _fetch_capterra(self, session: requests.Session, limit: int) -> List[Dict[str, Any]]:
        """Fetch low-rated reviews from Capterra public review pages."""
        if BeautifulSoup is None:
            return []

        items: List[Dict[str, Any]] = []
        per_cat = max(2, limit // len(self.CAPTERRA_CATEGORIES))

        for category_name, url in self.CAPTERRA_CATEGORIES:
            if len(items) >= limit:
                break
            try:
                resp = session.get(url, timeout=20)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")

                review_blocks = soup.select("[class*='review']")
                count = 0
                for block in review_blocks:
                    text = block.get_text(separator=" ", strip=True)
                    if len(text) < 80:
                        continue

                    cons_match = re.search(
                        r"(?:cons?|disadvantages?|what.{0,20}don.?t like)[\s:]+(.{40,400})",
                        text, re.IGNORECASE,
                    )
                    complaint = cons_match.group(1).strip() if cons_match else text[:400]

                    product_el = block.find(["h3", "h4", "a"], string=True)
                    product_name = product_el.get_text(strip=True) if product_el else category_name

                    review_id = hashlib.md5(complaint[:100].encode()).hexdigest()[:10]
                    items.append({
                        "id": f"capterra_{category_name}_{review_id}",
                        "title": f"[Capterra] {product_name}: {complaint[:80]}"[:200],
                        "source": "saas_reviews",
                        "url": url,
                        "score": 3,
                        "description": (
                            f"Platform: Capterra | Category: {category_name} | "
                            f"Product: {product_name} | Complaint: {complaint[:420]}"
                        ),
                    })
                    count += 1
                    if count >= per_cat:
                        break
            except Exception as exc:
                print(f"Capterra scrape error ({category_name}): {exc}")

            time.sleep(1.5)

        return items

    def _fetch_alternativeto_dislikes(self, session: requests.Session, limit: int) -> List[Dict[str, Any]]:
        """Fetch 'disliked' or low-rated items from AlternativeTo."""
        items: List[Dict[str, Any]] = []
        per_cat = max(2, limit // len(self.ALTERNATIVETO_CATEGORIES))

        for category_name, url in self.ALTERNATIVETO_CATEGORIES:
            if len(items) >= limit:
                break
            try:
                resp = session.get(url, timeout=20)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")

                app_items = soup.select(".app-list-item, [data-testid='app-item'], .listing-item")
                count = 0
                for app_item in app_items:
                    name_el = app_item.find(["h3", "a", "h2"], string=True)
                    if not name_el:
                        continue
                    name = name_el.get_text(strip=True)
                    desc = app_item.get_text(separator=" ", strip=True)[:300]
                    link_el = app_item.find("a", href=True)
                    link = f"https://alternativeto.net{link_el['href']}" if link_el else url

                    dislikes = 0
                    dislike_el = app_item.find(string=re.compile(r"dislike|thumbs.?down", re.I))
                    if dislike_el:
                        num = re.search(r"\d+", dislike_el.string or "")
                        dislikes = int(num.group()) if num else 1

                    if dislikes < 1 and count >= per_cat // 2:
                        continue

                    review_id = hashlib.md5(name.encode()).hexdigest()[:10]
                    items.append({
                        "id": f"alternativeto_{category_name}_{review_id}",
                        "title": f"[AlternativeTo] {name} (dislikes: {dislikes})"[:200],
                        "source": "saas_reviews",
                        "url": link,
                        "score": max(1, dislikes),
                        "description": (
                            f"Platform: AlternativeTo | Category: {category_name} | "
                            f"App: {name} | Dislikes: {dislikes} | {desc[:300]}"
                        ),
                    })
                    count += 1
                    if count >= per_cat:
                        break
            except Exception as exc:
                print(f"AlternativeTo scrape error ({category_name}): {exc}")

            time.sleep(1.5)

        return items
