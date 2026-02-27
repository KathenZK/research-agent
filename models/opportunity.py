#!/usr/bin/env python3
"""机会数据模型"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Opportunity:
    """产品机会"""
    
    id: str
    title: str
    source: str  # hn/ph/appstore/xiaohongshu
    url: str
    score: int = 0  # 0-100 机会评分
    summary: str = ""  # AI 生成的摘要
    suggestion: str = ""  # AI 生成的建议方向
    tags: list = field(default_factory=list)  # 标签
    created_at: datetime = field(default_factory=datetime.now)
    
    # 新增详细分析字段
    description: str = ""  # 项目详细介绍（做什么的）
    market_size: str = ""  # TAM/SAM/SOM 分析
    business_model: str = ""  # 盈利模式
    competitors: str = ""  # 竞争对手
    barriers: str = ""  # 进入壁垒
    risks: str = ""  # 风险评估
    suggestion: str = ""  # 投资建议
    tags: list = field(default_factory=list)  # 标签
    source_url: str = ""  # 原始链接（在哪看到的）
    research_links: list = field(default_factory=list)  # 研究链接
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "score": self.score,
            "summary": self.summary,
            "description": self.description,
            "market_size": self.market_size,
            "business_model": self.business_model,
            "competitors": self.competitors,
            "barriers": self.barriers,
            "risks": self.risks,
            "suggestion": self.suggestion,
            "tags": self.tags,
            "source_url": self.source_url,
            "research_links": self.research_links,
            "created_at": self.created_at.isoformat()
        }
    
    def to_message(self) -> str:
        """生成飞书消息"""
        emoji = {
            "hn": "🔥",
            "ph": "🚀",
            "twitter": "𝕏",
            "36kr": "📰",
            "huxiu": "🐯",
            "crunchbase": "💰",
            "appstore": "📱",
            "xiaohongshu": "📕"
        }.get(self.source, "💡")
        
        return f"""
{emoji} 【机会 #{self.id}】评分：{self.score}/100

📌 {self.title}
🔗 来源：{self.source.upper()} | {self.url}

📖 项目介绍
{self.description if self.description else self.summary}

📊 市场规模
{self.market_size if self.market_size else "待分析"}

💰 盈利模式
{self.business_model if self.business_model else "待分析"}

🏆 竞争格局
{self.competitors if self.competitors else "待分析"}

🚧 进入壁垒
{self.barriers if self.barriers else "待分析"}

⚠️ 风险评估
{self.risks if self.risks else "待分析"}

💡 投资建议
{self.suggestion}

{f"🏷️ 标签：{', '.join(self.tags)}" if self.tags else ""}
---
生成时间：{self.created_at.strftime("%Y-%m-%d %H:%M")}
""".strip()
