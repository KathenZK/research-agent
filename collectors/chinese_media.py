#!/usr/bin/env python3
"""中国科技媒体收集器 (36 氪、虎嗅等)"""

import feedparser
import requests
from typing import List, Dict, Any
from datetime import datetime, timedelta
import time


class ChineseMediaCollector:
    """中国科技媒体文章收集器"""
    
    # RSS 源
    RSS_FEEDS = {
        '36kr': 'https://36kr.com/feed',
        'huxiu': 'https://www.huxiu.com/rss/0.xml',
        'tiehan': 'https://www.tmtpost.com/feed'  # 钛媒体
    }
    
    # 关键词过滤
    KEYWORDS = [
        'AI', '人工智能', '融资', '创业', ' startup',
        'A 轮', 'B 轮', '天使轮', '种子轮',
        'SaaS', '大模型', 'AIGC', 'LLM'
    ]
    
    @staticmethod
    def _is_relevant(title: str, summary: str = '') -> bool:
        """检查文章是否相关"""
        text = (title + ' ' + summary).lower()
        return any(keyword.lower() in text for keyword in ChineseMediaCollector.KEYWORDS)
    
    @staticmethod
    def fetch(hours: int = 48, limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取最近 N 小时的文章
        
        Args:
            hours: 时间范围（小时）
            limit: 返回数量
            
        Returns:
            文章列表
        """
        items = []
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        for source, url in ChineseMediaCollector.RSS_FEEDS.items():
            try:
                feed = feedparser.parse(url)
                
                for entry in feed.entries[:limit // len(ChineseMediaCollector.RSS_FEEDS)]:
                    # 解析时间
                    try:
                        published = datetime(*entry.published_parsed[:6])
                    except:
                        published = datetime.now()
                    
                    # 时间过滤
                    if published < cutoff_time:
                        continue
                    
                    # 相关性过滤
                    if not ChineseMediaCollector._is_relevant(entry.title, entry.get('summary', '')):
                        continue
                    
                    items.append({
                        'id': entry.get('id', str(len(items))),
                        'title': entry.title,
                        'url': entry.get('link', ''),
                        'source': source,
                        'author': entry.get('author', ''),
                        'published': published.isoformat(),
                        'description': entry.get('summary', '')[:500],
                        'tags': [tag.get('term', '') for tag in entry.get('tags', [])[:5]]
                    })
                
                # 限流
                time.sleep(1)
                
            except Exception as e:
                print(f"Error fetching {source}: {e}")
        
        # 按时间排序
        items.sort(key=lambda x: x['published'], reverse=True)
        
        return items


if __name__ == "__main__":
    # 测试
    articles = ChineseMediaCollector.fetch(hours=24, limit=20)
    print(f"Found {len(articles)} articles")
    for article in articles[:5]:
        print(f"- [{article['source']}] {article['title'][:50]}...")
