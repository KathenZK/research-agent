#!/usr/bin/env python3
"""Product Hunt 收集器"""

import feedparser
from typing import List, Dict, Any
from datetime import datetime
from config import PH_RSS_URL


class PHCollector:
    """Product Hunt 产品收集器"""
    
    @staticmethod
    def fetch(limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取 PH 热门产品
        
        Args:
            limit: 获取数量
            
        Returns:
            产品列表
        """
        try:
            feed = feedparser.parse(PH_RSS_URL)
            
            items = []
            for entry in feed.entries[:limit]:
                items.append({
                    'id': entry.get('id', str(len(items))),
                    'title': entry.get('title', ''),
                    'url': entry.get('link', ''),
                    'description': entry.get('description', '')[:500],
                    'published': entry.get('published', ''),
                    'source': 'ph'
                })
            
            return items
            
        except Exception as e:
            print(f"Error fetching PH: {e}")
            return []
