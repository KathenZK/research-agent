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

额外硬规则：
- 遇到红海通用品类（如项目管理、白噪音、通用 AI 编程助手、通用语音转文字、泛内容工具）、正面硬刚大厂/平台原生功能、重实施/重交付/强定制机会时，必须显著降分；证据弱时宁可给低分，不要为了凑候选而给“保留观察”。
- 如果 14 天内无法看见首单路径、前 20 个用户来源只停留在“SEO / Product Hunt / 社媒”这种泛渠道词，也必须降分。
- `risks` 要写创业决策逻辑：这个机会最可能因为什么而不值得做，而不是泛泛列风险词。
- `action_plan` 要写成 7-14 天内可收费的最小 wedge，不要写“先做 MVP 再迭代”这种模板话。
- `customer_acquisition` 必须尽量具体到“前 20 个用户从哪里来”，例如某类帖子、某类评论者、某社区或某类客户名单。

输出严格的 JSON 格式：
{{
    "score": 75,
    "summary": "50 字一句话：为什么适合/不适合一人公司",
    "description": "100 字：做什么、解决什么问题、目标用户",
    "solo_feasibility": "150 字：为什么适合一人公司 + Agent 完成，哪些工作可自动化",
    "agent_roles": ["内容 Agent", "客服 Agent", "开发 Agent", "营销 Agent"],
    "startup_cost": "<$1k 或 $1-5k 或 $5-20k 或 >$20k",
    "time_to_revenue": "<7 天 或 14 天 或 30 天 或 90 天 或 >90 天",
    "revenue_model": "订阅 或 一次性 或 联盟 或 广告 或 API 收费",
    "monthly_potential": "$1-10k 或 $10-50k 或 $50k+",
    "automation_rate": "50% 或 70% 或 90%+",
    "customer_acquisition": "前 20 个用户从哪里来，写具体社区/帖子/评论者/客户名单，而不是泛渠道词",
    "risks": "50 字：为什么这个机会可能不值得做，用创业决策语言表达",
    "action_plan": "50 字：7-14 天内可收费的最小 wedge 和首单动作",
    "tags": ["SaaS", "AI", "B2B", "内容", "自动化"]
}}

评分标准（一人公司视角）：
- 90-100: 启动成本低 (<$5k) + 14 天内可见首单 + 可 90% 自动化 + 切口够窄，能避开大玩家主战场 → 立即开干
- 70-89: 一人能完成 + 前 20 个用户来源具体 + 有明确付费动作，但仍有一两个关键假设待验证 → 深入研究
- 50-69: 问题存在，但付费路径、切口或分发证据不够硬 → 暂不投入
- 0-49: 需要团队/重资金/难自动化/正面撞大厂原生功能/红海泛品类 → 直接跳过
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
