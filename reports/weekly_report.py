#!/usr/bin/env python3
"""深筛周报生成"""

import os
import re
import json
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from config import DATA_DIR
from models.opportunity import Opportunity
from screening.constants import PHASE2_WATCH_MIN_SCORE
from screening.phase2 import (
    ScreeningAssessment,
    _build_phase2_assessment,
    _phase2_signal_summary, _pseudo_opportunity_type, _concise_drop_reason,
    _clean_text,
)


def _normalize_title(title: str) -> str:
    t = (title or '').lower()
    t = re.sub(r'https?://\S+', '', t)
    t = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _normalize_url(url: str) -> str:
    if not url:
        return ''
    try:
        u = urlparse(url.strip())
        scheme = (u.scheme or 'https').lower()
        netloc = (u.netloc or '').lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]
        path = (u.path or '/').rstrip('/') or '/'
        blocked_prefix = ('utm_', 'spm', 'from', 'source', 'ref', 'ref_src', 'fbclid', 'gclid', 'igshid', 'mkt_')
        clean_q = []
        for k, v in parse_qsl(u.query, keep_blank_values=False):
            if k.lower().startswith(blocked_prefix):
                continue
            clean_q.append((k, v))
        clean_q.sort(key=lambda kv: kv[0])
        query = urlencode(clean_q, doseq=True)
        return urlunparse((scheme, netloc, path, '', query, ''))
    except Exception:
        return (url or '').strip()


def _fingerprint_opportunity(opp: Opportunity) -> str:
    title_norm = _normalize_title(opp.title)
    canonical_url = _normalize_url(opp.url or opp.source_url or '')
    domain = ''
    try:
        domain = urlparse(canonical_url).netloc.lower()
    except Exception:
        pass
    raw = f"{title_norm[:160]}|{domain}|{canonical_url}"
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


def _snapshot_datetime_from_name(name: str) -> Optional[datetime]:
    match = re.match(r'^opportunities_(\d{8})_(\d{6})\.json$', name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1) + match.group(2), '%Y%m%d%H%M%S')
    except ValueError:
        return None


def _restore_opportunity_from_dict(data: Dict[str, Any]) -> Opportunity:
    created_at_raw = data.get('created_at')
    created_at = datetime.now()
    if isinstance(created_at_raw, str):
        try:
            created_at = datetime.fromisoformat(created_at_raw)
        except ValueError:
            created_at = datetime.now()

    opp = Opportunity(
        id=str(data.get('id', '')),
        title=data.get('title', '') or '',
        source=data.get('source', '') or '',
        url=data.get('url', '') or '',
        score=int(data.get('phase2_raw_score', data.get('score', 0)) or 0),
        summary=data.get('summary', '') or '',
        description=data.get('description', '') or '',
        solo_feasibility=data.get('solo_feasibility', '') or '',
        agent_roles=list(data.get('agent_roles', []) or []),
        startup_cost=data.get('startup_cost', '') or '',
        time_to_revenue=data.get('time_to_revenue', '') or '',
        revenue_model=data.get('revenue_model', '') or '',
        monthly_potential=data.get('monthly_potential', '') or '',
        automation_rate=data.get('automation_rate', '') or '',
        customer_acquisition=data.get('customer_acquisition', '') or '',
        risks=data.get('risks', '') or '',
        action_plan=data.get('action_plan', '') or '',
        tags=list(data.get('tags', []) or []),
        source_url=data.get('source_url', '') or '',
        research_links=list(data.get('research_links', []) or []),
        created_at=created_at,
    )
    for field_name in (
        'phase2_adjusted_score', 'phase2_decision_label', 'phase2_verdict',
        'phase2_wedge', 'phase2_who_pays', 'phase2_first_users',
        'phase2_solo_logic', 'phase2_not_crushed', 'phase2_paid_mvp',
        'phase2_target_user', 'phase2_trigger_event', 'phase2_deliverable',
        'phase2_current_alternative', 'phase2_why_existing_bad', 'phase2_why_now',
        'phase2_why_fit_for_user', 'phase2_boundary', 'phase2_final_conclusion',
        'phase2_filtered_reason', 'phase2_raw_score', 'phase2_evidence_score',
    ):
        if field_name in data:
            setattr(opp, field_name, data.get(field_name))
    return opp


