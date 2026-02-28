#!/usr/bin/env python3
"""Reddit 收集器 - r/entrepreneur 和 r/SaaS"""

import requests
from typing import List, Dict, Any


class RedditCollector:
    """Reddit 创业/SaaS 讨论收集器"""
    
    def __init__(self):
        self.subreddits = ['entrepreneur', 'SaaS']  # 先只用两个最相关的
        self.headers = {'User-Agent': 'ResearchAgent/1.0'}
    
    def fetch(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取 Reddit 热门讨论
        
        Args:
            limit: 获取数量
            
        Returns:
            帖子列表
        """
        items = []
        per_sub = limit // len(self.subreddits)
        
        for subreddit in self.subreddits:
            try:
                sub_items = self._fetch_subreddit(subreddit, per_sub)
                items.extend(sub_items)
            except Exception as e:
                print(f"Reddit r/{subreddit} error: {e}")
        
        print(f"Got {len(items)} Reddit items")
        return items
    
    def _fetch_subreddit(self, subreddit: str, limit: int) -> List[Dict[str, Any]]:
        """获取指定 subreddit 的热门帖子"""
        url = f'https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}'
        
        response = requests.get(url, headers=self.headers, timeout=30)
        
        if response.status_code != 200:
            print(f"  r/{subreddit}: HTTP {response.status_code}")
            return []
        
        data = response.json()
        items = []
        
        for post in data.get('data', {}).get('children', []):
            post_data = post.get('data', {})
            
            # 跳过置顶帖、广告、视频
            if post_data.get('stickied') or post_data.get('is_video') or post_data.get('over_18'):
                continue
            
            # 至少要有标题
            if not post_data.get('title'):
                continue
            
            items.append({
                'id': f"reddit_{post_data.get('id', '')}",
                'title': post_data.get('title', '')[:200],
                'source': f'reddit_r/{subreddit}',
                'url': f"https://www.reddit.com{post_data.get('permalink', '')}",
                'score': post_data.get('score', 0),
                'description': (post_data.get('selftext', '')[:500] if post_data.get('selftext') else ''),
                'author': post_data.get('author', 'unknown'),
                'created_at': post_data.get('created_utc', '')
            })
        
        return items
