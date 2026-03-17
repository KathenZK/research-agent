#!/usr/bin/env python3
"""IndieHackers 收集器 - 一人公司/独立开发者案例"""

import requests
from typing import List, Dict, Any


class IndieHackersCollector:
    """IndieHackers 产品/收入案例收集器（API + 备用）"""
    
    def fetch(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取 IndieHackers 上的产品案例
        
        Args:
            limit: 获取数量
            
        Returns:
            产品列表
        """
        items = []
        
        # 尝试 API 方案
        items = self._fetch_api(limit)
        
        print(f"Got {len(items)} IndieHackers items")
        return items
    
    def _fetch_api(self, limit: int) -> List[Dict[str, Any]]:
        """尝试从 IndieHackers 获取真实数据"""
        items: List[Dict[str, Any]] = []
        try:
            # 使用公开的产品列表页面
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
            
            # 尝试获取热门产品
            response = requests.get(
                'https://www.indiehackers.com/products',
                headers=headers,
                timeout=15
            )
            
            if response.status_code == 200:
                # 简单解析 HTML 获取产品链接
                import re
                pattern = r'href="(/products/[^"]+)"'
                matches = re.findall(pattern, response.text)
                
                for href in matches[:limit]:
                    # 获取产品详情
                    product_url = f'https://www.indiehackers.com{href}'
                    items.append({
                        'id': f"ih_{href.split('/')[-1]}",
                        'title': f'IndieHackers Product: {href.split("/")[-1]}',
                        'source': 'indiehackers',
                        'url': product_url,
                        'score': 0,
                        'description': f'Independent developer product from IndieHackers community',
                        'author': 'unknown',
                        'created_at': ''
                    })
                
                if items:
                    return items
        except Exception as e:
            print(f"IndieHackers API error: {e}")
        
        return []
    