def _load_snapshot_records(window_days: int = 7, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    ref_now = now or datetime.now()
    cutoff = ref_now - timedelta(days=max(1, window_days))
    snapshot_files: List[tuple[datetime, str]] = []
    if not os.path.exists(DATA_DIR):
        return []
    for name in os.listdir(DATA_DIR):
        snapshot_at = _snapshot_datetime_from_name(name)
        if not snapshot_at or snapshot_at < cutoff:
            continue
        snapshot_files.append((snapshot_at, os.path.join(DATA_DIR, name)))
    snapshot_files.sort(key=lambda item: item[0])
    records: List[Dict[str, Any]] = []
    for snapshot_at, path in snapshot_files:
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                payload = json.load(fh)
        except Exception:
            continue
        if not isinstance(payload, list):
            continue
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            opp = _restore_opportunity_from_dict(raw)
            assessment = _build_phase2_assessment(opp)
            records.append({
                'snapshot_at': snapshot_at,
                'snapshot_day': snapshot_at.strftime('%Y-%m-%d'),
                'path': path,
                'opp': opp,
                'assessment': assessment,
                'fingerprint': _fingerprint_opportunity(opp),
            })
    return records


def _weekly_focus_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        r for r in records
        if r['assessment'].verdict in {'keep', 'watch'}
        or r['assessment'].adjusted_score >= PHASE2_WATCH_MIN_SCORE
        or r['assessment'].evidence_score >= 4
    ]


def _weekly_pain_label(assessment: ScreeningAssessment) -> str:
    return _clean_text(assessment.trigger_event or assessment.deliverable or assessment.category_label or '用户最着急解决这个问题时')


def _summarize_weekly_clusters(records, label_fn, reason_fn, limit: int = 3):
    buckets: Dict[str, Dict[str, Any]] = {}
    for record in records:
        opp = record['opp']
        assessment = record['assessment']
        label = _clean_text(label_fn(opp, assessment))
        if not label:
            continue
        key = label.lower()
        bucket = buckets.setdefault(key, {'label': label, 'count': 0, 'days': set(), 'sources': set(), 'reasons': [], 'sample_title': opp.title})
        bucket['count'] += 1
        bucket['days'].add(record['snapshot_day'])
        if opp.source:
            bucket['sources'].add(opp.source)
        reason = _clean_text(reason_fn(opp, assessment))
        if reason:
            bucket['reasons'].append(reason)
    ranked = sorted(buckets.values(), key=lambda i: (i['count'], len(i['days']), len(i['sources'])), reverse=True)
    return ranked[:limit]


def _best_weekly_direction(records):
    if not records:
        return None
    groups: Dict[str, Dict[str, Any]] = {}
    for record in records:
        opp = record['opp']
        assessment = record['assessment']
        gk = '|'.join([_clean_text(assessment.deliverable).lower(), _clean_text(assessment.target_user).lower()])
        if not gk.strip('|'):
            continue
        g = groups.setdefault(gk, {'records': [], 'days': set(), 'sources': set(), 'keep': 0, 'watch': 0, 'score_total': 0, 'evidence_total': 0})
        g['records'].append(record)
        g['days'].add(record['snapshot_day'])
        if opp.source:
            g['sources'].add(opp.source)
        if assessment.verdict == 'keep':
            g['keep'] += 1
        elif assessment.verdict == 'watch':
            g['watch'] += 1
        g['score_total'] += assessment.adjusted_score
        g['evidence_total'] += assessment.evidence_score
    if not groups:
        return None

    def _gs(g):
        c = max(1, len(g['records']))
        return g['keep'] * 8 + g['watch'] * 4 + len(g['days']) * 2 + len(g['sources']) * 1.5 + g['score_total'] / c / 10 + g['evidence_total'] / c

    best = max(groups.values(), key=_gs)
    rep = max(best['records'], key=lambda i: (i['assessment'].verdict == 'keep', i['assessment'].adjusted_score, i['assessment'].evidence_score))
    return {
        'representative': rep, 'days': len(best['days']), 'sources': len(best['sources']),
        'count': len(best['records']), 'keep': best['keep'], 'watch': best['watch'],
        'avg_score': round(best['score_total'] / max(1, len(best['records'])), 1),
        'avg_evidence': round(best['evidence_total'] / max(1, len(best['records'])), 1),
    }


def _weekly_direction_confidence(direction):
    if direction['keep'] >= 1 or direction['avg_evidence'] >= 5:
        return '本周已经出现值得认真验证的单一方向。'
    if direction['watch'] >= 2 or direction['days'] >= 2:
        return '证据还没硬到直接开做，但这是本周唯一值得继续压缩验证的问题。'
    return '证据偏弱，先把这一个方向收窄验证，不要同时追别的题。'


