#!/usr/bin/env python3
"""每日报告生成 -- Phase 1 screener、Top10 报告和控制台输出"""

import os
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import DATA_DIR
from models.opportunity import Opportunity
from screening.constants import (
    FINAL_ACTION_LANDING_PAGE, FINAL_ACTION_7DAY_MVP, FINAL_ACTION_DROP,
)
from screening.phase2 import (
    ScreeningAssessment,
    _build_phase2_assessment, _bucket_phase2_candidates,
    _primary_candidate, _unique_candidate_card_lines,
    _decision_label, _signal_strength_label,
    _phase2_signal_summary, _final_conclusion, _filtered_reason,
    _not_worth_doing_lines, _daily_rule_adjustment,
    _opportunity_what, _opportunity_how, _opportunity_profit,
    _phase2_evidence_label,
    _who_pays_in_14_days, _first_20_users_source,
    _why_solo_buildable, _why_not_crushed,
    _smallest_paid_mvp, _high_frequency_scenario,
    _current_alternative, _why_existing_solution_bad,
    _why_now_worth_doing, _why_fit_for_user,
    _do_not_scale_boundary,
)


def _agent_reach_health_summary_lines() -> List[str]:
    health_summary_lines = []
    health_file = os.path.join(DATA_DIR, 'agent_reach_health.json')
    if not os.path.exists(health_file):
        return health_summary_lines

    try:
        h = json.load(open(health_file, 'r', encoding='utf-8'))
        platforms = h.get('platforms', {})
        health_summary_lines.append('## 每日健康摘要（Agent Reach）')
        for name in ('x', 'youtube', 'reddit'):
            p = platforms.get(name, {})
            healthy = bool(p.get('healthy', False))
            failures = int(p.get('failures', 0) or 0)
            cooldown = p.get('cooldown_until') or ''
            status = '可用' if healthy else '不可用'
            if cooldown:
                status += f'（熔断至 {cooldown}）'
            health_summary_lines.append(f'- {name}: {status} | 连续失败: {failures}')
        health_summary_lines.append('')
    except Exception as e:
        health_summary_lines.append('## 每日健康摘要（Agent Reach）')
        health_summary_lines.append(f'- 读取失败: {e}')
        health_summary_lines.append('')
    return health_summary_lines


def save_phase1_report(opportunities: List[Opportunity], assessments: Optional[dict] = None, run_notes: Optional[List[str]] = None):
    """输出 Phase 1 solo-venture screener（markdown + latest）。"""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = os.path.join(DATA_DIR, f'phase1_report_{ts}.md')
    latest_file = os.path.join(DATA_DIR, 'latest_phase1.md')

    assessments = assessments or {opp.id: _build_phase2_assessment(opp) for opp in opportunities}
    kept, watchlist, dropped = _bucket_phase2_candidates(opportunities, assessments)
    primary, remaining_watchlist = _primary_candidate(kept, watchlist)
    rule_adjustment = _daily_rule_adjustment(opportunities, assessments)
    verdict_counts = {'keep': 0, 'watch': 0, 'drop': 0}
    for opp in opportunities:
        verdict = assessments[opp.id].verdict
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
    lines = [
        '# Phase 1 Solo Venture Screener',
        '',
        f'- 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'- 候选池规模: {len(opportunities)}',
        f'- 结论: {_final_conclusion(primary, assessments[primary.id]) if primary else "丢弃。今日没有值得继续验证的切口。"}',
        f'- 决策分布: keep {verdict_counts["keep"]} / watch {verdict_counts["watch"]} / drop {verdict_counts["drop"]}',
        '',
    ]
    lines.extend(_agent_reach_health_summary_lines())
    if run_notes:
        lines.extend(['## Run Notes', *[f'- {note}' for note in run_notes], ''])
    lines.extend([
        '## 今日最该调整的一条筛选规则',
        f'- 建议: {rule_adjustment["suggestion"]}',
        f'- 依据: {rule_adjustment["evidence"]}',
        '',
    ])

    if primary:
        assessment = assessments[primary.id]
        lines.extend(_unique_candidate_card_lines(primary, assessment))
        lines.extend([
            '## 决策依据',
            f'- 机会信号: **{_signal_strength_label(primary.score)}**',
            f'- 证据摘要: **{_phase2_signal_summary(primary, assessment)}**',
            f'- 14 天内谁会先付钱: {_who_pays_in_14_days(primary, assessment)}',
            f'- 一人可行性: {_why_solo_buildable(primary, assessment)}',
            '',
        ])
    else:
        top_gap_lines = []
        for opp in dropped[:2]:
            reason = _filtered_reason(opp, assessments.get(opp.id))
            if reason:
                top_gap_lines.append(f'- {opp.title}: {reason}')
        lines.extend([
            '## 今日唯一候选',
            f'- 验证动作（landing page / 7 day MVP / 丢弃）: **{FINAL_ACTION_DROP}**',
            '- 最终结论: 丢弃。今天没有出现值得继续验证的唯一候选。',
            '',
            '## 为什么今天没有候选',
            '缺的不是更高的分数，而是一个同时满足"14 天可收钱 + 首批用户名单明确 + 不正面撞大厂主战场"的切口。',
            '',
        ])
        lines.extend(top_gap_lines)
        if top_gap_lines:
            lines.append('')

    if remaining_watchlist:
        lines.extend([
            '## 继续观察',
            '以下机会仍可作为候选池样本，但今天不升级为唯一候选：',
            '',
        ])
        for idx, opp in enumerate(remaining_watchlist, 1):
            assessment = assessments[opp.id]
            lines.extend([
                f'### {idx}. {opp.title}',
                f'- 验证动作（landing page / 7 day MVP / 丢弃）: **{_decision_label(opp.score, assessment.verdict)}**',
                f'- 机会信号: **{_signal_strength_label(opp.score)}**',
                f'- 证据摘要: {_phase2_signal_summary(opp, assessment)}',
                f'- 最终结论: {_final_conclusion(opp, assessment)}',
                f'- 链接: {opp.url}',
                '',
            ])

    lines.extend([
        '## 今天不值得做',
        '以下 3-5 条是今天明确不该继续投入的伪机会判断：',
        '',
    ])

    not_worth_lines = _not_worth_doing_lines(dropped, assessments)
    if not_worth_lines:
        lines.extend(not_worth_lines)
        lines.append('')
    else:
        lines.extend([
            '- 无更多可列出的过滤样本。',
            '',
        ])

    content = '\n'.join(lines)
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(content)
    with open(latest_file, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f'Phase 1 report saved: {report_file}')


