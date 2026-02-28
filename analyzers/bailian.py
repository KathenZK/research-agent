#!/usr/bin/env python3
"""阿里百炼 API 分析器"""

import asyncio
import json
from typing import Dict, Any, Optional
from datetime import datetime

import aiohttp

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
    
    async def analyze_async(
        self,
        item: Dict[str, Any],
        session: Optional[aiohttp.ClientSession] = None
    ) -> Optional[Opportunity]:
        """
        分析一个项目，生成机会评估（带重试机制）
        
        Args:
            item: 收集到的项目数据
            
        Returns:
            Opportunity 对象，如果分析失败返回 None
        """
        max_retries = 3
        base_delay = 2  # 秒

        prompt = self._build_prompt(item)
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": "你是一个产品机会分析专家。分析技术新闻和产品，评估商业机会。输出严格的 JSON 格式。\n\n" + prompt
                }
            ],
            "max_tokens": 1000,
            "temperature": 0.7
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        own_session = session is None
        timeout = aiohttp.ClientTimeout(total=BAILIAN_TIMEOUT)
        client = session or aiohttp.ClientSession(timeout=timeout)

        try:
            for attempt in range(max_retries):
                try:
                    async with client.post(
                        self.endpoint,
                        headers=headers,
                        json=payload
                    ) as response:
                        if response.status == 429:  # Rate limited
                            delay = base_delay * (2 ** attempt)
                            print(f"Rate limited, retrying in {delay}s...")
                            await asyncio.sleep(delay)
                            continue

                        if response.status != 200:
                            response_text = await response.text()
                            print(f"API Error: {response.status}")
                            print(f"Response: {response_text[:500]}")
                            return None

                        result = await response.json()
                        break  # Success

                except (aiohttp.ServerTimeoutError, asyncio.TimeoutError):
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        print(f"Timeout, retrying in {delay}s...")
                        await asyncio.sleep(delay)
                    else:
                        print(f"Timeout after {max_retries} attempts")
                        return None
                except aiohttp.ClientError as e:
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        print(f"Request error: {e}, retrying in {delay}s...")
                        await asyncio.sleep(delay)
                    else:
                        print(f"Request failed after {max_retries} attempts: {e}")
                        return None
            else:
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
            
            # 创建 Opportunity（一人公司格式）
            return Opportunity(
                id=item['id'],
                title=item['title'],
                source=item.get('source', 'unknown'),
                url=item.get('url', ''),
                score=analysis.get('score', 50),
                summary=analysis.get('summary', ''),
                description=analysis.get('description', ''),
                solo_feasibility=analysis.get('solo_feasibility', ''),
                agent_roles=analysis.get('agent_roles', []),
                startup_cost=analysis.get('startup_cost', ''),
                time_to_revenue=analysis.get('time_to_revenue', ''),
                revenue_model=analysis.get('revenue_model', ''),
                monthly_potential=analysis.get('monthly_potential', ''),
                automation_rate=analysis.get('automation_rate', ''),
                customer_acquisition=analysis.get('customer_acquisition', ''),
                risks=analysis.get('risks', ''),
                action_plan=analysis.get('action_plan', ''),
                tags=analysis.get('tags', []),
                source_url=item.get('url', ''),
                research_links=[
                    item.get('url', ''),
                    f"https://www.google.com/search?q={item.get('title', '')}",
                    f"https://www.google.com/search?q={item.get('title', '')}+competitors+alternatives"
                ],
                created_at=datetime.now()
            )
            
        except Exception as e:
            print(f"Error analyzing item: {e}")
            if DEBUG:
                import traceback
                traceback.print_exc()
            return None
        finally:
            if own_session:
                await client.close()

    def analyze(self, item: Dict[str, Any]) -> Optional[Opportunity]:
        """同步兼容接口：内部调用异步实现"""
        return asyncio.run(self.analyze_async(item))
    
    def _build_prompt(self, item: Dict[str, Any]) -> str:
        """构建分析提示词（一人公司 + Agent 军团视角）"""
        return f"""
你是一人公司成功创业者，擅长用 AI Agent 军团自动化业务。请分析这个机会：

标题：{item.get('title', '')}
来源：{item.get('source', 'unknown').upper()}
链接：{item.get('url', '')}
{f"描述：{item.get('description', '')[:500]}" if item.get('description') else ""}
{f"热度：{item.get('score', 0)} 分" if item.get('score') else ""}

请从**一人公司 + Agent 军团**角度分析，判断是否适合 1 人干到年入百万美金：

输出严格的 JSON 格式：
{{
    "score": 75,
    "summary": "50 字一句话：为什么适合/不适合一人公司",
    "description": "100 字：做什么、解决什么问题、目标用户",
    "solo_feasibility": "150 字：为什么适合一人公司 + Agent 完成，哪些工作可自动化",
    "agent_roles": ["内容 Agent", "客服 Agent", "开发 Agent", "营销 Agent"],
    "startup_cost": "<$1k 或 $1-5k 或 $5-20k 或 >$20k",
    "time_to_revenue": "<7 天 或 30 天 或 90 天 或 >90 天",
    "revenue_model": "订阅 或 一次性 或 联盟 或 广告 或 API 收费",
    "monthly_potential": "$1-10k 或 $10-50k 或 $50k+",
    "automation_rate": "50% 或 70% 或 90%+",
    "customer_acquisition": "SEO 或 社交媒体 或 付费广告 或 联盟 或 Product Hunt",
    "risks": "50 字主要风险",
    "action_plan": "50 字第一步做什么",
    "tags": ["SaaS", "AI", "B2B", "内容", "自动化"]
}}

评分标准（一人公司视角）：
- 90-100: 启动成本低 (<$5k) + 30 天见钱 + 可 90% 自动化 + 月入$50k+ 潜力 → 立即开干
- 70-89: 一人能完成 + 有明确获客渠道 + 月入$10-50k 潜力 → 深入研究
- 50-69: 需要验证 + 可能需要外包部分工作 → 保持关注
- 0-49: 需要团队/重资金/难自动化 → 跳过
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
    
    async def batch_analyze_async(self, items: list, min_score: int = 60) -> list:
        """
        批量分析
        
        Args:
            items: 项目列表
            min_score: 最低分数阈值
            
        Returns:
            机会列表（按分数排序）
        """
        opportunities = []
        total = len(items)
        semaphore = asyncio.Semaphore(5)
        timeout = aiohttp.ClientTimeout(total=BAILIAN_TIMEOUT)

        async def analyze_one(item: Dict[str, Any], session: aiohttp.ClientSession) -> Optional[Opportunity]:
            async with semaphore:
                if DEBUG:
                    print(f"Analyzing: {item.get('title', '')[:50]}...")
                return await self.analyze_async(item, session=session)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks = [asyncio.create_task(analyze_one(item, session)) for item in items]
            completed = 0
            for task in asyncio.as_completed(tasks):
                opp = await task
                completed += 1
                print(f"Progress: {completed}/{total}")
                if opp and opp.score >= min_score:
                    opportunities.append(opp)
        
        # 按分数排序
        return sorted(opportunities, key=lambda x: x.score, reverse=True)

    def batch_analyze(self, items: list, min_score: int = 60) -> list:
        """同步兼容接口：内部调用异步实现"""
        return asyncio.run(self.batch_analyze_async(items, min_score=min_score))
