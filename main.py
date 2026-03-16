#!/usr/bin/env python3
"""
调研 Agent - 发现产品机会

用法:
    python3 main.py              # 手动运行
    python3 main.py --test       # 测试模式
    python3 main.py --debug      # 调试模式

配置:
    复制 .env.example 为 .env 并填写 API Key
"""

import os
import sys
import json
import asyncio
import argparse
from datetime import datetime, timedelta
from typing import List, Optional
import hashlib
import subprocess
import tempfile
import re
import shutil
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mvp_generator import MVPGenerator
from config import DEBUG, DATA_DIR, LOG_DIR, BAILIAN_API_KEY, FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_USER_ID, FEISHU_INDEX_DOC_TOKEN, FEISHU_DOC_SYNC_ENABLED, validate_config, GITHUB_TOKEN, GITHUB_REPO
from collectors import HNCollector, PHCollector, ChineseMediaCollector, GitHubTrendingCollector, AgentReachBridge
from collectors.indiehackers import IndieHackersCollector
from collectors.reddit import RedditCollector
from analyzers import BailianAnalyzer
from models import Opportunity

PHASE1_KEEP_MIN_SCORE = 75
PHASE1_FILTER_LIMIT = 5


def setup_logging():
    """设置日志"""
    import logging as loglib
    
    log_file = os.path.join(LOG_DIR, f"research_{datetime.now().strftime('%Y%m%d')}.log")
    
    # 简单的日志配置
    loglib.basicConfig(
        level=loglib.DEBUG if DEBUG else loglib.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            loglib.FileHandler(log_file),
            loglib.StreamHandler()
        ]
    )
    return loglib.getLogger(__name__)


def collect_data(hn_limit: int = 10, ph_limit: int = 5, media_hours: int = 48,
                 indie_limit: int = 15, reddit_limit: int = 10, github_limit: int = 10,
                 enable_agent_reach: bool = False, ar_limit: int = 10) -> List[dict]:
    """收集数据"""
    import logging
    logger = logging.getLogger(__name__)
    
    items = []
    
    # Hacker News
    logger.info(f"Fetching HN (limit={hn_limit})...")
    hn_items = HNCollector.fetch(limit=hn_limit)
    logger.info(f"Got {len(hn_items)} HN items")
    items.extend(hn_items)
    
    # Product Hunt
    logger.info(f"Fetching PH (limit={ph_limit})...")
    ph_items = PHCollector.fetch(limit=ph_limit)
    logger.info(f"Got {len(ph_items)} PH items")
    items.extend(ph_items)
    
    
    # Chinese Media (36Kr, Huxiu, etc.)
    logger.info(f"Fetching Chinese Media (hours={media_hours})...")
    media_items = ChineseMediaCollector.fetch(hours=media_hours, limit=20)
    logger.info(f"Got {len(media_items)} Chinese media items")
    items.extend(media_items)
    
    
    # IndieHackers (solo founder stories)
    logger.info(f"Fetching IndieHackers (limit={indie_limit})...")
    ih_collector = IndieHackersCollector()
    ih_items = ih_collector.fetch(limit=indie_limit)
    logger.info(f"Got {len(ih_items)} IndieHackers items")
    items.extend(ih_items)

    # GitHub Trending
    logger.info(f"Fetching GitHub Trending (limit={github_limit})...")
    gh_collector = GitHubTrendingCollector()
    gh_items = gh_collector.fetch(limit=github_limit)
    logger.info(f"Got {len(gh_items)} GitHub Trending items")
    items.extend(gh_items)

    # fallback legacy Reddit collector (kept for compatibility)
    if not enable_agent_reach:
        logger.info(f"Fetching Reddit (limit={reddit_limit})...")
        reddit_collector = RedditCollector()
        reddit_items = reddit_collector.fetch(limit=reddit_limit)
        logger.info(f"Got {len(reddit_items)} Reddit items")
        items.extend(reddit_items)


    # Agent Reach bridge (P1: X / YouTube / Reddit)
    if enable_agent_reach:
        logger.info(f"Fetching Agent Reach sources (limit={ar_limit})...")
        ar = AgentReachBridge(DATA_DIR)
        health = ar.check_health()

        if health.get("x"):
            x_items = ar.fetch_x(limit=ar_limit)
            logger.info(f"Got {len(x_items)} Agent Reach X items")
            items.extend(x_items)
        else:
            logger.info("Skip Agent Reach X (unhealthy)")

        if health.get("youtube"):
            y_items = ar.fetch_youtube(limit=ar_limit)
            logger.info(f"Got {len(y_items)} Agent Reach YouTube items")
            items.extend(y_items)
        else:
            logger.info("Skip Agent Reach YouTube (unhealthy)")

        if health.get("reddit"):
            r_items = ar.fetch_reddit(limit=ar_limit)
            logger.info(f"Got {len(r_items)} Agent Reach Reddit items")
            items.extend(r_items)
        else:
            logger.info("Skip Agent Reach Reddit (unhealthy)")

    return items


def analyze_items(items: List[dict], min_score: int = 60) -> List[Opportunity]:
    """分析项目"""
    return asyncio.run(analyze_items_async(items, min_score=min_score))


