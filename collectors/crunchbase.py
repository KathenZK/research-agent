#!/usr/bin/env python3
"""Crunchbase 投融资数据收集器"""

import requests
import os
from typing import List, Dict, Any
from datetime import datetime, timedelta


class CrunchbaseCollector:
    """Crunchbase 投融资数据收集器"""
    
    API_KEY = os.getenv('CRUNCHBASE_API_KEY', '')
    BASE_URL = 'https://api.crunchbase.com/api/v4'
    
    # 搜索关键词
    KEYWORDS = [
        'Artificial Intelligence',
        'Machine Learning',
        'SaaS',
        'Enterprise Software',
        'FinTech'
    ]
    
    @staticmethod
    def search_funding(keywords: list = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        搜索融资事件
        
        Args:
            keywords: 搜索关键词
            limit: 返回数量
            
        Returns:
            融资事件列表
        """
        if not CrunchbaseCollector.API_KEY:
            print("⚠️  CRUNCHBASE_API_KEY not configured, skipping Crunchbase")
            return []
        
        if keywords is None:
            keywords = CrunchbaseCollector.KEYWORDS
        
        results = []
        
        for keyword in keywords:
            try:
                response = requests.get(
                    f'{CrunchbaseCollector.BASE_URL}/searches/organizations',
                    headers={'X-cb-user-key': CrunchbaseCollector.API_KEY},
                    params={
                        'query': keyword,
                        'limit': limit
                    },
                    timeout=30
                )
                
                if response.status_code == 200:
                    data = response.json()
                    for entity in data.get('entities', []):
                        properties = entity.get('properties', {})
                        results.append({
                            'id': entity.get('uuid', ''),
                            'title': f"{properties.get('name', '')} raises funding",
                            'url': properties.get('web_url', ''),
                            'source': 'crunchbase',
                            'company_name': properties.get('name', ''),
                            'funding_round': properties.get('last_funding_type', ''),
                            'funding_amount': properties.get('last_funding_amount', 0),
                            'currency': properties.get('last_funding_currency', 'USD'),
                            'announced_date': properties.get('last_funding_announced_on', ''),
                            'investors': properties.get('investor_identifiers', []),
                            'description': properties.get('short_description', '')[:500],
                            'categories': properties.get('category_identifiers', []),
                            'location': properties.get('location_identifiers', [])
                        })
                
            except Exception as e:
                print(f"Crunchbase API error: {e}")
        
        return results
    
    @staticmethod
    def fetch(limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取融资数据（兼容其他收集器接口）
        
        Args:
            limit: 返回数量
            
        Returns:
            融资事件列表
        """
        return CrunchbaseCollector.search_funding(limit=limit // len(CrunchbaseCollector.KEYWORDS))


if __name__ == "__main__":
    # 测试
    funding_rounds = CrunchbaseCollector.fetch(limit=10)
    if funding_rounds:
        print(f"Found {len(funding_rounds)} funding rounds")
        for round in funding_rounds[:3]:
            print(f"- {round['company_name']}: {round['funding_round']}")
    else:
        print("No Crunchbase data (API key not configured)")
