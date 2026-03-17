#!/usr/bin/env python3
"""阿里百炼 API 分析器 -- 两阶段分析架构

Call 1 (factual assessment, temperature 0.1): 纯事实评分，只基于输入信息。
Call 2 (strategic planning, temperature 0.4): 仅对 Call 1 得分 >= 65 的候选，
  结合 enrichment 证据做落地规划。
"""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional
from datetime import datetime

import aiohttp

from config import BAILIAN_API_KEY, BAILIAN_MODEL, BAILIAN_ENDPOINT, DEBUG, BAILIAN_TIMEOUT
from models.opportunity import Opportunity

CALL2_SCORE_THRESHOLD = 65


class BailianAnalyzer:
    """阿里百炼大模型分析器（两阶段架构）"""

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or BAILIAN_API_KEY
        self.model = model or BAILIAN_MODEL
        self.endpoint = BAILIAN_ENDPOINT

        if not self.api_key:
            raise ValueError("BAILIAN_API_KEY not configured")

    async def analyze_async(
        self,
        item: Dict[str, Any],
        session: Optional[aiohttp.ClientSession] = None,
        enrichment_context: str = "",
    ) -> Optional[Opportunity]:
        """Two-phase analysis: factual assessment then strategic planning."""
        own_session = session is None
        timeout = aiohttp.ClientTimeout(total=BAILIAN_TIMEOUT)
        client = session or aiohttp.ClientSession(timeout=timeout)

        try:
            call1 = await self._call_factual(item, client)
            if not call1:
                return None

            score = call1.get('score', 0)
            if score < CALL2_SCORE_THRESHOLD:
                return self._build_opportunity(item, call1, {})

            call2 = await self._call_strategic(item, call1, client, enrichment_context)
            return self._build_opportunity(item, call1, call2 or {})

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
        """同步兼容接口"""
        return asyncio.run(self.analyze_async(item))

    async def _call_factual(self, item: Dict[str, Any], session: aiohttp.ClientSession) -> Optional[Dict]:
        """Call 1: factual assessment -- low temperature, strict facts only."""
        prompt = self._build_factual_prompt(item)
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": "你是一个产品机会分析专家。只基于提供的信息评估商业机会。如果信息不足请写 'unknown'。输出严格的 JSON 格式。\n\n" + prompt,
                }
            ],
            "max_tokens": 800,
            "temperature": 0.1,
        }
        return await self._send_request(payload, session)

    async def _call_strategic(
        self,
        item: Dict[str, Any],
        factual: Dict[str, Any],
        session: aiohttp.ClientSession,
        enrichment_context: str = "",
    ) -> Optional[Dict]:
        """Call 2: strategic planning -- grounded in enrichment evidence."""
        prompt = self._build_strategic_prompt(item, factual, enrichment_context)
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": "你是一人公司创业顾问。基于提供的市场证据做落地规划。不要凭空编造社区名称或用户来源。输出严格的 JSON 格式。\n\n" + prompt,
                }
            ],
            "max_tokens": 800,
            "temperature": 0.4,
        }
        return await self._send_request(payload, session)

    async def _send_request(self, payload: Dict, session: aiohttp.ClientSession) -> Optional[Dict]:
        """Send request to Bailian API with retry logic."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        max_retries = 3
        base_delay = 2

        for attempt in range(max_retries):
            try:
                async with session.post(self.endpoint, headers=headers, json=payload) as response:
                    if response.status == 429:
                        delay = base_delay * (2 ** attempt)
                        print(f"Rate limited, retrying in {delay}s...")
                        await asyncio.sleep(delay)
                        continue

                    if response.status != 200:
                        response_text = await response.text()
                        print(f"API Error: {response.status}")
                        if DEBUG:
                            print(f"Response: {response_text[:500]}")
                        return None

                    result = await response.json()
                    break
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

        if DEBUG:
            print(f"API Response: {json.dumps(result, indent=2)}")

        content = ''
        if 'content' in result and isinstance(result['content'], list) and len(result['content']) > 0:
            content = result['content'][0].get('text', '')
        elif 'choices' in result:
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '')

        if DEBUG:
            print(f"AI Response: {content}")

        return self._parse_json(content)

    def _build_factual_prompt(self, item: Dict[str, Any]) -> str:
        source_quality = item.get('source_quality', '')
        source_hint = f"\n信号类型：{source_quality}（pain=真实痛点, discussion=社区讨论, hype=热度新闻, story=成功案例, news=媒体报道）" if source_quality else ""

        return f"""请基于以下信息评估这个商业机会（只基于提供的信息，不确定就写 unknown）：

标题：{item.get('title', '')}
来源：{item.get('source', 'unknown').upper()}{source_hint}
链接：{item.get('url', '')}
{f"描述：{item.get('description', '')[:500]}" if item.get('description') else ""}
{f"热度：{item.get('score', 0)} 分" if item.get('score') else ""}

评分标准（一人公司视角）：
- 90-100: 信号明确指向真实用户痛点 + 领域足够窄 + 可被单人自动化 → 立即开干
- 70-89: 痛点方向清晰 + 有一定付费意愿信号 + 一人能完成 → 深入研究
- 50-69: 问题可能存在，但付费路径或切口证据不够硬 → 暂不投入
- 0-49: 需要团队/重资金/难自动化/红海泛品类/正面撞大厂 → 直接跳过

额外规则：
- 遇到红海品类（项目管理、白噪音、通用 AI 编程助手、泛内容工具）必须显著降分
- 正面硬刚大厂/平台原生功能时必须降分
- 信号类型为 pain 时可以适当加分，为 hype/story/news 时需要更严格

