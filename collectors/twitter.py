#!/usr/bin/env python3
"""Twitter/X 收集器"""

import subprocess
import json
import time
from typing import List, Dict, Any
from datetime import datetime, timedelta


class TwitterCollector:
    """Twitter/X 推文收集器"""
    
    # 监控关键词
    KEYWORDS = [
        "AI startup launch",
        "YC startup",
        "seed round AI",
        "Series A funding",
        "SaaS launch",
        "AI product launch"
    ]
    
    @staticmethod
    def search(keywords: list = None, limit: int = 20) -> List[Dict[str, Any]]:
        """
        搜索 Twitter 推文
        
        Args:
            keywords: 搜索关键词列表
            limit: 每个关键词返回数量
            
        Returns:
            推文列表
        """
        if keywords is None:
            keywords = TwitterCollector.KEYWORDS
        
        results = []
        
        for keyword in keywords:
            try:
                # 使用 xurl search
                cmd = f'xurl search "{keyword}" -n {limit}'
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    try:
                        tweets = json.loads(result.stdout)
                        for tweet in tweets.get('data', []):
                            results.append({
                                'id': tweet.get('id', ''),
                                'title': tweet.get('text', '')[:200],
                                'url': f"https://twitter.com/i/status/{tweet.get('id', '')}",
                                'source': 'twitter',
                                'author': tweet.get('author_username', ''),
                                'created_at': tweet.get('created_at', ''),
                                'metrics': {
                                    'likes': tweet.get('public_metrics', {}).get('like_count', 0),
                                    'retweets': tweet.get('public_metrics', {}).get('retweet_count', 0),
                                    'replies': tweet.get('public_metrics', {}).get('reply_count', 0)
                                },
                                'description': tweet.get('text', '')[:500]
                            })
                    except json.JSONDecodeError:
                        print(f"JSON parse error for keyword: {keyword}")
                
                # 限流
                time.sleep(2)
                
            except subprocess.TimeoutExpired:
                print(f"Twitter search timeout for: {keyword}")
            except Exception as e:
                print(f"Twitter search error: {e}")
        
        return results
    
    @staticmethod
    def fetch(limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取推文（兼容其他收集器接口）
        
        Args:
            limit: 返回数量
            
        Returns:
            推文列表
        """
        return TwitterCollector.search(limit=limit // len(TwitterCollector.KEYWORDS))


if __name__ == "__main__":
    # 测试
    tweets = TwitterCollector.fetch(limit=10)
    print(f"Found {len(tweets)} tweets")
    for tweet in tweets[:3]:
        print(f"- {tweet['title'][:50]}...")