def save_top10_report(opportunities: List[Opportunity]):
    """输出 Top10 决策报告（markdown + latest）"""
    if not opportunities:
        return

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = os.path.join(DATA_DIR, f'top10_report_{ts}.md')
    latest_file = os.path.join(DATA_DIR, 'latest_top10.md')

    health_summary_lines = _agent_reach_health_summary_lines()

    top = opportunities[:10]
    lines = [
        '# Top 10 一人公司机会日报',
        '',
        f'- 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'- 样本数量: {len(opportunities)}',
        '',
    ]
    lines.extend(health_summary_lines)

    for idx, o in enumerate(top, 1):
        lines += [
            f'## {idx}. {o.title}',
            f'- 机会信号: **{_signal_strength_label(o.display_score())}**',
            f'- 验证动作（landing page / 7 day MVP / 丢弃）: **{o.decision_label()}**',
            f'- 来源: `{o.source}`',
            f'- 链接: {o.url}',
            '',
            f'- 切口名称: {getattr(o, "phase2_deliverable", "") or _opportunity_what(o)}',
            f'- 目标用户: {getattr(o, "phase2_target_user", "") or "待补充"}',
            f'- 高频场景: {getattr(o, "phase2_trigger_event", "") or "待补充"}',
            f'- 6 周最小收费版本: {getattr(o, "phase2_paid_mvp", "") or _opportunity_how(o)}',
            f'- 最终结论: {getattr(o, "phase2_final_conclusion", "") or o.decision_label()}',
            '',
            f'### 关键指标',
            f'- 一人可行性: {o.solo_feasibility or "待分析"}',
            f'- 启动成本: {o.startup_cost or "待分析"}',
            f'- 见钱周期: {o.time_to_revenue or "待分析"}',
            f'- 收入模式: {o.revenue_model or "待分析"}',
            f'- 月潜力: {o.monthly_potential or "待分析"}',
            '',
        ]

    content = '\n'.join(lines)
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(content)
    with open(latest_file, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f'Report saved: {report_file}')