输出严格的 JSON 格式：
{{
    "score": 75,
    "summary": "50 字一句话：为什么适合/不适合一人公司",
    "description": "100 字：做什么、解决什么问题、目标用户",
    "tags": ["SaaS", "AI", "B2B", "内容", "自动化"],
    "risks": "50 字：为什么这个机会可能不值得做（用创业决策语言）",
    "startup_cost": "<$1k 或 $1-5k 或 $5-20k 或 >$20k 或 unknown",
    "automation_rate": "50% 或 70% 或 90%+ 或 unknown"
}}"""

    def _build_strategic_prompt(
        self,
        item: Dict[str, Any],
        factual: Dict[str, Any],
        enrichment_context: str = "",
    ) -> str:
        enrichment_block = ""
        if enrichment_context:
            enrichment_block = f"""
--- 市场证据（通过自动搜索收集，请基于这些真实证据规划） ---
{enrichment_context}
--- 市场证据结束 ---
"""

        return f"""一个候选机会已通过初筛（{factual.get('score', 0)} 分），请基于市场证据做一人公司落地规划：

标题：{item.get('title', '')}
来源：{item.get('source', 'unknown').upper()}
链接：{item.get('url', '')}
初筛摘要：{factual.get('summary', '')}
初筛描述：{factual.get('description', '')}
初筛风险：{factual.get('risks', '')}
{enrichment_block}
请从**一人公司 + Agent 军团**角度做落地规划：

规则：
- `customer_acquisition` 必须基于上面市场证据里出现过的社区/平台，不要编造
- `action_plan` 要写成 7-14 天内可收费的最小 wedge，不要写"先做 MVP 再迭代"
- 如果市场证据显示竞品很多（>5），必须说明切口如何避开
- 如果市场证据显示痛点帖少（<2），必须在 risks 里标注证据不足

输出严格的 JSON 格式：
{{
    "solo_feasibility": "150 字：为什么适合一人公司 + Agent 完成",
    "agent_roles": ["内容 Agent", "客服 Agent", "开发 Agent"],
    "time_to_revenue": "<7 天 或 14 天 或 30 天 或 90 天 或 >90 天",
    "revenue_model": "订阅 或 一次性 或 联盟 或 API 收费",
    "monthly_potential": "$1-10k 或 $10-50k 或 $50k+",
    "customer_acquisition": "前 20 个用户从哪里来（基于市场证据，写具体社区/帖子/评论者）",
    "action_plan": "7-14 天内可收费的最小 wedge 和首单动作"
}}"""

    def _build_opportunity(
        self,
        item: Dict[str, Any],
        factual: Dict[str, Any],
        strategic: Dict[str, Any],
    ) -> Opportunity:
        return Opportunity(
            id=item['id'],
            title=item['title'],
            source=item.get('source', 'unknown'),
            url=item.get('url', ''),
            score=factual.get('score', 50),
            summary=factual.get('summary', ''),
            description=factual.get('description', ''),
            solo_feasibility=strategic.get('solo_feasibility', ''),
            agent_roles=strategic.get('agent_roles', []),
            startup_cost=factual.get('startup_cost', ''),
            time_to_revenue=strategic.get('time_to_revenue', ''),
            revenue_model=strategic.get('revenue_model', ''),
            monthly_potential=strategic.get('monthly_potential', ''),
            automation_rate=factual.get('automation_rate', ''),
            customer_acquisition=strategic.get('customer_acquisition', ''),
            risks=factual.get('risks', ''),
            action_plan=strategic.get('action_plan', ''),
            tags=factual.get('tags', []),
            source_url=item.get('url', ''),
            research_links=[
                item.get('url', ''),
                f"https://www.google.com/search?q={item.get('title', '')}",
                f"https://www.google.com/search?q={item.get('title', '')}+competitors+alternatives",
            ],
            created_at=datetime.now(),
        )

    def _parse_json(self, content: str) -> Optional[Dict]:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return None

    async def batch_analyze_async(
        self,
        items: list,
        min_score: int = 60,
        enrichment_map: Optional[Dict[str, Any]] = None,
    ) -> list:
        """批量分析（两阶段架构 + enrichment 注入）"""
        enrichment_map = enrichment_map or {}
        opportunities = []
        total = len(items)
        semaphore = asyncio.Semaphore(5)
        timeout = aiohttp.ClientTimeout(total=BAILIAN_TIMEOUT)

        async def analyze_one(item: Dict[str, Any], session: aiohttp.ClientSession) -> Optional[Opportunity]:
            async with semaphore:
                if DEBUG:
                    print(f"Analyzing: {item.get('title', '')[:50]}...")
                item_id = str(item.get('id', ''))
                enrichment = enrichment_map.get(item_id)
                enrichment_context = ""
                if enrichment and hasattr(enrichment, 'to_prompt_context'):
                    enrichment_context = enrichment.to_prompt_context()
                elif isinstance(enrichment, str):
                    enrichment_context = enrichment
                return await self.analyze_async(item, session=session, enrichment_context=enrichment_context)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks = [asyncio.create_task(analyze_one(item, session)) for item in items]
            completed = 0
            for task in asyncio.as_completed(tasks):
                opp = await task
                completed += 1
                print(f"Progress: {completed}/{total}")
                if opp and opp.score >= min_score:
                    opportunities.append(opp)

        return sorted(opportunities, key=lambda x: x.score, reverse=True)

    def batch_analyze(self, items: list, min_score: int = 60) -> list:
        """同步兼容接口"""
        return asyncio.run(self.batch_analyze_async(items, min_score=min_score))
