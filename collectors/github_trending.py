#!/usr/bin/env python3
"""GitHub Trending 收集器 - 热门开源项目"""

import requests
from typing import List, Dict, Any
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class GitHubTrendingCollector:
    """GitHub Trending 项目收集器"""
    
    def __init__(self):
        self.base_url = "https://github.com/trending"
        self.languages = ["", "Python", "JavaScript", "TypeScript"]  # 空字符串表示全部

    def _session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(['GET']),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        return session
    
    def fetch(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取 GitHub Trending 项目
        
        Args:
            limit: 获取数量
            
        Returns:
            项目列表
        """
        items = []
        
        # 获取默认语言列表的 Trending
        try:
            trending_items = self._fetch_trending(limit)
            items.extend(trending_items)
        except Exception as e:
            print(f"GitHub Trending error: {e}")
        
        print(f"Got {len(items)} GitHub Trending items")
        return items
    
    def _fetch_trending(self, limit: int) -> List[Dict[str, Any]]:
        """抓取 GitHub Trending 页面"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        
        response = self._session().get(self.base_url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            print(f"  GitHub Trending: HTTP {response.status_code}")
            return []
        
        items = []
        html = response.text
        
        # 简单解析 HTML
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        
        articles = soup.find_all('article', class_='Box-row')
        
        for article in articles[:limit]:
            try:
                # 获取项目标题
                title_elem = article.find('h2', class_='h3').find('a')
                if not title_elem:
                    continue
                
                full_name = title_elem.get('href', '').strip('/')
                name_parts = full_name.split('/')
                
                if len(name_parts) != 2:
                    continue
                
                author, name = name_parts
                
                # 获取描述
                desc_elem = article.find('p', class_='col-9')
                description = desc_elem.get_text(strip=True)[:500] if desc_elem else ''
                
                # 获取 star 数
                star_elem = article.find('a', href=lambda x: x and '/stargazers' in x)
                stars_text = star_elem.get_text(strip=True) if star_elem else '0'
                stars = self._parse_number(stars_text)
                
                # 获取 fork 数
                fork_elem = article.find('a', href=lambda x: x and '/forks' in x)
                forks_text = fork_elem.get_text(strip=True) if fork_elem else '0'
                forks = self._parse_number(forks_text)
                
                # 获取语言
                lang_elem = article.find('span', itemprop='programmingLanguage')
                language = lang_elem.get_text(strip=True) if lang_elem else ''
                
                items.append({
                    'id': f"github_{full_name.replace('/', '_')}",
                    'title': f"{name} - {description[:100] if description else 'GitHub Trending Project'}",
                    'source': 'github_trending',
                    'url': f"https://github.com/{full_name}",
                    'score': stars,  # 用 star 数作为评分参考
                    'description': f"**{name}** by @{author}\n\n{description}\n\n⭐ {stars} | 🍴 {forks} | 💻 {language or 'Unknown'}",
                    'author': author,
                    'created_at': datetime.now().isoformat(),
                    'metadata': {
                        'full_name': full_name,
                        'stars': stars,
                        'forks': forks,
                        'language': language
                    }
                })
                
            except Exception as e:
                print(f"  Parse error: {e}")
                continue
        
        return items
    
    def _parse_number(self, text: str) -> int:
        """解析数字（处理 k, M 等单位）"""
        text = text.replace(',', '').strip()
        
        if not text:
            return 0
        
        try:
            if 'k' in text.lower():
                return int(float(text.lower().replace('k', '')) * 1000)
            elif 'm' in text.lower():
                return int(float(text.lower().replace('m', '')) * 1000000)
            else:
                return int(text)
        except:
            return 0


# 测试
if __name__ == '__main__':
    collector = GitHubTrendingCollector()
    items = collector.fetch(limit=5)
    
    print(f"\nGot {len(items)} items\n")
    for i, item in enumerate(items[:3], 1):
        print(f"{i}. {item['title'][:60]}...")
        print(f"   URL: {item['url']}")
        print(f"   Stars: {item['metadata']['stars']:,}")
        print()
