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

    def display_score(self) -> int:
        return int(getattr(self, "phase2_adjusted_score", self.score) or 0)

    def grade_label(self) -> str:
        score = self.display_score()
        if score >= 86:
            return "A"
        if score >= 78:
            return "B"
        if score >= 68:
            return "C"
        return "D"

    def signal_strength_label(self) -> str:
        return {
            "A": "高",
            "B": "中高",
            "C": "待验证",
            "D": "弱",
        }[self.grade_label()]

    def decision_label(self) -> str:
        custom = getattr(self, "phase2_decision_label", "")
        if custom:
            return custom
        mapping = {
            "A": "立即验证",
            "B": "保留观察",
            "C": "暂不投入",
            "D": "直接过滤",
        }
        return mapping[self.grade_label()]
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "score": self.score,
            "display_score": self.display_score(),
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
            "created_at": self.created_at.isoformat(),
            "phase2_raw_score": getattr(self, "phase2_raw_score", self.score),
            "phase2_evidence_score": getattr(self, "phase2_evidence_score", 0),
            "phase2_verdict": getattr(self, "phase2_verdict", ""),
            "phase2_decision_label": getattr(self, "phase2_decision_label", ""),
            "phase2_wedge": getattr(self, "phase2_wedge", ""),
            "phase2_filtered_reason": getattr(self, "phase2_filtered_reason", ""),
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

        wedge = getattr(self, "phase2_wedge", f"围绕「{self.title}」切一个最窄且可先收钱的工作流")
        solo_logic = getattr(self, "phase2_solo_logic", self.solo_feasibility or "待分析")
        first_users = getattr(self, "phase2_first_users", self.customer_acquisition or "待分析")
        paid_mvp = getattr(self, "phase2_paid_mvp", self.action_plan or "待分析")
        risk_logic = getattr(self, "phase2_not_crushed", self.risks or "待分析")
        
        return f"""
{emoji} 【一人公司机会 #{self.id}】{self.decision_label()} | 机会信号 {self.signal_strength_label()}

📌 切入 wedge：{wedge}
🔗 来源：{self.source.upper()} | {self.url}

📖 项目介绍
{self.description if self.description else self.summary}

👤 一人公司可行性
{solo_logic}

🤖 需要的 Agent 角色
{', '.join(self.agent_roles) if self.agent_roles else "待分析"}

💰 启动成本：{self.startup_cost or "待分析"}
⏱️ 多久见钱：{self.time_to_revenue or "待分析"}
📈 收入模式：{self.revenue_model or "待分析"}
🎯 月收入潜力：{self.monthly_potential or "待分析"}
⚙️ 自动化率：{self.automation_rate or "待分析"}
📢 前 20 个用户：{first_users}

⚠️ 风险
{risk_logic}

🚀 第一步
{paid_mvp}

{f"🏷️ 标签：{', '.join(self.tags)}" if self.tags else ""}
---
生成时间：{self.created_at.strftime("%Y-%m-%d %H:%M")}
""".strip()
