#!/usr/bin/env python3
"""Product Hunt 收集器 - 每日热门产品"""

import feedparser
import requests
from typing import List, Dict, Any
import os


class PHCollector:
    """Product Hunt 产品收集器（RSS + API）"""
    
    @staticmethod
    def fetch(limit: int = 20) -> List[Dict[str, Any]]:
        """获取 Product Hunt 产品"""
        items = []
        
        # 先尝试 API（需要 token）
        items = PHCollector._fetch_api(limit)
        
        # API 失败则用 RSS
        if not items:
            items = PHCollector._fetch_rss(limit)
        
        return items
    
    @staticmethod
    def _fetch_api(limit: int) -> List[Dict[str, Any]]:
        """通过 GraphQL API 获取（需要配置 token）"""
        token = os.getenv('PH_ACCESS_TOKEN')
        if not token:
            return []
        
        try:
            query = """
            {
              posts(first: %d) {
                edges {
                  node {
                    id
                    name
                    tagline
                    url
                    votesCount
                  }
                }
              }
            }
            """ % limit
            
            response = requests.post(
                "https://api.producthunt.com/v2/api/graphql",
                headers={"Authorization": f"Bearer {token}"},
                json={"query": query},
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                items = []
                for edge in data.get('data', {}).get('posts', {}).get('edges', []):
                    node = edge.get('node', {})
                    items.append({
                        'id': f"ph_{node.get('id', '')}",
                        'title': f"{node.get('name', '')} - {node.get('tagline', '')}"[:200],
                        'source': 'ph',
                        'url': node.get('url', ''),
                        'score': node.get('votesCount', 0),
                        'description': node.get('tagline', '')[:500],
                    })
                return items
        except Exception as e:
            print(f"PH API error: {e}")
        
        return []
    
    @staticmethod
    def _fetch_rss(limit: int) -> List[Dict[str, Any]]:
        """RSS 备用方案"""
        try:
            feed = feedparser.parse("https://www.producthunt.com/feed")
            
            items = []
            for entry in feed.entries[:limit]:
                items.append({
                    'id': f"ph_{entry.id}" if hasattr(entry, 'id') else entry.link,
                    'title': entry.title[:200],
                    'source': 'ph',
                    'url': entry.link,
                    'score': 0,
                    'description': entry.summary[:500] if hasattr(entry, 'summary') else '',
                })
            
            return items
        except Exception as e:
            print(f"Error fetching PH RSS: {e}")
            return []
