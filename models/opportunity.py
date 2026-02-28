#!/usr/bin/env python3
"""机会数据模型 - 一人公司视角"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


@dataclass
class Opportunity:
    """产品机会（一人公司 + Agent 军团视角）"""
    
    id: str
    title: str
    source: str
    url: str
    score: int = 0
    summary: str = ""
    description: str = ""
    
    # 一人公司专属字段
    solo_feasibility: str = ""
    agent_roles: List[str] = field(default_factory=list)
    startup_cost: str = ""
    time_to_revenue: str = ""
    revenue_model: str = ""
    monthly_potential: str = ""
    automation_rate: str = ""
    customer_acquisition: str = ""
    risks: str = ""
    action_plan: str = ""
    
    # 通用字段
    tags: List[str] = field(default_factory=list)
    source_url: str = ""
    research_links: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "score": self.score,
            "summary": self.summary,
            "description": self.description,
            "solo_feasibility": self.solo_feasibility,
            "agent_roles": self.agent_roles,
            "startup_cost": self.startup_cost,
            "time_to_revenue": self.time_to_revenue,
            "revenue_model": self.revenue_model,
            "monthly_potential": self.monthly_potential,
            "automation_rate": self.automation_rate,
            "customer_acquisition": self.customer_acquisition,
            "risks": self.risks,
            "action_plan": self.action_plan,
            "tags": self.tags,
            "source_url": self.source_url,
            "research_links": self.research_links,
            "created_at": self.created_at.isoformat()
        }
    
    def to_message(self) -> str:
        """生成飞书消息（一人公司格式）"""
        emoji = {
            "hn": "🔥",
            "ph": "🚀",
            "twitter": "𝕏",
            "36kr": "📰",
            "huxiu": "🐯",
            "tiehan": "💎",
            "crunchbase": "💰",
        }.get(self.source, "💡")
        
        return f"""
{emoji} 【一人公司机会 #{self.id}】评分：{self.score}/100

📌 {self.title}
🔗 来源：{self.source.upper()} | {self.url}

📖 项目介绍
{self.description if self.description else self.summary}

👤 一人公司可行性
{self.solo_feasibility if self.solo_feasibility else "待分析"}

🤖 需要的 Agent 角色
{', '.join(self.agent_roles) if self.agent_roles else "待分析"}

💰 启动成本：{self.startup_cost or "待分析"}
⏱️ 多久见钱：{self.time_to_revenue or "待分析"}
📈 收入模式：{self.revenue_model or "待分析"}
🎯 月收入潜力：{self.monthly_potential or "待分析"}
⚙️ 自动化率：{self.automation_rate or "待分析"}
📢 获客渠道：{self.customer_acquisition or "待分析"}

⚠️ 风险
{self.risks if self.risks else "待分析"}

🚀 第一步
{self.action_plan if self.action_plan else "待分析"}

{f"🏷️ 标签：{', '.join(self.tags)}" if self.tags else ""}
---
生成时间：{self.created_at.strftime("%Y-%m-%d %H:%M")}
""".strip()
