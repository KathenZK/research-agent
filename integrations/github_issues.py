#!/usr/bin/env python3
"""GitHub Issues 集成 -- 自动创建 GitHub Issue"""

from typing import List

import requests

from config import GITHUB_TOKEN, GITHUB_REPO
from models.opportunity import Opportunity
from screening.phase2 import _signal_strength_label


def create_github_issues(opportunities: List[Opportunity]):
    """自动创建 GitHub Issue"""
    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN not configured, skipping GitHub issues")
        print("   Configure: echo 'ghp_xxx' > ~/.github_token")
        return

    url = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    created = 0
    for opp in opportunities[:3]:
        try:
            signal_label = _signal_strength_label(getattr(opp, 'phase2_adjusted_score', None) or opp.score)
            validation_action = getattr(opp, 'phase2_decision_label', '') or opp.decision_label()
            data = {
                "title": f"{opp.title[:50]} - {validation_action}",
                "body": f"""## 机会评估

- **机会信号**: {signal_label}
- **验证动作**: {validation_action}
- **来源**: {opp.source.upper()}
- **发现日期**: {opp.created_at.strftime('%Y-%m-%d')}

## 项目介绍

{opp.description if opp.description else opp.summary}

## 一人公司可行性

{opp.solo_feasibility if opp.solo_feasibility else '待分析'}

## 商业模式

- 启动成本：{opp.startup_cost or '待分析'}
- 多久见钱：{opp.time_to_revenue or '待分析'}
- 月收入潜力：{opp.monthly_potential or '待分析'}
- 自动化率：{opp.automation_rate or '待分析'}

## 第一步

{opp.action_plan if opp.action_plan else '待分析'}

---
*Auto-created by Research Agent*""",
                "labels": ["opportunity", "researching", "ai"]
            }

            response = requests.post(url, headers=headers, json=data, timeout=30)

            if response.status_code == 201:
                issue_url = response.json().get('html_url', '')
                print(f"Created Issue: {issue_url}")
                created += 1
            else:
                print(f"Failed: {response.status_code} - {response.text[:100]}")

        except Exception as e:
            print(f"Error: {e}")

    print(f"Created {created}/3 GitHub issues")
