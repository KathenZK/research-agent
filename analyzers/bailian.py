#!/usr/bin/env python3
"""阿里百炼 API 分析器"""

import json
import requests
import time
from typing import Dict, Any, Optional
from datetime import datetime

from config import BAILIAN_API_KEY, BAILIAN_MODEL, BAILIAN_ENDPOINT, DEBUG, BAILIAN_TIMEOUT
from models.opportunity import Opportunity


class BailianAnalyzer:
    """阿里百炼大模型分析器"""
    
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or BAILIAN_API_KEY
        self.model = model or BAILIAN_MODEL
        self.endpoint = BAILIAN_ENDPOINT
        
        if not self.api_key:
            raise ValueError("BAILIAN_API_KEY not configured")
    
    def analyze(self, item: Dict[str, Any]) -> Optional[Opportunity]:
        """
        分析一个项目，生成机会评估（带重试机制）
        
        Args:
            item: 收集到的项目数据
            
        Returns:
            Opportunity 对象，如果分析失败返回 None
        """
        max_retries = 3
        base_delay = 2  # 秒
        
        try:
            for attempt in range(max_retries):
                try:
                    prompt = self._build_prompt(item)
                    
                    response = requests.post(
                        self.endpoint,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": self.model,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": "你是一个产品机会分析专家。分析技术新闻和产品，评估商业机会。输出严格的 JSON 格式。\n\n" + prompt
                                }
                            ],
                            "max_tokens": 1000,
                            "temperature": 0.7
                        },
                        timeout=BAILIAN_TIMEOUT
                    )
                    
                    if response.status_code == 429:  # Rate limited
                        delay = base_delay * (2 ** attempt)
                        print(f"Rate limited, retrying in {delay}s...")
                        time.sleep(delay)
                        continue
                    
                    if response.status_code != 200:
                        print(f"API Error: {response.status_code}")
                        print(f"Response: {response.text[:500]}")
                        return None
                    
                    result = response.json()
                    break  # Success
                    
                except requests.exceptions.Timeout:
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        print(f"Timeout, retrying in {delay}s...")
                        time.sleep(delay)
                    else:
                        print(f"Timeout after {max_retries} attempts")
                        return None
                except requests.exceptions.RequestException as e:
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        print(f"Request error: {e}, retrying in {delay}s...")
                        time.sleep(delay)
                    else:
                        print(f"Request failed after {max_retries} attempts: {e}")
                        return None
            
            # 处理成功的响应
            if DEBUG:
                print(f"API Response: {json.dumps(result, indent=2)}")
            
            # 解析 AI 输出 - Anthropic 兼容 API 格式
            content = ''
            if 'content' in result and isinstance(result['content'], list) and len(result['content']) > 0:
                content = result['content'][0].get('text', '')
            elif 'choices' in result:
                content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
            
            if DEBUG:
                print(f"AI Response: {content}")
            
            # 尝试解析 JSON
            analysis = self._parse_json(content)
            if not analysis:
                return None
            
            # 创建 Opportunity
            return Opportunity(
                id=item['id'],
                title=item['title'],
                source=item.get('source', 'unknown'),
                url=item.get('url', ''),
                score=analysis.get('score', 50),
                summary=analysis.get('summary', ''),
                suggestion=analysis.get('suggestion', ''),
                tags=analysis.get('tags', []),
                created_at=datetime.now()
            )
            
        except Exception as e:
            print(f"Error analyzing item: {e}")
            if DEBUG:
                import traceback
                traceback.print_exc()
            return None
    
    def _build_prompt(self, item: Dict[str, Any]) -> str:
        """构建分析提示词"""
        return f"""
分析这个产品/新闻机会：

标题：{item.get('title', '')}
来源：{item.get('source', 'unknown').upper()}
链接：{item.get('url', '')}
{f"描述：{item.get('description', '')[:500]}" if item.get('description') else ""}
{f"热度：{item.get('score', 0)} 分" if item.get('score') else ""}
{f"评论：{item.get('descendants', 0)} 条" if item.get('descendants') is not None else ""}

请评估这是一个多好的产品机会（0-100 分），并给出分析。

输出严格的 JSON 格式：
{{
    "score": 75,
    "summary": "200 字以内的摘要，说明这是什么、解决了什么问题",
    "suggestion": "100 字以内的可落地产品建议",
    "tags": ["AI", "SaaS", "B2B"]
}}

评分标准：
- 90-100: 明确的痛点 + 付费意愿强 + 竞争少
- 70-89: 有需求 + 有市场 + 可差异化
- 50-69: 一般机会，需要验证
- 0-49: 不建议做
"""
    
    def _parse_json(self, content: str) -> Optional[Dict]:
        """解析 JSON 输出"""
        try:
            # 尝试直接解析
            return json.loads(content)
        except json.JSONDecodeError:
            # 尝试提取 JSON
            import re
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return None
    
    def batch_analyze(self, items: list, min_score: int = 60) -> list:
        """
        批量分析
        
        Args:
            items: 项目列表
            min_score: 最低分数阈值
            
        Returns:
            机会列表（按分数排序）
        """
        opportunities = []
        
        for item in items:
            if DEBUG:
                print(f"Analyzing: {item.get('title', '')[:50]}...")
            
            opp = self.analyze(item)
            if opp and opp.score >= min_score:
                opportunities.append(opp)
        
        # 按分数排序
        return sorted(opportunities, key=lambda x: x.score, reverse=True)
