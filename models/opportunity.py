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
    business_model: str = ""  # 盈利模式
    competitors: str = ""  # 竞争对手
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
            "suggestion": self.suggestion,
            "tags": self.tags,
            "description": self.description,
            "business_model": self.business_model,
            "competitors": self.competitors,
            "source_url": self.source_url,
            "research_links": self.research_links,
            "created_at": self.created_at.isoformat()
        }
    
    def to_message(self) -> str:
        """生成飞书消息"""
        emoji = {
            "hn": "🔥",
            "ph": "🚀",
            "appstore": "📱",
            "xiaohongshu": "📕"
        }.get(self.source, "💡")
        
        return f"""
{emoji} 【机会 #{self.id}】评分：{self.score}/100

📌 {self.title}
🔗 来源：{self.source.upper()} | {self.url}

📖 项目介绍
{self.description if self.description else self.summary}

💰 盈利模式
{self.business_model if self.business_model else "待分析"}

🏆 竞争对手
{self.competitors if self.competitors else "待分析"}

💡 建议方向
{self.suggestion}

{f"🏷️ 标签：{', '.join(self.tags)}" if self.tags else ""}
---
生成时间：{self.created_at.strftime("%Y-%m-%d %H:%M")}
""".strip()