async def analyze_items_async(items: List[dict], min_score: int = 60) -> List[Opportunity]:
    """异步分析项目"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not BAILIAN_API_KEY:
        logger.error("BAILIAN_API_KEY not configured")
        return []
    
    analyzer = BailianAnalyzer()
    
    logger.info(f"Analyzing {len(items)} items (min_score={min_score})...")
    opportunities = await analyzer.batch_analyze_async(items, min_score=min_score)
    logger.info(f"Found {len(opportunities)} opportunities")
    
    return opportunities




def _normalize_title(title: str) -> str:
    import re
    t = (title or '').lower()
    t = re.sub(r'https?://\S+', '', t)
    t = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t




def _normalize_url(url: str) -> str:
    """URL 规范化：去掉常见追踪参数，统一域名/路径格式"""
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
            lk = k.lower()
            if lk.startswith(blocked_prefix):
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
        domain = ''
    raw = f"{title_norm[:160]}|{domain}|{canonical_url}"
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


def _load_seen_fingerprints(days: int = 14):
    seen_file = os.path.join(DATA_DIR, 'seen_fingerprints.json')
    now = datetime.now()
    cutoff = now - timedelta(days=days)
    data = {'items': []}

    if os.path.exists(seen_file):
        try:
            with open(seen_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {'items': []}

    kept = []
    seen_map = {}
    for it in data.get('items', []):
        ts = it.get('seen_at', '')
        fp = it.get('fp', '')
        try:
            dt = datetime.fromisoformat(ts)
        except Exception:
            continue
        if dt >= cutoff and fp:
            kept.append({'fp': fp, 'seen_at': ts})
            seen_map[fp] = dt

    return seen_file, kept, seen_map


def deduplicate_across_days(opportunities: List[Opportunity], days: int = 14) -> List[Opportunity]:
    """跨天去重：命中最近 N 天已见指纹则过滤"""
    seen_file, kept_items, seen_map = _load_seen_fingerprints(days=days)

    fresh = []
    for opp in opportunities:
        fp = _fingerprint_opportunity(opp)
        if fp in seen_map:
            continue
        fresh.append(opp)
        kept_items.append({'fp': fp, 'seen_at': datetime.now().isoformat()})
        seen_map[fp] = datetime.now()

    try:
        with open(seen_file, 'w', encoding='utf-8') as f:
            json.dump({'items': kept_items[-5000:]}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'Warning: failed to save seen_fingerprints: {e}')

    return fresh


def deduplicate_opportunities(opportunities: List[Opportunity]) -> List[Opportunity]:
    """按标题归一化去重：同类机会保留分数最高项"""
    best = {}
    for opp in opportunities:
        key = _normalize_title(opp.title)[:120]
        if not key:
            continue
        old = best.get(key)
        if old is None or opp.score > old.score:
            best[key] = opp
    return list(best.values())


def rerank_for_solo(opportunities: List[Opportunity]) -> List[Opportunity]:
    """一人公司友好重排：在原始 score 上加轻量业务权重"""
    def bonus(opp: Opportunity) -> int:
        b = 0
        text = f"{opp.revenue_model} {opp.time_to_revenue} {opp.automation_rate} {opp.source}".lower()
        if any(k in text for k in ['subscription', '订阅', 'saas']):
            b += 5
        if any(k in text for k in ['<7', '30', '30 天', '7 天']):
            b += 4
        if '90' in text or '90%+' in text:
            b += 4
        if any(k in text for k in ['indiehackers', 'reddit_r/saas', 'product hunt', 'ph']):
            b += 2
        return b

    ranked = sorted(opportunities, key=lambda o: (o.score + bonus(o), o.score), reverse=True)
    return ranked


def _clean_text(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').strip())


def _truncate(text: str, limit: int = 160) -> str:
    text = _clean_text(text)
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + '…'


def _score_grade(score: int) -> str:
    if score >= 85:
        return 'A'
    if score >= 75:
        return 'B'
    if score >= 65:
        return 'C'
    return 'D'


def _decision_label(score: int) -> str:
    grade = _score_grade(score)
    mapping = {
        'A': '立即验证',
        'B': '保留观察',
        'C': '暂不投入',
        'D': '直接过滤',
    }
    return mapping[grade]


def _is_fast_payback_window(text: str) -> bool:
    normalized = _clean_text(text).lower()
    if not normalized:
        return False
    return any(token in normalized for token in ['7天', '14天', '两周', '2周', 'two week', '<7', '7 days', '14 days'])


def _default_first_users_source(opp: Opportunity) -> str:
    source = (opp.source or '').lower()
    mapping = {
        'hn': '从 Hacker News 原帖作者、评论区高互动用户和相关 Show HN 创作者里定向外联。',
        'ph': '从 Product Hunt 发布页评论者、投票用户和同类产品的早期支持者里找首批试用者。',
        'reddit': '从对应 subreddit 的发帖者、评论者和求推荐帖子里私信约访。',
        'reddit_r/saas': '从 r/SaaS 的发帖者、评论者和求工具帖里私信约访。',
        'github': '从相关仓库的 issue、discussion、star 用户和 README 反馈里找早期用户。',
        'github_trending': '从相关仓库的 issue、discussion、star 用户和 README 反馈里找早期用户。',
        'indiehackers': '从 IndieHackers 发帖作者、评论区和同类项目创始人网络中直接约访。',
        '36kr': '从报道里出现的赛道从业者、微信群和相关服务商客户名单中做定向外联。',
        'huxiu': '从报道里出现的赛道从业者、微信群和相关服务商客户名单中做定向外联。',
    }
    return mapping.get(source, '从原始信号对应的社区、评论区和现有人脉里做定向外联，先拿到 20 个深访/试用用户。')


def _select_phase1_candidates(opportunities: List[Opportunity]) -> tuple[List[Opportunity], List[Opportunity]]:
    kept: List[Opportunity] = []
    filtered_pool = list(opportunities)
    if opportunities and opportunities[0].score >= PHASE1_KEEP_MIN_SCORE:
        kept = [opportunities[0]]
        filtered_pool = opportunities[1:]
    return kept, filtered_pool[:PHASE1_FILTER_LIMIT]




def _opportunity_what(opp: Opportunity) -> str:
    """项目是做什么（优先 description，其次 summary）。"""
    base = (opp.description or opp.summary or '').strip()
    if base:
        return base
    return f"围绕 {opp.title} 这个信号，抽象出可产品化场景，面向对应目标用户提供可复用的工具/服务。"


def _opportunity_how(opp: Opportunity) -> str:
    """怎么做（落地路径）。"""
    if opp.action_plan:
        return opp.action_plan.strip()
    return "先做最小可行版本（MVP）→ 找10位种子用户验证 → 根据反馈迭代功能与定价。"


def _opportunity_profit(opp: Opportunity) -> str:
    """怎么盈利（商业模式 + 时间预期）。"""
    model = (opp.revenue_model or '订阅').strip()
    ttr = (opp.time_to_revenue or '30天').strip()
    potential = (opp.monthly_potential or '$10-50k').strip()
    return f"主要通过【{model}】变现，预计【{ttr}】看到首笔收入，月度潜力区间【{potential}】。"


def _wedge_statement(opp: Opportunity) -> str:
    # TODO(Phase 2): replace this template with analyzer-native wedge extraction.
    what = _truncate(_opportunity_what(opp), limit=180)
    return f"不要复刻“{opp.title}”本身，而是切其中最窄、最容易先收钱的工作流：{what}"


def _who_pays_in_14_days(opp: Opportunity) -> str:
    model = _clean_text(opp.revenue_model or '一次性 setup fee 或按月订阅')
    timing = _clean_text(opp.time_to_revenue)
    if timing and _is_fast_payback_window(timing):
        return f"优先卖给已经在主动找替代方案的早期客户，先用“{model}”收第一笔钱；当前分析判断见钱周期为“{timing}”。"
    if timing:
        return f"优先卖给痛点最强、可被直接外联触达的客户，收费方式先用“{model}”；但当前给出的见钱周期是“{timing}”，14 天内收钱仍需人工验证。"
    return f"优先卖给已经在用手工流程或多工具拼接解决这个问题的人，先用“{model}”收第一笔钱；14 天内是否能成交，目前证据不足。"


def _first_20_users_source(opp: Opportunity) -> str:
    acquisition = _clean_text(opp.customer_acquisition)
    if acquisition:
        return acquisition
    return _default_first_users_source(opp)


def _why_solo_buildable(opp: Opportunity) -> str:
    reasons = []
    if opp.solo_feasibility:
        reasons.append(_truncate(opp.solo_feasibility, limit=140))
    if opp.startup_cost:
        reasons.append(f"启动成本预估 {opp.startup_cost}")
    if opp.automation_rate:
        reasons.append(f"可自动化比例 {opp.automation_rate}")
    if reasons:
        return '；'.join(reasons[:3]) + '。'
    return '先从人工服务 + 轻工具交付起步，单人也能在需求验证期内完成交付。'


def _why_not_crushed(opp: Opportunity) -> str:
    risk = _truncate(opp.risks, limit=120)
    base = '这是一个窄切口工作流，先靠速度、人工兜底和深度场景理解收钱，通常不值得大玩家立刻下场复制。'
    if risk:
        return f"{base} 当前最需要防的不是巨头，而是 {risk}"
    return base


def _smallest_paid_mvp(opp: Opportunity) -> str:
    plan = _clean_text(opp.action_plan)
    if plan:
        return f"最小收费版本应只承诺一个明确结果，先用表单/脚本/人工交付完成闭环。落地路径：{_truncate(plan, limit=180)}"
    return '先做一个单入口、单输出、可人工兜底的收费 MVP，验证是否有人愿意为这一个结果付款。'


def _filtered_reason(opp: Opportunity) -> str:
    reasons = []
    if opp.score < PHASE1_KEEP_MIN_SCORE:
        reasons.append('未达到 Phase 1 保留阈值')
    if not _is_fast_payback_window(opp.time_to_revenue):
        reasons.append('14 天内收钱路径不够清晰')
    if not _clean_text(opp.customer_acquisition):
        reasons.append('前 20 个用户来源不够具体')
    if not _clean_text(opp.solo_feasibility):
        reasons.append('单人可交付边界不够明确')
    if opp.risks:
        reasons.append(f"主要风险：{_truncate(opp.risks, limit=80)}")
    return '；'.join(reasons[:3]) if reasons else '当前更像泛机会，不是今天就该切进去的 wedge。'


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


def save_phase1_report(opportunities: List[Opportunity]):
    """输出 Phase 1 solo-venture screener（markdown + latest）。"""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = os.path.join(DATA_DIR, f'phase1_report_{ts}.md')
    latest_file = os.path.join(DATA_DIR, 'latest_phase1.md')

    kept, filtered = _select_phase1_candidates(opportunities)
    lines = [
        '# Phase 1 Solo Venture Screener',
        '',
        f'- 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'- 候选池规模: {len(opportunities)}',
        f'- 结论: {"Top1" if kept else "Top0"}',
        '',
    ]
    lines.extend(_agent_reach_health_summary_lines())

    if kept:
        opp = kept[0]
        lines.extend([
            '## Keep Candidate',
            f'- 决策: **{_decision_label(opp.score)}**',
            f'- 等级: **{_score_grade(opp.score)}**',
            f'- 来源: `{opp.source}`',
            f'- 链接: {opp.url}',
            '',
            '### Wedge / 切入点',
            _wedge_statement(opp),
            '',
            '### 谁会在 14 天内付钱',
            _who_pays_in_14_days(opp),
            '',
            '### 前 20 个用户从哪里来',
            _first_20_users_source(opp),
            '',
            '### 为什么适合 solo builder',
            _why_solo_buildable(opp),
            '',
            '### 为什么不会立刻被大玩家碾压',
            _why_not_crushed(opp),
            '',
            '### 最小可收费 MVP',
            _smallest_paid_mvp(opp),
            '',
            '### 备注',
            f'- 变现方式: {opp.revenue_model or "待验证"}',
            f'- 见钱周期: {opp.time_to_revenue or "待验证"}',
            f'- 启动成本: {opp.startup_cost or "待验证"}',
            f'- 月潜力: {opp.monthly_potential or "待验证"}',
            '',
        ])
    else:
        lines.extend([
            '## Top0',
            '今天没有候选通过 Phase 1 保留门槛。',
            '主要原因通常是 14 天内付费路径、前 20 个用户来源或单人可交付边界不够清晰。',
            '',
        ])

    lines.extend([
        '## Not Worth Doing Now',
        '以下条目保留作样本，但不进入本轮 wedge 验证：',
        '',
    ])

    if filtered:
        for idx, opp in enumerate(filtered, 1):
            lines.extend([
                f'### {idx}. {opp.title}',
                f'- 决策: **{_decision_label(opp.score)}**',
                f'- 等级: **{_score_grade(opp.score)}**',
                f'- 来源: `{opp.source}`',
                f'- 理由: {_filtered_reason(opp)}',
                f'- 链接: {opp.url}',
                '',
            ])
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

    # Agent Reach 健康摘要
    health_summary_lines = []
    health_file = os.path.join(DATA_DIR, 'agent_reach_health.json')
    if os.path.exists(health_file):
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
            f'- 评分: **{o.score}/100**',
            f'- 来源: `{o.source}`',
            f'- 链接: {o.url}',
            '',
            f'### 这是什么项目（What）',
            _opportunity_what(o),
            '',
            f'### 怎么做（How）',
            _opportunity_how(o),
            '',
            f'### 怎么盈利（Money）',
            _opportunity_profit(o),
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


def _extract_real_feishu_doc_url(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r'https://(?:[\w-]+\.)?feishu\.cn/docx/[A-Za-z0-9]+', text)
    return m.group(0) if m else None


def _looks_like_placeholder(value: str) -> bool:
    v = (value or '').strip().lower()
    return not v or v in {'cli_xxx', 'xxx', 'ou_xxx', 'user_xxx', 'open_id_xxx', 'placeholder'}


def _resolve_feishu_credentials() -> tuple[Optional[str], Optional[str]]:
    app_id = FEISHU_APP_ID
    app_secret = FEISHU_APP_SECRET
    if not _looks_like_placeholder(app_id) and not _looks_like_placeholder(app_secret):
        return app_id, app_secret

    try:
        cfg_path = os.path.expanduser('~/.openclaw/openclaw.json')
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        acct = (((cfg.get('channels') or {}).get('feishu') or {}).get('accounts') or {}).get('default') or {}
        app_id = acct.get('appId') or app_id
        app_secret = acct.get('appSecret') or app_secret
    except Exception:
        pass
    return app_id, app_secret


def sync_report_to_feishu(md_filename: str = 'latest_phase1.md', title: Optional[str] = None) -> Optional[str]:
    """将指定 markdown 报告同步到 Feishu Doc，并返回可验证的真实 docx URL。"""
    if not FEISHU_DOC_SYNC_ENABLED:
        print("Feishu doc sync disabled, skipping")
        return None
    app_id, app_secret = _resolve_feishu_credentials()
    if _looks_like_placeholder(app_id) or _looks_like_placeholder(app_secret):
        print("FEISHU_APP_ID / FEISHU_APP_SECRET not configured, skipping Feishu doc sync")
        return None

    md_path = os.path.join(DATA_DIR, md_filename)
    if not os.path.exists(md_path):
        print(f"{md_filename} not found, skipping Feishu doc sync")
        return None

    title = title or f"Solo Venture Screener-{datetime.now().strftime('%Y-%m-%d')}"

    node_script = r'''
const fs = require('fs');
const os = require('os');
const path = require('path');
const Lark = require('@larksuiteoapi/node-sdk');

const appId = process.env.FEISHU_APP_ID || '';
const appSecret = process.env.FEISHU_APP_SECRET || '';
const indexToken = (process.env.FEISHU_INDEX_DOC_TOKEN || '').trim();
const title = process.env.FEISHU_DOC_TITLE || '机会洞察';
const mdPath = process.env.FEISHU_MD_PATH;

const client = new Lark.Client({
  appId,
  appSecret,
  appType: Lark.AppType.SelfBuild,
  domain: Lark.Domain.Feishu,
});

function cleanBlocksForDescendant(blocks) {
  return blocks.map((block) => {
    const { parent_id, ...cleanBlock } = block;
    if (cleanBlock.block_type === 32 && typeof cleanBlock.children === 'string') {
      cleanBlock.children = [cleanBlock.children];
    }
    if (cleanBlock.block_type === 31 && cleanBlock.table) {
      const prop = cleanBlock.table.property || {};
      cleanBlock.table = { property: { row_size: prop.row_size, column_size: prop.column_size, ...(prop.column_width ? {column_width: prop.column_width} : {}) } };
    }
    return cleanBlock;
  });
}

async function convertMarkdown(markdown) {
  const res = await client.docx.document.convert({ data: { content_type: 'markdown', content: markdown } });
  if (res.code !== 0) throw new Error('convert failed: ' + res.msg);
  return { blocks: res.data?.blocks || [], firstLevelBlockIds: res.data?.first_level_block_ids || [] };
}

async function clearDocumentContent(docToken) {
  const existing = await client.docx.documentBlock.list({ path: { document_id: docToken } });
  if (existing.code !== 0) throw new Error(existing.msg);
  const childIds = (existing.data?.items || []).filter(b => b.parent_id === docToken && b.block_type !== 1).map(b => b.block_id);
  if (childIds.length > 0) {
    const del = await client.docx.documentBlockChildren.batchDelete({ path: { document_id: docToken, block_id: docToken }, data: { start_index: 0, end_index: childIds.length } });
    if (del.code !== 0) throw new Error(del.msg);
  }
}

async function writeMarkdown(docToken, markdown) {
  await clearDocumentContent(docToken);
  const { blocks, firstLevelBlockIds } = await convertMarkdown(markdown);
  if (!blocks.length) return;
  const res = await client.docx.documentBlockDescendant.create({
    path: { document_id: docToken, block_id: docToken },
    data: { children_id: firstLevelBlockIds, descendants: cleanBlocksForDescendant(blocks), index: -1 }
  });
  if (res.code !== 0) throw new Error('descendant create failed: ' + res.msg + ' (code ' + res.code + ')');
}

async function listAllBlocks(docToken) {
  const res = await client.docx.documentBlock.list({ path: { document_id: docToken } });
  if (res.code !== 0) throw new Error(res.msg);
  return res.data?.items || [];
}

function headingLevel(type) {
  return ({3:1,4:2,5:3})[type] || null;
}

async function insertUnderDocList(docToken, lineMarkdown) {
  const blocks = await listAllBlocks(docToken);
  const heading = blocks.find(b => {
    const elems = b.text?.elements || [];
    const text = elems.map(e => e?.text_run?.content || '').join('');
    return text.trim() === '文档列表';
  });
  if (!heading) throw new Error('未找到“文档列表”区块');
  const parentId = heading.parent_id || docToken;
  const childrenRes = await client.docx.documentBlockChildren.get({ path: { document_id: docToken, block_id: parentId } });
  if (childrenRes.code !== 0) throw new Error(childrenRes.msg);
  const siblings = childrenRes.data?.items || [];
  const hIdx = siblings.findIndex(s => s.block_id === heading.block_id);
  if (hIdx < 0) throw new Error('未找到“文档列表”区块在父节点中的位置');
  const hLevel = headingLevel(heading.block_type) || 99;
  let insertIndex = siblings.length;
  for (let i = hIdx + 1; i < siblings.length; i++) {
    const lvl = headingLevel(siblings[i].block_type);
    if (lvl !== null && lvl <= hLevel) {
      insertIndex = i;
      break;
    }
  }
  const { blocks: newBlocks, firstLevelBlockIds } = await convertMarkdown(lineMarkdown);
  const res = await client.docx.documentBlockDescendant.create({
    path: { document_id: docToken, block_id: parentId },
    data: { children_id: firstLevelBlockIds, descendants: cleanBlocksForDescendant(newBlocks), index: insertIndex }
  });
  if (res.code !== 0) throw new Error('index update failed: ' + res.msg + ' (code ' + res.code + ')');
}

(async () => {
  const out = { created: false, write_ok: false, index_update_ok: false, doc_url: '', title, error: '', warning: '' };
  try {
    const markdown = fs.readFileSync(mdPath, 'utf8');
    const created = await client.docx.document.create({ data: { title } });
    if (created.code !== 0) throw new Error('create failed: ' + created.msg);
    const docToken = created.data?.document?.document_id;
    if (!docToken) throw new Error('create failed: missing document_id');
    const docUrl = `https://feishu.cn/docx/${docToken}`;
    if (!/^https:\/\/(?:[\w-]+\.)?feishu\.cn\/docx\/[A-Za-z0-9]+$/.test(docUrl)) {
      throw new Error('returned doc URL is not a real Feishu docx URL');
    }
    out.created = true;
    out.doc_url = docUrl;

    await writeMarkdown(docToken, markdown);
    out.write_ok = true;

    if (indexToken) {
      try {
        const line = `- ${new Date().toISOString().slice(0,10)}: [${title}](${docUrl})`;
        await insertUnderDocList(indexToken, line);
        out.index_update_ok = true;
      } catch (err) {
        out.warning = err && err.message ? err.message : String(err);
      }
    }

    console.log(JSON.stringify(out));
  } catch (err) {
    out.error = err && err.message ? err.message : String(err);
    console.log(JSON.stringify(out));
    process.exitCode = 1;
  }
})();
'''

    script_path = None
    try:
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
            f.write(node_script)
            script_path = f.name

        env = os.environ.copy()
        env.update({
            'FEISHU_APP_ID': app_id,
            'FEISHU_APP_SECRET': app_secret,
            'FEISHU_INDEX_DOC_TOKEN': FEISHU_INDEX_DOC_TOKEN,
            'FEISHU_DOC_TITLE': title,
            'FEISHU_MD_PATH': md_path,
        })

        npm_root = '/opt/homebrew/lib/node_modules/openclaw/node_modules'
        env['NODE_PATH'] = f"{npm_root}:{env.get('NODE_PATH', '')}" if env.get('NODE_PATH') else npm_root

        node_bin = shutil.which('node') or '/opt/homebrew/bin/node'
        result = subprocess.run(
            [node_bin, script_path],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        out = (result.stdout or '').strip() or (result.stderr or '').strip()
        url = _extract_real_feishu_doc_url(out)
        if result.returncode == 0 and url:
            print(f'Feishu daily doc: {url}')
            return url
        raise RuntimeError(out or 'unknown feishu doc sync error')
    except Exception as e:
        print(f'Feishu doc sync failed: {e}')
        return None
    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass


def sync_top10_report_to_feishu() -> Optional[str]:
    """兼容旧调用。"""
    return sync_report_to_feishu(md_filename='latest_top10.md', title=f"机会洞察-{datetime.now().strftime('%Y-%m-%d')}")


def cleanup_old_data(retention_days: int = 14):
    """清理历史机会快照，仅保留最近 N 天。"""
    import re
    cutoff = datetime.now() - timedelta(days=retention_days)
    pattern = re.compile(r'^opportunities_(\d{8})_(\d{6})\.json$')

    removed = 0
    for name in os.listdir(DATA_DIR):
        m = pattern.match(name)
        if not m:
            continue
        dt_str = m.group(1) + m.group(2)
        try:
            dt = datetime.strptime(dt_str, '%Y%m%d%H%M%S')
        except Exception:
            continue
        if dt < cutoff:
            try:
                os.remove(os.path.join(DATA_DIR, name))
                removed += 1
            except Exception:
                pass

    if removed:
        print(f'Cleanup: removed {removed} old snapshot files (> {retention_days} days)')


def save_results(opportunities: List[Opportunity]):
    """保存结果"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # 保存 JSON
    json_file = os.path.join(DATA_DIR, f"opportunities_{timestamp}.json")
    with open(json_file, 'w', encoding='utf-8') as f:
        try:
            json.dump([opp.to_dict() for opp in opportunities], f, ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as e:
            print(f"JSON serialization error: {e}")
            # 尝试简化数据
            simple_data = []
            for opp in opportunities:
                try:
                    simple_data.append({
                        'id': opp.id,
                        'title': opp.title,
                        'score': opp.score
                    })
                except Exception:
                    continue
            json.dump(simple_data, f, ensure_ascii=False, indent=2)
    
    # 保存最新结果
    latest_file = os.path.join(DATA_DIR, "latest.json")
    try:
        with open(latest_file, 'w', encoding='utf-8') as f:
            json.dump([opp.to_dict() for opp in opportunities], f, ensure_ascii=False, indent=2)
    except (IOError, OSError) as e:
        print(f"Error saving latest.json: {e}")
    
    print(f"Saved to {json_file}")
    cleanup_old_data(retention_days=14)


def send_to_feishu(opportunities: List[Opportunity]):
    """发送到飞书（通过 OpenClaw CLI）

    修复点：某些环境下 openclaw 会输出 config warnings，
    但消息实际已发送。这里用“返回码 + 输出特征”双判定，避免误报失败。
    """
    if not FEISHU_USER_ID:
        print("FEISHU_USER_ID not configured, skipping Feishu notification")
        return
    if FEISHU_USER_ID.strip().lower() in {"ou_xxx", "user_xxx", "open_id_xxx", "placeholder"}:
        print("FEISHU_USER_ID is placeholder, skipping direct Feishu notification")
        return

    def _looks_delivered(stdout: str, stderr: str) -> bool:
        text = f"{stdout}\n{stderr}".lower()
        # 兼容不同输出格式
        success_signals = [
            '"messageid"',
            '"chatid"',
            ' via ',
            'result',
            'sent',
            'delivered',
        ]
        return any(sig in text for sig in success_signals)

    try:
        import subprocess

        sent = 0
        failed = 0

        # 发送 Top 10
        for opp in opportunities[:10]:
            msg = opp.to_message()
            cmd = [
                "openclaw", "message", "send",
                "--channel", "feishu",
                "--target", f"user:{FEISHU_USER_ID}",
                "--message", msg,
                "--silent"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            delivered = (result.returncode == 0) or _looks_delivered(result.stdout, result.stderr)

            if delivered:
                sent += 1
                if result.returncode != 0:
                    print(f"✅ Sent to Feishu (with warnings): {opp.title[:50]}...")
                else:
                    print(f"✅ Sent to Feishu: {opp.title[:50]}...")
            else:
                failed += 1
                err = (result.stderr or result.stdout or '').strip().replace('\n', ' ')
                print(f"⚠️  Send failed: {err[:160]}")

        print(f"✅ Feishu delivery summary: sent={sent}, failed={failed}, total={min(10, len(opportunities))}")

    except Exception as e:
        print(f"Error sending to Feishu: {e}")


def create_github_issues(opportunities: List[Opportunity]):
    """自动创建 GitHub Issue"""
    if not GITHUB_TOKEN:
        print("⚠️  GITHUB_TOKEN not configured, skipping GitHub issues")
        print("   Configure: echo 'ghp_xxx' > ~/.github_token")
        return
    
    import requests
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    created = 0
    for opp in opportunities[:3]:  # 只创建 Top 3
        try:
            data = {
                "title": f"🚀 {opp.title[:50]} - {opp.score}分机会",
                "body": f"""## 📊 机会评估

- **评分**: {opp.score}/100
- **来源**: {opp.source.upper()}
- **发现日期**: {opp.created_at.strftime('%Y-%m-%d')}

## 📖 项目介绍

{opp.description if opp.description else opp.summary}

## 👤 一人公司可行性

{opp.solo_feasibility if opp.solo_feasibility else '待分析'}

## 💰 商业模式

- 启动成本：{opp.startup_cost or '待分析'}
- 多久见钱：{opp.time_to_revenue or '待分析'}
- 月收入潜力：{opp.monthly_potential or '待分析'}
- 自动化率：{opp.automation_rate or '待分析'}

## 🚀 第一步

{opp.action_plan if opp.action_plan else '待分析'}

## 📄 详情

https://github.com/{GITHUB_REPO}/blob/main/opportunities/{opp.created_at.strftime('%Y-%m-%d')}_{opp.id}.md

---
*Auto-created by Research Agent*""",
                "labels": ["opportunity", "researching", "ai"]
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 201:
                issue_url = response.json().get('html_url', '')
                print(f"✅ Created Issue: {issue_url}")
                created += 1
            else:
                print(f"⚠️  Failed: {response.status_code} - {response.text[:100]}")
                
        except Exception as e:
            print(f"⚠️  Error: {e}")
    
    print(f"✅ Created {created}/3 GitHub issues")




def generate_mvps(opportunities: List[Opportunity]):
    """为 Top 机会生成 MVP"""
    print("\n🚀 Generating MVPs...")
    
    generator = MVPGenerator()
    generated = 0
    
    for opp in opportunities[:2]:  # 只为 Top 2 生成 MVP
        try:
            opp_dict = {
                'title': opp.title,
                'summary': opp.summary,
                'description': opp.description or opp.summary,
                'score': opp.score,
                'revenue_model': opp.revenue_model or 'Subscription',
                'startup_cost': opp.startup_cost or '$1-5k',
                'time_to_revenue': opp.time_to_revenue or '30 days',
                'monthly_potential': opp.monthly_potential or '$10-50k',
                'automation_rate': opp.automation_rate or '90%+',
                'agent_roles': opp.agent_roles or ['Development Agent']
            }
            
            project_dir = generator.generate(opp_dict)
            if project_dir:
                generated += 1
                print(f"✅ Generated: {project_dir}")
        except Exception as e:
            print(f"⚠️  Failed to generate MVP for {opp.title}: {e}")
    
    print(f"\n✅ Generated {generated}/{len(opportunities[:2])} MVPs")


def print_phase1_results(kept: List[Opportunity], filtered: List[Opportunity], total_count: int):
    """打印 Phase 1 screener 摘要。"""
    print("\n" + "=" * 80)
    print(f"Phase 1 Solo Venture Screener | 候选池 {total_count} 条")
    print("=" * 80 + "\n")

    if kept:
        opp = kept[0]
        print(f"Top1 | {_decision_label(opp.score)} | 等级 { _score_grade(opp.score) }")
        print(f"切入 wedge：{_wedge_statement(opp)}")
        print(f"14 天收钱：{_who_pays_in_14_days(opp)}")
        print(f"前 20 个用户：{_first_20_users_source(opp)}")
        print(f"Solo 可行性：{_why_solo_buildable(opp)}")
        print(f"抗巨头逻辑：{_why_not_crushed(opp)}")
        print(f"最小收费 MVP：{_smallest_paid_mvp(opp)}")
        print(f"链接：{opp.url}")
    else:
        print("Top0 | 今天没有候选通过 Phase 1 保留门槛")

    print("\n过滤样本：")
    if filtered:
        for idx, opp in enumerate(filtered, 1):
            print(f"{idx}. {_decision_label(opp.score)} | 等级 {_score_grade(opp.score)} | {opp.title}")
            print(f"   {_filtered_reason(opp)}")
    else:
        print("无更多可列出的过滤样本")
    print()


def print_results(opportunities: List[Opportunity]):
    """打印结果"""
    print("\n" + "="*80)
    print(f"发现 {len(opportunities)} 个产品机会")
    print("="*80 + "\n")
    
    for i, opp in enumerate(opportunities[:5], 1):  # 只显示 top 5
        print(f"#{i} [{opp.source.upper()}] 评分：{opp.score}/100")
        print(f"   标题：{opp.title}")
        print(f"   链接：{opp.url}")
        print()
        print(f"   📖 项目介绍")
        print(f"   {opp.description[:200] if opp.description else opp.summary[:200]}...")
        print()
        print(f"   👤 一人公司可行性")
        print(f"   {opp.solo_feasibility[:150] if opp.solo_feasibility else '待分析'}...")
        print()
        print(f"   🤖 Agent 角色：{', '.join(opp.agent_roles) if opp.agent_roles else '待分析'}")
        print(f"   💰 启动成本：{opp.startup_cost or '待分析'}")
        print(f"   ⏱️ 多久见钱：{opp.time_to_revenue or '待分析'}")
        print(f"   📈 收入模式：{opp.revenue_model or '待分析'}")
        print(f"   🎯 月收入潜力：{opp.monthly_potential or '待分析'}")
        print(f"   ⚙️ 自动化率：{opp.automation_rate or '待分析'}")
        print(f"   📢 获客渠道：{opp.customer_acquisition or '待分析'}")
        print()
        print(f"   ⚠️ 风险")
        print(f"   {opp.risks[:150] if opp.risks else '待分析'}...")
        print()
        print(f"   🚀 第一步")
        print(f"   {opp.action_plan[:100] if opp.action_plan else '待分析'}...")
        print()
        print(f"   🔗 相关链接")
        print(f"   - 原始链接：{opp.source_url}")
        for link in opp.research_links[1:3]:  # 显示研究链接
            print(f"   - {link}")
        print()
        print("-"*80 + "\n")


def main():
    """主函数"""
    # 验证配置
    try:
        validate_config()
    except ValueError as e:
        print(f"❌ 配置错误：{e}")
        print("请检查 .env 文件配置")
        sys.exit(1)
    
    parser = argparse.ArgumentParser(description="调研 Agent - 发现产品机会")
    parser.add_argument('--test', action='store_true', help='测试模式')
    parser.add_argument('--debug', action='store_true', help='调试模式')
    parser.add_argument('--hn-limit', type=int, default=30, help='HN 获取数量')
    parser.add_argument('--ph-limit', type=int, default=20, help='PH 获取数量')
    parser.add_argument('--min-score', type=int, default=60, help='最低分数')
    parser.add_argument('--media-hours', type=int, default=48, help='中文媒体抓取时间窗口（小时）')
    parser.add_argument('--indie-limit', type=int, default=15, help='IndieHackers 获取数量')
    parser.add_argument('--reddit-limit', type=int, default=10, help='Reddit 获取数量')
    parser.add_argument('--github-limit', type=int, default=10, help='GitHub Trending 获取数量')
    parser.add_argument('--enable-agent-reach', action='store_true', help='启用 Agent Reach 桥接采集（X/YouTube/Reddit）')
    parser.add_argument('--ar-limit', type=int, default=10, help='Agent Reach 每平台抓取数量')
    parser.add_argument('--indie-mode', action='store_true', help='一人公司模式：专注 Indie Hacker/微 SaaS/自动化机会')
    parser.add_argument('--enable-github-issues', action='store_true', help='显式启用 GitHub issue 创建（默认关闭）')
    parser.add_argument('--enable-mvp-generation', action='store_true', help='显式启用 MVP 自动生成（默认关闭）')
    
    args = parser.parse_args()
    
    # 设置调试模式
    if args.debug:
        os.environ['DEBUG'] = 'true'
    
    global DEBUG
    DEBUG = args.debug or DEBUG
    
    # 设置日志
    logger = setup_logging()
    logger.info("Starting research agent...")
    
    # 检查 API Key
    if not BAILIAN_API_KEY:
        logger.error("BAILIAN_API_KEY not configured. Please set it in .env file.")
        print("错误：请配置 BAILIAN_API_KEY")
        print("1. 复制 .env.example 为 .env")
        print("2. 填写你的阿里百炼 API Key")
        sys.exit(1)
    
    # 测试模式
    if args.test:
        logger.info("Test mode: fetching sample data...")
        items = collect_data(hn_limit=5, ph_limit=3, media_hours=args.media_hours, indie_limit=min(5, args.indie_limit), reddit_limit=min(4, args.reddit_limit), github_limit=min(4, args.github_limit), enable_agent_reach=args.enable_agent_reach, ar_limit=min(5, args.ar_limit))
        print(f"Collected {len(items)} items")
        for item in items[:3]:
            print(f"  - {item['title']}")
        return
    
    # 正常运行
    items = collect_data(
        hn_limit=args.hn_limit,
        ph_limit=args.ph_limit,
        media_hours=args.media_hours,
        indie_limit=args.indie_limit,
        reddit_limit=args.reddit_limit,
        github_limit=args.github_limit,
        enable_agent_reach=args.enable_agent_reach,
        ar_limit=args.ar_limit,
    )
    opportunities = asyncio.run(analyze_items_async(items, min_score=args.min_score))

    if opportunities:
        # 机会去重：当日去重 + 跨天去重 + 一人公司重排
        opportunities = deduplicate_opportunities(opportunities)
        opportunities = deduplicate_across_days(opportunities, days=14)

        if not opportunities:
            print("本次机会均与近14天重复，已全部过滤")
            return

        opportunities = rerank_for_solo(opportunities)
        kept_candidates, filtered_candidates = _select_phase1_candidates(opportunities)

        save_results(opportunities)
        save_phase1_report(opportunities)
        feishu_doc_url = sync_report_to_feishu()
        print_phase1_results(kept_candidates, filtered_candidates, len(opportunities))
        if feishu_doc_url:
            print(f"Verified Feishu doc URL: {feishu_doc_url}")
        if kept_candidates:
            send_to_feishu(kept_candidates)
        else:
            print("No kept candidate to send via direct Feishu message")

        if args.enable_github_issues:
            create_github_issues(kept_candidates)
        else:
            print("GitHub issue creation disabled in Phase 1; use --enable-github-issues to override")

        if args.enable_mvp_generation:
            generate_mvps(kept_candidates)
        else:
            print("MVP generation disabled in Phase 1; use --enable-mvp-generation to override")
    else:
        print("未发现符合条件的机会")


if __name__ == "__main__":
    main()
