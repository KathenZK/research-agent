#!/usr/bin/env python3
"""阿里百炼 API 分析器"""

import json
import requests
from typing import Dict, Any, Optional
from datetime import datetime

from config import BAILIAN_API_KEY, BAILIAN_MODEL, BAILIAN_ENDPOINT, DEBUG
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
        分析一个项目，生成机会评估
        
        Args:
            item: 收集到的项目数据
            
        Returns:
            Opportunity 对象，如果分析失败返回 None
        """
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
                    "input": {
                        "messages": [
                            {
                                "role": "system",
                                "content": "你是一个产品机会分析专家。分析技术新闻和产品，评估商业机会。输出严格的 JSON 格式。"
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ]
                    },
                    "parameters": {
                        "temperature": 0.7,
                        "max_tokens": 1000
                    }
                },
                timeout=30
            )
            
            response.raise_for_status()
            result = response.json()
            
            if DEBUG:
                print(f"API Response: {json.dumps(result, indent=2)}")
            
            # 解析 AI 输出 - 百炼 API 格式
            # 格式 1: output.choices[0].message.content
            # 格式 2: output.text
            content = ''
            output = result.get('output', {})
            if 'choices' in output:
                content = output.get('choices', [{}])[0].get('message', {}).get('content', '')
            elif 'text' in output:
                content = output.get('text', '')
            elif 'content' in output:
                content = output.get('content', '')
            
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
