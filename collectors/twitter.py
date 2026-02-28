#!/usr/bin/env python3
"""Twitter/X 收集器 - AI/创业相关推文"""

import subprocess
import json
from typing import List, Dict, Any


class TwitterCollector:
    """Twitter/X 推文收集器（使用 xurl）"""
    
    def __init__(self):
        self.queries = [
            'AI startup',
            'indie hacker',
            'SaaS founder',
            'build in public',
            'solopreneur'
        ]
    
    def fetch(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取 Twitter 热门推文
        
        Args:
            limit: 获取数量
            
        Returns:
            推文列表
        """
        items = []
        per_query = limit // len(self.queries)
        
        for query in self.queries:
            try:
                query_items = self._search(query, per_query)
                items.extend(query_items)
            except Exception as e:
                print(f"Twitter search '{query}' error: {e}")
        
        print(f"Got {len(items)} Twitter items")
        return items
    
    def _search(self, query: str, count: int) -> List[Dict[str, Any]]:
        """搜索推文"""
        try:
            # 使用 xurl 搜索
            cmd = [
                'xurl',
                '--auth', 'oauth1',
                'search', query,
                '-n', str(count)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                print(f"  xurl error: {result.stderr[:100]}")
                return []
            
            # 解析 JSON 输出
            data = json.loads(result.stdout)
            items = []
            
            for tweet in data.get('data', []):
                items.append({
                    'id': f"twitter_{tweet.get('id', '')}",
                    'title': tweet.get('text', '')[:200],
                    'source': 'twitter',
                    'url': f"https://twitter.com/statuses/{tweet.get('id', '')}",
                    'score': 0,
                    'description': tweet.get('text', '')[:500],
                    'author': tweet.get('author_id', 'unknown'),
                    'created_at': tweet.get('created_at', '')
                })
            
            return items
            
        except Exception as e:
            print(f"  Twitter API error: {e}")
            return []