def print_phase1_results(
    kept: List[Opportunity],
    watchlist: List[Opportunity],
    dropped: List[Opportunity],
    total_count: int,
    assessments: Optional[dict] = None,
    rule_adjustment: Optional[Dict[str, str]] = None,
):
    """打印 Phase 1 screener 摘要。"""
    assessments = assessments or {}
    rule_adjustment = rule_adjustment or _daily_rule_adjustment(kept + watchlist + dropped, assessments)
    primary, remaining_watchlist = _primary_candidate(kept, watchlist)
    print("\n" + "=" * 80)
    print(f"Phase 1 Solo Venture Screener | 候选池 {total_count} 条")
    print("=" * 80 + "\n")
    print(f"今日最该调整的一条筛选规则：{rule_adjustment['suggestion']}")
    print(f"依据：{rule_adjustment['evidence']}\n")

    if primary:
        assessment = assessments.get(primary.id)
        print(f"今日唯一候选 | {_decision_label(primary.score, assessment.verdict if assessment else None)} | 信号 {_signal_strength_label(primary.score)}")
        if assessment:
            print(f"切口名称：{assessment.deliverable}")
            print(f"目标用户：{assessment.target_user}")
            print(f"高频场景：{_high_frequency_scenario(primary, assessment)}")
            print(f"当前替代方案：{_current_alternative(primary, assessment)}")
            print(f"为什么现有方案不好：{_why_existing_solution_bad(primary, assessment)}")
            print(f"为什么现在值得做：{_why_now_worth_doing(primary, assessment)}")
            print(f"为什么适合用户：{_why_fit_for_user(primary, assessment)}")
            print(f"6 周最小收费版本：{_smallest_paid_mvp(primary, assessment)}")
            print(f"首批 20 用户从哪里来：{_first_20_users_source(primary, assessment)}")
            print(f"不该做大的边界：{_do_not_scale_boundary(primary, assessment)}")
            print(f"最终结论：{_final_conclusion(primary, assessment)}")
        print(f"链接：{primary.url}")
    else:
        print("今日唯一候选 | 丢弃")
        for opp in dropped[:2]:
            assessment = assessments.get(opp.id)
            print(f"- {opp.title}：{_filtered_reason(opp, assessment)}")

    if remaining_watchlist:
        print("\n继续观察：")
        for idx, opp in enumerate(remaining_watchlist, 1):
            assessment = assessments.get(opp.id)
            verdict = assessment.verdict if assessment else None
            summary = _phase2_signal_summary(opp, assessment) if assessment else '证据待补充'
            print(f"{idx}. {_decision_label(opp.score, verdict)} | 信号 {_signal_strength_label(opp.score)} | {opp.title}")
            print(f"   {summary}")
            print(f"   {_final_conclusion(opp, assessment)}")

    print("\n今天不值得做：")
    not_worth_lines = _not_worth_doing_lines(dropped, assessments)
    if not_worth_lines:
        for line in not_worth_lines:
            print(line)
    else:
        print("无更多可列出的过滤样本")
    print()


def print_results(opportunities: List[Opportunity]):
    """打印结果"""
    print("\n" + "="*80)
    print(f"发现 {len(opportunities)} 个产品机会")
    print("="*80 + "\n")

    for i, opp in enumerate(opportunities[:5], 1):
        print(f"#{i} [{opp.source.upper()}] {opp.decision_label()} | 信号：{_signal_strength_label(opp.display_score())}")
        print(f"   标题：{opp.title}")
        print(f"   链接：{opp.url}")
        print()
        print(f"   项目介绍")
        print(f"   {opp.description[:200] if opp.description else opp.summary[:200]}...")
        print()
        print(f"   一人公司可行性")
        print(f"   {opp.solo_feasibility[:150] if opp.solo_feasibility else '待分析'}...")
        print()
        print(f"   Agent 角色：{', '.join(opp.agent_roles) if opp.agent_roles else '待分析'}")
        print(f"   启动成本：{opp.startup_cost or '待分析'}")
        print(f"   多久见钱：{opp.time_to_revenue or '待分析'}")
        print(f"   收入模式：{opp.revenue_model or '待分析'}")
        print(f"   月收入潜力：{opp.monthly_potential or '待分析'}")
        print(f"   自动化率：{opp.automation_rate or '待分析'}")
        print(f"   获客渠道：{opp.customer_acquisition or '待分析'}")
        print()
        print(f"   风险")
        print(f"   {opp.risks[:150] if opp.risks else '待分析'}...")
        print()
        print(f"   第一步")
        print(f"   {opp.action_plan[:100] if opp.action_plan else '待分析'}...")
        print()
        print(f"   相关链接")
        print(f"   - 原始链接：{opp.source_url}")
        for link in opp.research_links[1:3]:
            print(f"   - {link}")
        print()
        print("-"*80 + "\n")
