#!/usr/bin/env python3
"""Hacker News 收集器"""

import requests
import time
from typing import List, Dict, Any
from config import HN_API_URL


class HNCollector:
    """Hacker News 文章收集器"""
    
    @staticmethod
    def fetch(limit: int = 30) -> List[Dict[str, Any]]:
        """
        获取 HN 热门新闻
        
        Args:
            limit: 获取数量
            
        Returns:
            文章列表
        """
        try:
            # 获取热门新闻 ID 列表
            response = requests.get(
                f"{HN_API_URL}/topstories.json",
                timeout=10
            )
            response.raise_for_status()
            top_ids = response.json()[:limit]
            
            # 获取文章详情（带限流）
            items = []
            for i, item_id in enumerate(top_ids):
                try:
                    # 限流：每 10 个请求延迟 1 秒
                    if i > 0 and i % 10 == 0:
                        time.sleep(1)
                    
                    item_response = requests.get(
                        f"{HN_API_URL}/item/{item_id}.json",
                        timeout=5
                    )
                    if item_response.status_code == 200:
                        item = item_response.json()
                        if item and item.get('type') == 'story' and item.get('url'):
                            items.append({
                                'id': str(item['id']),
                                'title': item.get('title', ''),
                                'url': item.get('url', ''),
                                'score': item.get('score', 0),
                                'by': item.get('by', ''),
                                'time': item.get('time', 0),
                                'descendants': item.get('descendants', 0),
                                'source': 'hn'
                            })
                except Exception as e:
                    print(f"Error fetching item {item_id}: {e}")
                    continue
            
            return items
            
        except Exception as e:
            print(f"Error fetching HN: {e}")
            return []
    
    @staticmethod
    def fetch_new(limit: int = 30) -> List[Dict[str, Any]]:
        """获取最新新闻"""
        try:
            response = requests.get(
                f"{HN_API_URL}/newstories.json",
                timeout=10
            )
            response.raise_for_status()
            new_ids = response.json()[:limit]
            
            items = []
            for item_id in new_ids:
                try:
                    item_response = requests.get(
                        f"{HN_API_URL}/item/{item_id}.json",
                        timeout=5
                    )
                    if item_response.status_code == 200:
                        item = item_response.json()
                        if item and item.get('type') == 'story' and item.get('url'):
                            items.append({
                                'id': str(item['id']),
                                'title': item.get('title', ''),
                                'url': item.get('url', ''),
                                'score': item.get('score', 0),
                                'by': item.get('by', ''),
                                'time': item.get('time', 0),
                                'source': 'hn'
                            })
                except Exception:
                    continue
            
            return items
            
        except Exception as e:
            print(f"Error fetching HN new: {e}")
            return []
