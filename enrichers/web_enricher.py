#!/usr/bin/env python3
"""Web enricher -- gathers lightweight market evidence for candidate opportunities."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import aiohttp


@dataclass
class EnrichmentResult:
    """Market evidence collected for a single opportunity."""
    competitor_count: int = 0
    competitor_names: List[str] = field(default_factory=list)
    pain_post_count: int = 0
    pain_snippets: List[str] = field(default_factory=list)
    ph_existing_count: int = 0
    ph_product_names: List[str] = field(default_factory=list)
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
        return '\n'.join(parts)


class WebEnricher:
    """Async web enricher that gathers market evidence via public APIs."""

    def __init__(self, timeout: int = 15):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._semaphore = asyncio.Semaphore(3)

    async def enrich_async(self, title: str, keywords: Optional[List[str]] = None) -> EnrichmentResult:
        search_terms = self._extract_search_terms(title, keywords)
        if not search_terms:
            return EnrichmentResult()
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = [
                self._check_competitors(session, search_terms),
                self._check_reddit_pain(session, search_terms),
                self._check_producthunt(session, search_terms),
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
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
        result.enrichment_summary = result.to_prompt_context()
        return result

    def enrich(self, title: str, keywords: Optional[List[str]] = None) -> EnrichmentResult:
        return asyncio.run(self.enrich_async(title, keywords))

    async def batch_enrich_async(self, items: List[Dict[str, Any]], session: Optional[aiohttp.ClientSession] = None) -> Dict[str, EnrichmentResult]:
        results: Dict[str, EnrichmentResult] = {}
        async def _one(item):
            async with self._semaphore:
                item_id = str(item.get('id', ''))
                title = item.get('title', '')
                tags = item.get('tags', [])
                return item_id, await self.enrich_async(title, tags)
        own = session is None
        client = session or aiohttp.ClientSession(timeout=self.timeout)
        try:
            tasks = [asyncio.create_task(_one(item)) for item in items]
            for task in asyncio.as_completed(tasks):
                try:
                    item_id, enrichment = await task
                    results[item_id] = enrichment
                except Exception:
                    continue
        finally:
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

    async def _check_competitors(self, session: aiohttp.ClientSession, terms: str) -> Dict[str, Any]:
        async with self._semaphore:
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
