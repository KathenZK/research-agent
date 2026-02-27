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
{emoji} 【机会 #{self.id}】

📌 标题：{self.title}
🔗 来源：{self.source.upper()}
📊 评分：{self.score}/100
🔗 链接：{self.url}

📝 摘要：
{self.summary}

💡 建议方向：
{self.suggestion}

{f"🏷️ 标签：{', '.join(self.tags)}" if self.tags else ""}
---
生成时间：{self.created_at.strftime("%Y-%m-%d %H:%M")}
""".strip()
