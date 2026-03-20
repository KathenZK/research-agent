#!/usr/bin/env python3
"""Web enricher -- gathers market evidence and page content for candidate opportunities.

Three enrichment axes:
1. Competitor check via DuckDuckGo HTML search (real search results, not instant answers)
2. Pain density check via Reddit search
3. Page content extraction from the opportunity's source URL
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import aiohttp

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[misc,assignment]

_CONTENT_LIMIT = 2000
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class EnrichmentResult:
    """Market evidence collected for a single opportunity."""
    competitor_count: int = 0
    competitor_names: List[str] = field(default_factory=list)
    pain_post_count: int = 0
    pain_snippets: List[str] = field(default_factory=list)
    ph_existing_count: int = 0
    ph_product_names: List[str] = field(default_factory=list)
    page_content: str = ""
    enrichment_summary: str = ""

    @property
    def evidence_score(self) -> int:
        score = 0
        if self.pain_post_count >= 5:
            score += 4
        elif self.pain_post_count >= 2:
            score += 2
        if self.competitor_count == 0:
            score += 3
        elif self.competitor_count <= 3:
            score += 1
        elif self.competitor_count >= 8:
            score -= 2
        if self.ph_existing_count == 0:
            score += 2
        elif self.ph_existing_count >= 3:
            score -= 1
        if self.page_content:
            score += 1
        return score

    def to_prompt_context(self) -> str:
        parts = [f"竞品数量: {self.competitor_count}"]
        if self.competitor_names:
            parts.append(f"主要竞品: {', '.join(self.competitor_names[:5])}")
        parts.append(f"Reddit 痛点帖数: {self.pain_post_count}")
        if self.pain_snippets:
            parts.append(f"代表性痛点: {'; '.join(self.pain_snippets[:3])}")
        parts.append(f"Product Hunt 已有类似产品: {self.ph_existing_count}")
        if self.ph_product_names:
            parts.append(f"已有产品: {', '.join(self.ph_product_names[:3])}")
        if self.page_content:
            parts.append(f"\n--- 原始页面正文（截取） ---\n{self.page_content[:_CONTENT_LIMIT]}\n--- 正文结束 ---")
        return '\n'.join(parts)


class WebEnricher:
    """Async web enricher that gathers market evidence via public APIs and page scraping."""

    def __init__(self, timeout: int = 15, per_item_timeout: Optional[int] = None, progress_every: int = 10):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.per_item_timeout = per_item_timeout or max(timeout * 2, 30)
        self.progress_every = max(1, progress_every)
        self._semaphore = asyncio.Semaphore(3)
        self._logger = logging.getLogger(__name__)

    async def enrich_async(
        self,
        title: str,
        keywords: Optional[List[str]] = None,
        url: Optional[str] = None,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> EnrichmentResult:
        search_terms = self._extract_search_terms(title, keywords)
        own_session = session is None
        client = session or aiohttp.ClientSession(timeout=self.timeout)
        try:
            tasks: list = []
            if search_terms:
                tasks.extend([
                    self._check_competitors(client, search_terms),
                    self._check_reddit_pain(client, search_terms),
                    self._check_producthunt(client, search_terms),
                ])
            else:
                tasks.extend([
                    self._empty_json_result(),
                    self._empty_json_result(),
                    self._empty_json_result(),
                ])
            if url and url.startswith('http'):
                tasks.append(self._fetch_page_content(client, url))
            else:
                tasks.append(self._empty_coro())

            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            if own_session:
                await client.close()

        result = EnrichmentResult()
        if isinstance(results[0], dict):
            result.competitor_count = results[0].get('count', 0)
            result.competitor_names = results[0].get('names', [])
        if isinstance(results[1], dict):
            result.pain_post_count = results[1].get('count', 0)
            result.pain_snippets = results[1].get('snippets', [])
        if isinstance(results[2], dict):
            result.ph_existing_count = results[2].get('count', 0)
            result.ph_product_names = results[2].get('names', [])
        if isinstance(results[3], str) and results[3]:
            result.page_content = results[3][:_CONTENT_LIMIT]
        result.enrichment_summary = result.to_prompt_context()
        return result

    @staticmethod
    async def _empty_coro():
        return ""

    @staticmethod
    async def _empty_json_result() -> Dict[str, Any]:
        return {'count': 0, 'names': []}

    def enrich(self, title: str, keywords: Optional[List[str]] = None, url: Optional[str] = None) -> EnrichmentResult:
        return asyncio.run(self.enrich_async(title, keywords, url))

    async def batch_enrich_async(
        self,
        items: List[Dict[str, Any]],
        session: Optional[aiohttp.ClientSession] = None,
    ) -> Dict[str, EnrichmentResult]:
        results: Dict[str, EnrichmentResult] = {}
        total = len(items)
        completed = 0
        failed = 0

        async def _one(item: Dict[str, Any]):
            item_id = str(item.get('id', ''))
            title = item.get('title', '')
            tags = item.get('tags', [])
            url = item.get('url', '')
            try:
                enrichment = await asyncio.wait_for(
                    self.enrich_async(title, tags, url, session=client),
                    timeout=self.per_item_timeout,
                )
                return item_id, enrichment
            except asyncio.TimeoutError:
                self._logger.warning(
                    "Enrichment timeout for item_id=%s title=%r after %ss",
                    item_id,
                    title[:120],
                    self.per_item_timeout,
                )
                return item_id, EnrichmentResult()
            except Exception as exc:
                self._logger.warning(
                    "Enrichment failed for item_id=%s title=%r: %s",
                    item_id,
                    title[:120],
                    exc,
                )
                return item_id, EnrichmentResult()

        own = session is None
        client = session or aiohttp.ClientSession(timeout=self.timeout)
        tasks: List[asyncio.Task] = []
        try:
            tasks = [asyncio.create_task(_one(item)) for item in items]
            for task in asyncio.as_completed(tasks):
                item_id, enrichment = await task
                results[item_id] = enrichment
                completed += 1
                if not enrichment.page_content and enrichment.competitor_count == 0 and enrichment.pain_post_count == 0 and enrichment.ph_existing_count == 0:
                    failed += 1
                if completed == 1 or completed % self.progress_every == 0 or completed == total:
                    self._logger.info(
                        "Enrichment progress: %s/%s completed (%s empty fallbacks)",
                        completed,
                        total,
                        failed,
                    )
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if own:
                await client.close()
        return results

    def _extract_search_terms(self, title: str, keywords: Optional[List[str]] = None) -> str:
        cleaned = re.sub(r'\[.*?\]', '', title)
        cleaned = re.sub(r'[^\w\s]', ' ', cleaned)
        words = cleaned.split()
        stop = {'the', 'a', 'an', 'is', 'are', 'was', 'for', 'of', 'to', 'in', 'on', 'and', 'or', 'with', 'from'}
        meaningful = [w for w in words if w.lower() not in stop and len(w) > 2][:6]
        if keywords:
            meaningful.extend(kw for kw in keywords[:3] if kw.lower() not in stop)
        return ' '.join(meaningful[:8])

    # ------------------------------------------------------------------
    # Competitor check: DuckDuckGo HTML search (real results)
    # ------------------------------------------------------------------

    async def _check_competitors(self, session: aiohttp.ClientSession, terms: str) -> Dict[str, Any]:
        """Search DuckDuckGo HTML endpoint for real competitor results."""
        async with self._semaphore:
            try:
                query = f"{terms} tool OR software OR app OR SaaS"
                url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
                headers = {**_HEADERS, "Accept": "text/html"}
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        return await self._check_competitors_fallback(session, terms)
                    html = await resp.text()

                names: List[str] = []
                if BeautifulSoup:
                    soup = BeautifulSoup(html, 'html.parser')
                    for result in soup.select('.result__title, .result__a'):
                        text = result.get_text(strip=True)
                        if text and len(text) > 3 and len(text) < 80:
                            clean = re.sub(r'\s+', ' ', text).strip()
                            if clean and clean.lower() not in ('duckduckgo', 'privacy'):
                                names.append(clean)
                else:
                    raw_titles = re.findall(r'class="result__a"[^>]*>([^<]+)<', html)
                    for t in raw_titles:
                        clean = re.sub(r'\s+', ' ', t).strip()
                        if clean and len(clean) > 3 and len(clean) < 80:
                            names.append(clean)

                unique = list(dict.fromkeys(names))[:10]
                return {'count': len(unique), 'names': unique[:5]}
            except Exception:
                return await self._check_competitors_fallback(session, terms)

    async def _check_competitors_fallback(self, session: aiohttp.ClientSession, terms: str) -> Dict[str, Any]:
        """Fallback to DuckDuckGo Instant Answers API."""
        try:
            query = f"{terms} tool OR software OR app"
            url = f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_redirect=1"
            async with session.get(url) as resp:
                if resp.status != 200:
                    return {'count': 0, 'names': []}
                data = await resp.json(content_type=None)
            names = []
            for topic in (data.get('RelatedTopics', []))[:10]:
                text = topic.get('Text', '')
                if text:
                    name = text.split(' - ')[0].strip()[:50]
                    if name and len(name) > 2:
                        names.append(name)
            return {'count': len(names), 'names': names[:5]}
        except Exception:
            return {'count': 0, 'names': []}

    # ------------------------------------------------------------------
    # Reddit pain check
    # ------------------------------------------------------------------

    async def _check_reddit_pain(self, session: aiohttp.ClientSession, terms: str) -> Dict[str, Any]:
        async with self._semaphore:
            try:
                query = f"{terms} frustrated OR broken OR alternative OR wish"
                url = f"https://www.reddit.com/search.json?q={quote_plus(query)}&sort=new&t=month&limit=10"
                headers = {"User-Agent": "ResearchAgent/2.0 (enricher)"}
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        return {'count': 0, 'snippets': []}
                    data = await resp.json(content_type=None)
                posts = data.get('data', {}).get('children', [])
                snippets = []
                for post in posts:
                    pd = post.get('data', {})
                    t = pd.get('title', '')
                    if t:
                        snippets.append(f"r/{pd.get('subreddit', '?')}: {t[:100]}")
                return {'count': len(posts), 'snippets': snippets[:5]}
            except Exception:
                return {'count': 0, 'snippets': []}

    # ------------------------------------------------------------------
    # Product Hunt check
    # ------------------------------------------------------------------

    async def _check_producthunt(self, session: aiohttp.ClientSession, terms: str) -> Dict[str, Any]:
        async with self._semaphore:
            try:
                url = f"https://www.producthunt.com/search/posts?q={quote_plus(terms)}"
                headers = {"User-Agent": "ResearchAgent/2.0 (enricher)", "Accept": "application/json"}
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        return {'count': 0, 'names': []}
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        text = await resp.text()
                        names = re.findall(r'"name"\s*:\s*"([^"]+)"', text)[:5]
                        return {'count': len(names), 'names': names}
                posts = data if isinstance(data, list) else data.get('posts', data.get('results', []))
                names = [p.get('name', '') for p in posts[:10] if isinstance(p, dict) and p.get('name')]
                return {'count': len(names), 'names': names[:5]}
            except Exception:
                return {'count': 0, 'names': []}

    # ------------------------------------------------------------------
    # Page content extraction (P0 fix: feed real content to LLM Call 2)
    # ------------------------------------------------------------------

    async def _fetch_page_content(self, session: aiohttp.ClientSession, url: str) -> str:
        """Fetch and extract readable text from the opportunity's source URL."""
        if not url or not url.startswith('http'):
            return ""
        skip_domains = ('github.com/trending', 'reddit.com/search', 'itunes.apple.com')
        if any(d in url for d in skip_domains):
            return ""
        async with self._semaphore:
            try:
                async with session.get(url, headers=_HEADERS, allow_redirects=True) as resp:
                    if resp.status != 200:
                        return ""
                    ctype = resp.headers.get('content-type', '')
                    if 'text/html' not in ctype and 'application/xhtml' not in ctype:
                        return ""
                    html = await resp.text(errors='replace')

                if BeautifulSoup:
                    soup = BeautifulSoup(html, 'html.parser')
                    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'noscript']):
                        tag.decompose()
                    article = soup.find('article') or soup.find('main') or soup.find('body')
                    if not article:
                        return ""
                    text = article.get_text(separator='\n', strip=True)
                else:
                    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()

                lines = [line.strip() for line in text.splitlines() if line.strip()]
                clean = '\n'.join(lines)
                return clean[:_CONTENT_LIMIT] if clean else ""
            except Exception:
                return ""