def save_weekly_report(window_days: int = 7, now: Optional[datetime] = None) -> Optional[str]:
    """输出深筛周报（markdown + latest）。"""
    ref_now = now or datetime.now()
    ts = ref_now.strftime('%Y%m%d_%H%M%S')
    report_file = os.path.join(DATA_DIR, f'weekly_report_{ts}.md')
    latest_file = os.path.join(DATA_DIR, 'latest_weekly.md')
    records = _load_snapshot_records(window_days=window_days, now=ref_now)

    start_date = (ref_now - timedelta(days=max(1, window_days) - 1)).strftime('%Y-%m-%d')
    end_date = ref_now.strftime('%Y-%m-%d')
    snapshot_count = len({r['path'] for r in records})
    unique_fingerprints = len({r['fingerprint'] for r in records})

    if not records:
        content = '\n'.join([
            '# 深筛周报', '', f'- 统计窗口: {start_date} ~ {end_date}',
            '- 结论: 当前窗口内没有可用历史快照，先继续跑每日模式积累样本。', '',
            '## 反复出现的痛点', '- 暂无历史样本。', '',
            '## 重复出现的切口', '- 暂无历史样本。', '',
            '## 最常见伪机会类型', '- 暂无历史样本。', '',
            '## 本周唯一值得认真验证的方向', '- 暂无。先继续积累 3-7 天快照，再做深筛归纳。', '',
        ])
        for fp in (report_file, latest_file):
            with open(fp, 'w', encoding='utf-8') as fh:
                fh.write(content)
        print(f'Weekly report saved: {report_file}')
        return report_file

    focus = _weekly_focus_records(records)
    dropped = [r for r in records if r['assessment'].verdict == 'drop']
    pain_clusters = _summarize_weekly_clusters(focus, lambda _o, a: _weekly_pain_label(a), lambda _o, a: a.target_user, limit=4)
    wedge_clusters = _summarize_weekly_clusters(focus, lambda _o, a: a.deliverable, lambda _o, a: _phase2_signal_summary(_o, a), limit=4)
    pseudo_clusters = _summarize_weekly_clusters(dropped, lambda o, a: _pseudo_opportunity_type(o, a), lambda o, a: _concise_drop_reason(o, a), limit=4)
    direction_cands = [r for r in focus if r['assessment'].verdict in {'keep', 'watch'}]
    direction = _best_weekly_direction(direction_cands)

    vc = defaultdict(int)
    for r in records:
        vc[r['assessment'].verdict] += 1

    lines = [
        '# 深筛周报', '',
        f'- 统计窗口: {start_date} ~ {end_date}',
        f'- 覆盖快照: {snapshot_count} 份',
        f'- 去重后机会指纹: {unique_fingerprints}',
        f'- 决策分布: keep {vc["keep"]} / watch {vc["watch"]} / drop {vc["drop"]}',
        '', '## 反复出现的痛点',
    ]
    if pain_clusters:
        for c in pain_clusters:
            s = '、'.join(sorted(c['sources'])[:3]) or '未知来源'
            lines.append(f'- {c["label"]}: {c["count"]} 次，出现在 {len(c["days"])} 天，主要指向 {s}。')
    else:
        lines.append('- 本周没有形成可复用的痛点聚类。')
    lines.append('')

    lines.append('## 重复出现的切口')
    if wedge_clusters:
        for c in wedge_clusters:
            r = c['reasons'][0] if c['reasons'] else '证据待补充'
            lines.append(f'- {c["label"]}: {c["count"]} 次，出现在 {len(c["days"])} 天；代表信号是 {r}。')
    else:
        lines.append('- 本周没有出现重复到值得命名的切口。')
    lines.append('')

    lines.append('## 最常见伪机会类型')
    if pseudo_clusters:
        for c in pseudo_clusters:
            r = c['reasons'][0] if c['reasons'] else '今天看不到可执行验证路径。'
            lines.append(f'- {c["label"]}: {c["count"]} 次；共性问题是 {r}')
    else:
        lines.append('- 本周 drop 样本不足，暂时没有稳定伪机会类型。')
    lines.append('')

    lines.append('## 本周唯一值得认真验证的方向')
    if direction:
        rec = direction['representative']
        opp, a = rec['opp'], rec['assessment']
        lines.extend([
            f'- 切口名称: {a.deliverable}', f'- 目标用户: {a.target_user}', f'- 高频场景: {a.trigger_event}',
            f'- 本周证据: {direction["count"]} 次出现，覆盖 {direction["days"]} 天、{direction["sources"]} 个来源；平均信号 {direction["avg_score"]}，平均证据 {direction["avg_evidence"]}。',
            f'- 为什么是它: {_weekly_direction_confidence(direction)}',
            f'- 下周只验证什么: 先验证 {a.target_user} 是否愿意为"{a.deliverable}"付第一笔钱，不扩成功能平台。',
            f'- 参考样本: {opp.title} | {opp.url}', '',
        ])
    else:
        lines.extend(['- 暂无。当前窗口里还没有出现一个值得单点加码的方向。', ''])

    content = '\n'.join(lines)
    for fp in (report_file, latest_file):
        with open(fp, 'w', encoding='utf-8') as fh:
            fh.write(content)
    print(f'Weekly report saved: {report_file}')
    return report_file
