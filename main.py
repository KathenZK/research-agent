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
from dataclasses import dataclass, field
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
PHASE2_WATCH_LIMIT = 3
PHASE2_KEEP_MIN_SCORE = 83
PHASE2_WATCH_MIN_SCORE = 72
FINAL_ACTION_LANDING_PAGE = '做 landing page 验证'
FINAL_ACTION_7DAY_MVP = '做 7 天 MVP 验证'
FINAL_ACTION_DROP = '丢弃'


@dataclass
class ScreeningAssessment:
    raw_score: int
    adjusted_score: int
    verdict: str
    evidence_score: int
    strengths: List[str] = field(default_factory=list)
    keep_gaps: List[str] = field(default_factory=list)
    kill_reasons: List[str] = field(default_factory=list)
    crowded_hits: List[str] = field(default_factory=list)
    frontline_hits: List[str] = field(default_factory=list)
    heavy_delivery_hits: List[str] = field(default_factory=list)
    platform_dependency_hits: List[str] = field(default_factory=list)
    category_label: str = ""
    avoid_label: str = ""
    target_user: str = ""
    trigger_event: str = ""
    deliverable: str = ""
    first_users_hint: str = ""


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


def rerank_for_solo(opportunities: List[Opportunity], assessments: Optional[dict] = None) -> List[Opportunity]:
    """Phase 2 重排：先看 verdict，再看证据强度和筛选分。"""
    assessments = assessments or {opp.id: _build_phase2_assessment(opp) for opp in opportunities}
    verdict_order = {'keep': 0, 'watch': 1, 'drop': 2}

    def sort_key(opp: Opportunity):
        assessment = assessments.get(opp.id) or _build_phase2_assessment(opp)
        return (
            verdict_order.get(assessment.verdict, 3),
            -assessment.evidence_score,
            -assessment.adjusted_score,
            -assessment.raw_score,
        )

    return sorted(opportunities, key=sort_key)


def _clean_text(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').strip())


def _truncate(text: str, limit: int = 160) -> str:
    text = _clean_text(text)
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + '…'


PHASE2_CATEGORY_PROFILES = [
    {
        'name': 'billing_analytics',
        'terms': ['stripe', 'billing', 'mrr', 'churn', 'failed payment', 'subscription analytics', '支付', '订阅分析', '营收分析'],
        'category_label': '支付/订阅分析',
        'avoid_label': '完整的 Stripe 分析仪表盘',
        'default_target': '使用 Stripe 的 20-200 人 SaaS 团队创始人或营收负责人',
        'trigger': '每周复盘 MRR、流失和失败扣款时',
        'deliverable': '一份可直接执行的 failed payment 与流失诊断报告',
        'first_users_hint': '去 Indie Hackers、Stripe 开发者社区和讨论 churn / failed payment 的 SaaS 创始人帖子里定向约 20 人',
        'crowded': True,
    },
    {
        'name': 'project_management',
        'terms': ['project management', 'task management', 'kanban', 'roadmap', 'sprint', '项目管理', '任务管理', '协作工具'],
        'category_label': '项目管理',
        'avoid_label': '一个新的项目管理工具',
        'default_target': '2-10 人远程产品团队的创始人或项目负责人',
        'trigger': '周会前或 sprint 切换时',
        'deliverable': '一份自动清理过期任务并标出 blocker 的周会摘要',
        'first_users_hint': '去 Indie Hackers、Linear/Jira/Notion 模板帖和远程团队社群里约首批 20 个团队负责人',
        'crowded': True,
    },
    {
        'name': 'ai_coding',
        'terms': ['code generation', 'coding assistant', 'ai coding', 'developer tool', '开发工具', '代码生成', 'claude code', 'copilot', 'agent computer'],
        'category_label': 'AI 开发工具',
        'avoid_label': '一个通用 AI 编程助手',
        'default_target': '维护单一代码栈的 3-20 人开发团队负责人',
        'trigger': '需要新建模块、补测试或做迁移时',
        'deliverable': '一个针对单一框架的脚手架、测试补全或迁移包',
        'first_users_hint': '去 GitHub issues/discussions、Claude Code/Copilot 讨论区和开发者社群里找首批 20 个团队',
        'crowded': True,
    },
    {
        'name': 'transcription',
        'terms': ['speech to text', 'voice', 'dictation', 'transcription', '语音', '转文字', '语音输入', '语音识别'],
        'category_label': '语音转写',
        'avoid_label': '一个通用语音输入工具',
        'default_target': '每天要开会、访谈或写长文的 Mac 知识工作者',
        'trigger': '会议、访谈或边走边记刚结束时',
        'deliverable': '一份结构化纪要、待办列表和可直接发送的草稿',
        'first_users_hint': '去写作者社区、播客/访谈从业者群和高频会议团队里约首批 20 个重度用户',
        'crowded': True,
    },
    {
        'name': 'focus_audio',
        'terms': ['white noise', 'focus app', 'meditation', '白噪音', '专注', 'focus', '音频'],
        'category_label': '专注/白噪音',
        'avoid_label': '一个白噪音或专注应用',
        'default_target': '需要长时间深度工作的远程知识工作者',
        'trigger': '准备进入 60-90 分钟深度工作前',
        'deliverable': '一套带番茄钟和专注复盘的深度工作 session',
        'first_users_hint': '去深度工作、ADHD、远程办公社区里找愿意做 7 天专注实验的首批用户',
        'crowded': True,
    },
    {
        'name': 'content_training',
        'terms': ['how i', 'best practice', 'playbook', 'training', 'course', '教程', '培训', '内容'],
        'category_label': '内容/培训',
        'avoid_label': '一个泛 AI 编程内容站或培训课',
        'default_target': '想把 AI 编程流程标准化的 3-20 人工程团队负责人',
        'trigger': '团队开始要求统一 prompt、review checklist 和交付规范时',
        'deliverable': '一份基于真实代码库的 AI 编程 playbook 与评审清单',
        'first_users_hint': '去 HN 评论区、工程管理社群和已有 AI 编程实践分享帖下定向约访 20 个团队负责人',
        'crowded': False,
    },
]

PHASE2_BIG_PLAYER_TERMS = {
    'apple': 'Apple',
    'ios': 'Apple',
    'macos': 'Apple',
    'google': 'Google',
    'microsoft': 'Microsoft',
    'openai': 'OpenAI',
    'anthropic': 'Anthropic',
    'claude': 'Claude',
    'github copilot': 'GitHub Copilot',
    'copilot': 'GitHub Copilot',
    'notion': 'Notion',
    'linear': 'Linear',
    'jira': 'Jira',
    'slack': 'Slack',
    'figma': 'Figma',
    'stripe': 'Stripe',
    'deepgram': 'Deepgram',
}

PHASE2_HEAVY_DELIVERY_TERMS = [
    'implementation service', 'consulting service', 'custom implementation', 'system integration',
    'enterprise onboarding', 'deployment service', 'marketplace', 'two-sided', 'hardware', 'logistics',
    '代运营', '咨询服务', '定制开发', '实施服务', '系统集成', '私有化部署', '硬件', '供应链', '双边市场'
]
PHASE2_GENERIC_ACQUISITION_TERMS = ['seo', 'product hunt', 'social media', '社交媒体', '付费广告', '广告', '联盟', 'app store', 'aso']
PHASE2_SPECIFIC_ACQUISITION_TERMS = ['评论区', '帖子', '私信', '外联', '邮件', '名单', '社群', 'issue', 'discussion', 'subreddit', 'slack', 'discord', '论坛', '微信群', '评论者', '创始人', '群', '用户访谈']
PHASE2_VAGUE_ACQUISITION_TERMS = ['cold outreach', 'outbound', 'linkedin', '朋友圈', '转介绍', 'partnership', 'bd', '销售', '社群运营', '社区运营', 'founder network']
PHASE2_SIGNAL_WEAK_TERMS = ['融资', 'funding', 'launch', 'show hn', 'how i', 'essay', 'story', '案例', '教程', 'newsletter']
PHASE2_PLATFORM_DEPENDENCY_TERMS = ['api变更', 'api 变更', '官方', '自带', '依赖单一', '单一平台', 'policy', 'policies', '平台策略']
PHASE2_GENERIC_PLAN_TERMS = ['先做mvp', '先做 MVP', '根据反馈迭代', '再迭代', '验证需求', '上线看看', '先上线', 'build mvp', 'iterate', 'launch on product hunt']
PHASE2_CONCRETE_PLAN_TERMS = ['试点', '审计', '脚本', '人工', '报价', '收取', '收费', '外联', '迁移', '报告', '清单', '访谈', '名单', 'pilot', 'audit', 'migration', 'report']
PHASE2_CONCRETE_DELIVERABLE_TERMS = ['审计', '报告', '清单', '脚本', '迁移', 'migration', 'report', 'audit', 'playbook', '摘要', '诊断', '回复建议', 'review', 'checklist', '试点', 'pilot']
PHASE2_GENERIC_WEDGE_TERMS = ['tool', 'tools', 'platform', 'assistant', 'copilot', 'workspace', 'system', '产品', '工具', '平台', '系统', '应用']
PHASE2_TRIGGER_HINTS = [
    (('refund', '退款', 'chargeback', '高风险订单'), '出现退款争议、退款滥用或高风险订单时'),
    (('failed payment', '支付失败', '扣款失败'), 'failed payment 开始堆积时'),
    (('churn', '流失'), '流失率抬头时'),
    (('support', '客服', 'ticket', '工单'), '工单积压或回复超时时'),
    (('migration', '迁移'), '准备做迁移或切换栈时'),
    (('playbook', '评审清单', '代码库'), '团队准备把 AI 编程流程落进真实代码库时'),
]
PHASE2_DELIVERABLE_HINTS = [
    (('refund', '退款', 'chargeback'), '一份退款滥用审计报告'),
    (('failed payment', '支付失败', '扣款失败'), '一份 failed payment 与流失诊断报告'),
    (('support', '客服', 'ticket', '工单'), '一份工单分流与回复建议清单'),
    (('migration', '迁移'), '一个单一框架迁移包'),
    (('playbook', '评审清单', '代码库'), '一份基于真实代码库的 AI 编程评审清单与 playbook'),
]


def _score_grade(score: int) -> str:
    if score >= 86:
        return 'A'
    if score >= 78:
        return 'B'
    if score >= 68:
        return 'C'
    return 'D'


def _signal_strength_label(score: int) -> str:
    mapping = {
        'A': '高',
        'B': '中高',
        'C': '待验证',
        'D': '弱',
    }
    return mapping[_score_grade(score)]


def _decision_label(score: int, verdict: Optional[str] = None) -> str:
    if verdict == 'keep':
        return FINAL_ACTION_7DAY_MVP
    if verdict == 'watch':
        return FINAL_ACTION_LANDING_PAGE
    if verdict == 'drop':
        return FINAL_ACTION_DROP
    grade = _score_grade(score)
    mapping = {
        'A': FINAL_ACTION_7DAY_MVP,
        'B': FINAL_ACTION_LANDING_PAGE,
        'C': FINAL_ACTION_LANDING_PAGE,
        'D': FINAL_ACTION_DROP,
    }
    return mapping[grade]


def _is_fast_payback_window(text: str) -> bool:
    normalized = _clean_text(text).lower()
    if not normalized:
        return False
    return any(token in normalized for token in ['7天', '14天', '两周', '2周', 'two week', '<7', '7 days', '14 days'])


def _is_medium_payback_window(text: str) -> bool:
    normalized = _clean_text(text).lower()
    if not normalized:
        return False
    return any(token in normalized for token in ['30天', '30 天', '30 days', '30days', '一个月'])


def _combined_signal_text(opp: Opportunity) -> tuple[str, str]:
    raw = ' '.join([
        opp.title or '',
        opp.summary or '',
        opp.description or '',
        opp.risks or '',
        ' '.join(opp.tags or []),
        opp.customer_acquisition or '',
        opp.solo_feasibility or '',
        opp.action_plan or '',
    ]).strip()
    return raw, raw.lower()


def _match_terms(text: str, phrases: List[str]) -> List[str]:
    hits = []
    for phrase in phrases:
        if phrase and phrase in text:
            hits.append(phrase)
    return hits


def _normalize_term(term: str) -> str:
    return term.replace('_', ' ').replace('/', ' / ').strip()


def _pick_phase2_profile(text_lower: str) -> Optional[dict]:
    best = None
    best_score = 0
    for profile in PHASE2_CATEGORY_PROFILES:
        score = sum(1 for term in profile['terms'] if term in text_lower)
        if score > best_score:
            best = profile
            best_score = score
    return best if best_score >= 2 else None


def _extract_specific_phrase(text: str, patterns: List[str], limit: int = 72) -> str:
    haystack = _clean_text(text)
    if not haystack:
        return ''
    for pattern in patterns:
        match = re.search(pattern, haystack, re.IGNORECASE)
        if not match:
            continue
        candidate = _clean_text(match.group(1))
        candidate = re.sub(r'^(?:一版|一个|一份|一次|每周一次的|每周|一周内交付的|只交付|只卖|针对|面向)\s*', '', candidate, flags=re.IGNORECASE)
        candidate = re.sub(r'^[的\s]+', '', candidate)
        candidate = re.sub(r'[，。；,:：]+$', '', candidate)
        candidate = _truncate(candidate, limit=limit)
        if candidate:
            return candidate
    return ''


def _looks_specific_deliverable(text: str) -> bool:
    normalized = _clean_text(text).lower()
    if not normalized:
        return False
    if any(term in normalized for term in PHASE2_GENERIC_WEDGE_TERMS):
        return False
    return any(term in normalized for term in PHASE2_CONCRETE_DELIVERABLE_TERMS)


def _extract_trigger_candidate(opp: Opportunity) -> str:
    _, text_lower = _combined_signal_text(opp)
    for keywords, trigger in PHASE2_TRIGGER_HINTS:
        if any(keyword in text_lower for keyword in keywords):
            return trigger
    return ''


def _extract_deliverable_candidate(opp: Opportunity) -> str:
    haystacks = [
        opp.action_plan or '',
        opp.description or '',
        opp.summary or '',
    ]
    patterns = [
        r'(?:先卖|先做|先交付|先提供|交付|提供|输出)(?:一版|一个|一份|一次|每周一次的|每周|一周内交付的|只交付|只卖)?([^，。；\n]{6,80})',
        r'(?:卖|收取)[^，。；\n]{0,16}(?:的)?([^，。；\n]{6,80}(?:报告|审计|清单|脚本|迁移包|playbook|pilot|试点|诊断|摘要|方案))',
    ]
    for text in haystacks:
        candidate = _extract_specific_phrase(text, patterns)
        if candidate and _looks_specific_deliverable(candidate):
            return candidate

    _, text_lower = _combined_signal_text(opp)
    for keywords, deliverable in PHASE2_DELIVERABLE_HINTS:
        if any(keyword in text_lower for keyword in keywords):
            return deliverable
    return ''


def _extract_target_user(opp: Opportunity, profile: Optional[dict]) -> str:
    haystack = ' '.join([opp.description or '', opp.summary or ''])
    patterns = [
        r'目标用户为([^。；\n]+)',
        r'目标用户是([^。；\n]+)',
        r'面向([^。；\n]+)',
        r'目标客户为([^。；\n]+)',
        r'target users? (?:are|is)\s+([^.;\n]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, haystack, re.IGNORECASE)
        if match:
            candidate = _truncate(match.group(1), limit=60)
            if candidate:
                return candidate
    if profile:
        return profile['default_target']
    tags = {tag.lower() for tag in opp.tags or []}
    if 'b2b' in tags:
        return '有明确业务流程痛点的 B2B 团队负责人'
    if 'b2c' in tags:
        return '高频使用该场景、愿意先付费试用的重度个人用户'
    return '对这个问题已经在用手工流程兜底的人'


def _is_generic_acquisition_text(text: str) -> bool:
    normalized = _clean_text(text).lower()
    if not normalized:
        return True
    has_specific = any(token in normalized for token in PHASE2_SPECIFIC_ACQUISITION_TERMS)
    generic_hits = [token for token in PHASE2_GENERIC_ACQUISITION_TERMS if token in normalized]
    return bool(generic_hits) and not has_specific


def _has_specific_acquisition_text(text: str) -> bool:
    return _acquisition_specificity_level(text) >= 2


def _acquisition_specificity_level(text: str) -> int:
    normalized = _clean_text(text).lower()
    if not normalized:
        return 0
    if _is_generic_acquisition_text(text):
        return 0

    specific_hits = sum(1 for token in PHASE2_SPECIFIC_ACQUISITION_TERMS if token in normalized)
    vague_hits = sum(1 for token in PHASE2_VAGUE_ACQUISITION_TERMS if token in normalized)
    named_community = bool(re.search(r'r/[a-z0-9_]+|github|reddit|hacker news|indie hackers|shopify|stripe|slack|discord|微信群|论坛', normalized))
    countable_targets = bool(re.search(r'(前|首批|先找)\s*\d{1,3}\s*(个)?(用户|客户|团队|公司|商家|founders?|teams?|companies?)', normalized))

    if (specific_hits >= 2) or (specific_hits >= 1 and (named_community or countable_targets)):
        return 2
    if countable_targets and not vague_hits:
        return 1
    if len(normalized) >= 30 and specific_hits >= 1 and vague_hits == 0:
        return 1
    return 0


def _is_generic_action_plan(text: str) -> bool:
    normalized = _clean_text(text).lower()
    if not normalized:
        return True
    generic_hit = any(token.lower() in normalized for token in PHASE2_GENERIC_PLAN_TERMS)
    concrete_hit = any(token.lower() in normalized for token in PHASE2_CONCRETE_PLAN_TERMS)
    if generic_hit and not concrete_hit:
        return True
    return not concrete_hit and len(normalized) < 24


def _default_first_users_source(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
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
    if assessment and assessment.first_users_hint:
        return assessment.first_users_hint + '。'
    return mapping.get(source, '从原始信号对应的社区、评论区和现有人脉里做定向外联，先拿到 20 个深访/试用用户。')


def _build_phase2_assessment(opp: Opportunity) -> ScreeningAssessment:
    _, text_lower = _combined_signal_text(opp)
    profile = _pick_phase2_profile(text_lower)
    target_user = _extract_target_user(opp, profile)
    trigger_candidate = _extract_trigger_candidate(opp)
    deliverable_candidate = _extract_deliverable_candidate(opp)
    trigger_event = trigger_candidate or (profile['trigger'] if profile else '用户最着急解决这个问题时')
    deliverable = deliverable_candidate or (profile['deliverable'] if profile else '一个单点可收费结果')
    avoid_label = profile['avoid_label'] if profile else f'一个泛化复制“{opp.title}”的产品'
    first_users_hint = profile['first_users_hint'] if profile else ''

    raw_score = int(opp.score or 0)
    adjusted_score = raw_score
    evidence_score = 0
    strengths: List[str] = []
    keep_gaps: List[str] = []
    crowded_hits: List[str] = []
    frontline_hits: List[str] = []
    heavy_delivery_hits: List[str] = []
    platform_dependency_hits: List[str] = []
    kill_reasons: List[str] = []

    if _is_fast_payback_window(opp.time_to_revenue):
        evidence_score += 2
        adjusted_score += 6
        strengths.append(f'见钱周期已压到 {opp.time_to_revenue}')
    elif _is_medium_payback_window(opp.time_to_revenue):
        keep_gaps.append('给出的见钱周期仍是 30 天量级，离 14 天首单还有距离')
        adjusted_score -= 9
    else:
        keep_gaps.append('没有看到 14 天内能成交的付费窗口')
        adjusted_score -= 12

    acquisition_level = _acquisition_specificity_level(opp.customer_acquisition)
    if acquisition_level >= 2:
        evidence_score += 2
        adjusted_score += 5
        strengths.append('前 20 个用户来源相对具体')
    elif acquisition_level == 1:
        keep_gaps.append('首批用户来源写了方向，但还没有具体到马上可开找的帖子、评论者或客户名单')
        adjusted_score -= 4
    else:
        keep_gaps.append('首批用户来源还停留在泛渠道词，没有变成可执行名单')
        adjusted_score -= 9

    if deliverable_candidate or trigger_candidate:
        evidence_score += 1
        adjusted_score += 4
        strengths.append(f'切口已经压到“{_truncate(deliverable, limit=36)}”这类可收费结果')
    elif profile:
        evidence_score += 1
        adjusted_score += 3
        strengths.append(f'目标切口至少落在“{profile["category_label"]}”这个具体工作流上')
    else:
        keep_gaps.append('机会描述仍然太宽，像类目词，不像一个可先收钱的窄工作流')
        adjusted_score -= 8

    if opp.startup_cost:
        startup_cost = _clean_text(opp.startup_cost).lower()
        if any(token in startup_cost for token in ['<$1k', '$1-5k', '<$5k']):
            adjusted_score += 3
            strengths.append(f'启动成本压在 {opp.startup_cost}')
        elif any(token in startup_cost for token in ['>$20k', '$5-20k']):
            keep_gaps.append(f'启动成本已经来到 {opp.startup_cost}')
            adjusted_score -= 7

    if opp.automation_rate:
        auto_text = _clean_text(opp.automation_rate).lower()
        if '90' in auto_text:
            adjusted_score += 2
            strengths.append(f'可自动化比例达到 {opp.automation_rate}')
        elif '50' in auto_text:
            adjusted_score -= 3

    if opp.action_plan:
        if _is_generic_action_plan(opp.action_plan):
            keep_gaps.append('第一步仍然是“先做 MVP 再迭代”式模板话，没有落到首单交付动作')
            adjusted_score -= 8
        else:
            evidence_score += 1
            adjusted_score += 4
            strengths.append('首单动作已经落到可执行交付')
    else:
        keep_gaps.append('没有写清 7-14 天内怎么拿首单')
        adjusted_score -= 8

    source = (opp.source or '').lower()
    if source.startswith('reddit') or source in {'github', 'github_trending', 'x'}:
        evidence_score += 1
        adjusted_score += 2
        strengths.append(f'{opp.source} 更接近真实需求现场')
    elif source == 'indiehackers' and re.search(r'\$\d|mrr', (opp.title or '').lower()):
        keep_gaps.append('这是成功案例信号，不是未满足需求本身')
        adjusted_score -= 8
    elif source == 'hn' and any(term in text_lower for term in ['how i', 'show hn', 'essay']):
        keep_gaps.append('这是经验分享/展示，不是用户催着付钱的强需求信号')
        adjusted_score -= 7
    elif source in {'36kr', 'huxiu', 'tiehan'}:
        keep_gaps.append('媒体报道更像行业观察，不足以直接证明首单需求')
        adjusted_score -= 6

    if profile and profile.get('crowded'):
        crowded_hits.append(profile['category_label'])
        adjusted_score -= 14

    broad_market_hits = _match_terms(text_lower, ['project management', 'white noise', 'speech to text', 'code generation', 'agent computer', '生产力工具'])
    for hit in broad_market_hits:
        label = _normalize_term(hit)
        if label not in crowded_hits:
            crowded_hits.append(label)
    adjusted_score -= min(10, max(0, len(broad_market_hits) - 1) * 4)

    risks_text = _clean_text(opp.risks).lower()
    for term, label in PHASE2_BIG_PLAYER_TERMS.items():
        if term in text_lower or term in risks_text:
            if label not in frontline_hits:
                frontline_hits.append(label)
    if any(token in risks_text for token in ['竞争激烈', '大厂', '官方', '自带', '原生']) and frontline_hits:
        adjusted_score -= 16
    elif frontline_hits and profile and profile.get('crowded'):
        adjusted_score -= 12

    heavy_delivery_hits.extend(_match_terms(text_lower, PHASE2_HEAVY_DELIVERY_TERMS))
    if heavy_delivery_hits:
        adjusted_score -= 18
        keep_gaps.append('交付明显偏向重实施/重集成，不像能被单人稳定复制的高毛利模型')

    platform_dependency_hits.extend(_match_terms(risks_text, PHASE2_PLATFORM_DEPENDENCY_TERMS))
    if platform_dependency_hits:
        adjusted_score -= 9

    weak_signal_hits = _match_terms(text_lower, PHASE2_SIGNAL_WEAK_TERMS)
    if weak_signal_hits and source in {'hn', 'ph', 'indiehackers', '36kr', 'huxiu'}:
        adjusted_score -= 6

    if any(token in text_lower for token in ['all-in-one', '平台', 'suite', 'workspace', '系统']) and not profile:
        adjusted_score -= 8
        keep_gaps.append('叙述里还是平台/全家桶语言，没有压缩到单结果交付')

    fast_payback = _is_fast_payback_window(opp.time_to_revenue)
    generic_action_plan = _is_generic_action_plan(opp.action_plan)
    weak_source_signal = bool(weak_signal_hits) and source in {'hn', 'ph', 'indiehackers', '36kr', 'huxiu'}
    hard_filter_reasons: List[str] = []
    if heavy_delivery_hits:
        hard_filter_reasons.append('交付仍偏重实施/集成，单人模型会被服务化吞掉。')
    if crowded_hits and frontline_hits:
        hard_filter_reasons.append('切口仍落在大厂和成熟产品的主战场。')
    if acquisition_level == 0 and generic_action_plan:
        hard_filter_reasons.append('首客名单和首单动作都还是模板话，缺少可执行验证路径。')
    if weak_source_signal and not fast_payback and acquisition_level < 2:
        hard_filter_reasons.append('信号更像内容/案例热度，不像前线用户在催首单交付。')

    adjusted_score = max(0, min(95, adjusted_score))

    if crowded_hits and frontline_hits:
        names = '、'.join(frontline_hits[:2])
        category = profile['category_label'] if profile else '这个类目'
        kill_reasons.append(f'这是 {category} 的主战场，用户默认会先比较 {names} 这类现成方案；单人新项目很容易被拖进功能和价格战。')
    elif crowded_hits:
        category = crowded_hits[0]
        kill_reasons.append(f'{category} 已经是成熟红海类目，当前信号没有暴露出一个足够锋利、能先收钱的切口。')

    if heavy_delivery_hits:
        kill_reasons.append('首单也许能靠定制/实施拿下，但交付会持续吞掉创始人时间，不符合一人公司高毛利模型。')

    if platform_dependency_hits and frontline_hits:
        names = '、'.join(frontline_hits[:2])
        kill_reasons.append(f'价值链过度挂在 {names} 等平台上，平台补功能或改接口就会削弱你的定价权。')

    if keep_gaps and not _is_fast_payback_window(opp.time_to_revenue):
        kill_reasons.append('现在更多是“有人会讨论/会注册”，不是“有人会在 14 天内掏钱催你交付”。')
    kill_reasons.extend(hard_filter_reasons[:2])

    critical_red_flags = bool(heavy_delivery_hits) or (bool(crowded_hits) and bool(frontline_hits))
    if (
        adjusted_score >= PHASE2_KEEP_MIN_SCORE
        and evidence_score >= 5
        and fast_payback
        and acquisition_level >= 2
        and not generic_action_plan
        and (profile or deliverable_candidate or trigger_candidate)
        and not critical_red_flags
        and not hard_filter_reasons
    ):
        verdict = 'keep'
    elif (
        adjusted_score >= PHASE2_WATCH_MIN_SCORE
        and evidence_score >= 4
        and acquisition_level >= 1
        and not generic_action_plan
        and (profile or deliverable_candidate or trigger_candidate)
        and not critical_red_flags
        and not weak_source_signal
        and len(crowded_hits) <= 1
        and len(frontline_hits) <= 1
        and not hard_filter_reasons
    ):
        verdict = 'watch'
    else:
        verdict = 'drop'

    return ScreeningAssessment(
        raw_score=raw_score,
        adjusted_score=adjusted_score,
        verdict=verdict,
        evidence_score=evidence_score,
        strengths=strengths,
        keep_gaps=keep_gaps,
        kill_reasons=kill_reasons,
        crowded_hits=crowded_hits,
        frontline_hits=frontline_hits,
        heavy_delivery_hits=[_normalize_term(hit) for hit in heavy_delivery_hits[:3]],
        platform_dependency_hits=[_normalize_term(hit) for hit in platform_dependency_hits[:3]],
        category_label=profile['category_label'] if profile else '',
        avoid_label=avoid_label,
        target_user=target_user,
        trigger_event=trigger_event,
        deliverable=deliverable,
        first_users_hint=first_users_hint,
    )


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


def _wedge_statement(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    target = assessment.target_user or '一小撮已经在手工兜底的人'
    trigger = assessment.trigger_event or '用户最着急解决问题时'
    deliverable = assessment.deliverable or '一个单点可收费结果'
    prefix = f'{target}在{trigger}，先为他们交付“{deliverable}”'
    if assessment.verdict == 'keep':
        return f'别做{assessment.avoid_label}，先盯住这一个结果：{prefix}；先用脚本 + 人工兜底把首单卖出去。'
    if assessment.verdict == 'watch':
        return f'如果继续跟进，只验证这一刀是否成立：{prefix}。在证据更硬之前，不要扩成{assessment.avoid_label}。'
    return f'除非能先证明 {prefix}愿意付钱，否则别做{assessment.avoid_label}。'


def _phase2_evidence_label(assessment: ScreeningAssessment) -> str:
    if assessment.verdict == 'keep' or assessment.evidence_score >= 5:
        return '硬证据较强'
    if assessment.evidence_score >= 4:
        return '证据中等'
    if assessment.evidence_score >= 2:
        return '证据偏弱'
    return '证据不足'


def _phase2_signal_summary(opp: Opportunity, assessment: ScreeningAssessment) -> str:
    parts = [_phase2_evidence_label(assessment)]
    if _is_fast_payback_window(opp.time_to_revenue):
        parts.append('14 天收钱窗口明确')
    else:
        parts.append('14 天收钱窗口不足')

    acquisition_level = _acquisition_specificity_level(opp.customer_acquisition)
    if acquisition_level >= 2:
        parts.append('首客名单明确')
    elif acquisition_level == 1:
        parts.append('首客名单只有方向')
    else:
        parts.append('首客名单缺失')

    if _is_generic_action_plan(opp.action_plan):
        parts.append('首单动作仍模板化')
    else:
        parts.append('首单动作具体')
    return ' / '.join(parts)


def _who_pays_in_14_days(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    model = _clean_text(opp.revenue_model or '一次性 setup fee 或按月订阅')
    target = assessment.target_user or '最痛的那批用户'
    deliverable = assessment.deliverable or '一个明确结果'
    if _is_fast_payback_window(opp.time_to_revenue):
        return f'最可能先付钱的是 {target} 里刚经历过这个触发场景的人，先卖“{deliverable}”的 {model} 版本。'
    return f'现在还看不到 14 天内会主动掏钱的买家名单。理论上应先找 {target}，用“{deliverable}”试卖一单，但证据还不够。'


def _first_20_users_source(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    acquisition = _clean_text(opp.customer_acquisition)
    if acquisition and not _is_generic_acquisition_text(acquisition):
        return acquisition
    if acquisition:
        return f'{_default_first_users_source(opp, assessment)} 当前模型只给了“{acquisition}”这类泛渠道词，还不算真正的首客名单。'
    return _default_first_users_source(opp, assessment)


def _why_solo_buildable(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    reasons = []
    if opp.solo_feasibility:
        reasons.append(_truncate(opp.solo_feasibility, limit=140))
    if opp.startup_cost:
        reasons.append(f"启动成本预估 {opp.startup_cost}")
    if opp.automation_rate:
        reasons.append(f"可自动化比例 {opp.automation_rate}")
    if assessment.strengths:
        reasons.extend(assessment.strengths[:2])
    if reasons:
        return '；'.join(reasons[:3]) + '。'
    return '先从人工服务 + 轻工具交付起步，单人也能在需求验证期内完成交付。'


def _why_not_crushed(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    if assessment.frontline_hits:
        names = '、'.join(assessment.frontline_hits[:2])
        return f'目前并不存在明确的抗碾压逻辑。只要不把交付压缩成“{assessment.deliverable}”这种单结果，你就会回到和 {names} 正面拼功能的主战场。'
    if assessment.crowded_hits:
        category = assessment.category_label or assessment.crowded_hits[0]
        return f'只有把交付压到“{assessment.deliverable}”这一单结果，才可能避开 {category} 的功能清单战争。'
    risk = _truncate(opp.risks, limit=120)
    base = '这是一个足够窄的工作流，先靠速度、人工兜底和场景理解收钱，通常不值得大玩家立刻下场复制。'
    if risk:
        return f"{base} 当前最需要防的是 {risk}"
    return base


def _smallest_paid_mvp(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    plan = _clean_text(opp.action_plan)
    deliverable = assessment.deliverable or '一个单点结果'
    target = assessment.target_user or '首批目标用户'
    model = _clean_text(opp.revenue_model or '一次性服务费')
    if plan:
        return f'先卖一个只交付“{deliverable}”的 {model} 试点，目标客户锁定为 {target}。落地路径：{_truncate(plan, limit=180)}'
    return f'先卖一个只承诺“{deliverable}”的 {model} 试点，先用表单/脚本/人工兜底把首单交付出来。'


def _high_frequency_scenario(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    return assessment.trigger_event or '用户开始用人工流程兜底这个问题时'


def _current_alternative(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    if assessment.frontline_hits:
        names = '、'.join(assessment.frontline_hits[:2])
        return f'人工流程、Excel/表单，加上 {names} 这类通用或原生方案。'
    if assessment.category_label:
        return f'人工流程、Excel/表单，以及泛 {assessment.category_label} 工具。'
    return '人工流程、Excel/表单和零散脚本。'


def _why_existing_solution_bad(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    if assessment.frontline_hits:
        names = '、'.join(assessment.frontline_hits[:2])
        return f'{names} 这类方案更偏通用平台，不会只为“{assessment.deliverable}”这个单结果优化；用户最后还是得自己补人工。'
    if assessment.crowded_hits:
        return f'现有替代方案大多覆盖泛需求，不会围绕“{assessment.deliverable}”这个触发场景给出可直接付费的单点交付。'
    return f'现有替代方案要么太泛，要么还是人工兜底，没把“{assessment.deliverable}”压成可直接购买的结果。'


def _why_now_worth_doing(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    reasons = list(assessment.strengths[:2])
    if opp.source:
        reasons.append(f'信号直接来自 {opp.source} 的前线讨论')
    if not reasons:
        reasons.append('这个问题已经逼着用户在真实工作流里找临时解法')
    return '；'.join(reasons[:3]) + '。'


def _why_fit_for_user(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    target = assessment.target_user or '这批用户'
    scenario = assessment.trigger_event or '问题爆发时'
    deliverable = assessment.deliverable or '这个结果'
    return f'{target} 会在 {scenario} 立刻感受到损失或延误；只要你直接交付“{deliverable}”，他们不需要先改流程就能试用。'


def _do_not_scale_boundary(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    not_crushed = _why_not_crushed(opp, assessment)
    return f'别做 {assessment.avoid_label}。{not_crushed}'


def _final_conclusion(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    action = _decision_label(opp.score, assessment.verdict)
    if assessment.verdict == 'keep':
        return f'{action}。先把“{assessment.deliverable}”卖给最先痛的那批 {assessment.target_user}，不要扩成功能平台。'
    if assessment.verdict == 'watch':
        return f'{action}。先验证 {assessment.target_user} 是否愿意为“{assessment.deliverable}”留下联系方式或预约沟通，再决定要不要做 7 天 MVP。'
    return f'{action}。{_filtered_reason(opp, assessment)}'


def _primary_candidate(kept: List[Opportunity], watchlist: List[Opportunity]) -> tuple[Optional[Opportunity], List[Opportunity]]:
    if kept:
        return kept[0], watchlist
    if watchlist:
        return watchlist[0], watchlist[1:]
    return None, []


def _unique_candidate_card_lines(opp: Opportunity, assessment: ScreeningAssessment) -> List[str]:
    return [
        '## 今日唯一候选',
        f'- 切口名称: {assessment.deliverable}',
        f'- 目标用户: {assessment.target_user}',
        f'- 高频场景: {_high_frequency_scenario(opp, assessment)}',
        f'- 当前替代方案: {_current_alternative(opp, assessment)}',
        f'- 为什么现有方案不好: {_why_existing_solution_bad(opp, assessment)}',
        f'- 为什么现在值得做: {_why_now_worth_doing(opp, assessment)}',
        f'- 为什么适合用户: {_why_fit_for_user(opp, assessment)}',
        f'- 6 周最小收费版本: {_smallest_paid_mvp(opp, assessment)}',
        f'- 首批 20 用户从哪里来: {_first_20_users_source(opp, assessment)}',
        f'- 验证动作（landing page / 7 day MVP / 丢弃）: **{_decision_label(opp.score, assessment.verdict)}**',
        f'- 不该做大的边界: {_do_not_scale_boundary(opp, assessment)}',
        f'- 最终结论: {_final_conclusion(opp, assessment)}',
        f'- 来源: `{opp.source}`',
        f'- 链接: {opp.url}',
        '',
    ]


def _filtered_reason(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    reasons = list(assessment.kill_reasons[:2])
    if not reasons and assessment.keep_gaps:
        reasons.append(assessment.keep_gaps[0])
    if not reasons:
        reasons.append('当前更像泛机会，不是今天就该切进去的 wedge。')
    if len(reasons) < 2 and len(assessment.keep_gaps) > 1:
        reasons.append(assessment.keep_gaps[1])
    return ' '.join(reasons[:2])


def _pseudo_opportunity_type(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    if assessment.category_label:
        return f'{assessment.category_label}型机会'
    if assessment.deliverable:
        return f'{_truncate(assessment.deliverable, limit=28)}型机会'
    if opp.title:
        return f'{_truncate(opp.title, limit=28)}型机会'
    return '泛机会'


def _concise_drop_reason(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    if assessment.kill_reasons:
        return _truncate(assessment.kill_reasons[0], limit=72)
    if assessment.keep_gaps:
        return _truncate(assessment.keep_gaps[0], limit=72)
    return '今天看不到值得继续验证的付费与分发证据。'


def _not_worth_doing_lines(dropped: List[Opportunity], assessments: dict) -> List[str]:
    lines: List[str] = []
    for opp in dropped[:5]:
        assessment = assessments.get(opp.id) or _build_phase2_assessment(opp)
        lines.append(
            f'- {_pseudo_opportunity_type(opp, assessment)}: {_concise_drop_reason(opp, assessment)}'
        )

    fallback_lines = [
        '- 泛流量故事型机会: 缺少 14 天内谁会先付钱的明确信号，今天继续看只会放大自我感动。',
        '- 大厂主战场型机会: 没有更窄的结果交付切口，进入就是和平台能力硬碰硬。',
        '- 泛需求工具型机会: 首批 20 用户名单与触达动作不具体，今天不值得继续投入。',
        '- 重交付服务型机会: 一开始就要靠长期定制才能成立，不符合一人快速验证边界。',
        '- 证据不足型机会: 讨论热度可以保留观察，但不到今天就该升级验证的程度。',
    ]
    if len(lines) < 3:
        for fallback in fallback_lines:
            if fallback not in lines:
                lines.append(fallback)
            if len(lines) >= 3:
                break
    return lines[:5]


def _annotate_phase2_assessments(opportunities: List[Opportunity]) -> dict:
    assessments = {}
    for opp in opportunities:
        assessment = _build_phase2_assessment(opp)
        assessments[opp.id] = assessment
        opp.phase2_adjusted_score = assessment.adjusted_score
        opp.phase2_decision_label = _decision_label(assessment.adjusted_score, assessment.verdict)
        opp.phase2_verdict = assessment.verdict
        opp.phase2_wedge = _wedge_statement(opp, assessment)
        opp.phase2_who_pays = _who_pays_in_14_days(opp, assessment)
        opp.phase2_first_users = _first_20_users_source(opp, assessment)
        opp.phase2_solo_logic = _why_solo_buildable(opp, assessment)
        opp.phase2_not_crushed = _why_not_crushed(opp, assessment)
        opp.phase2_paid_mvp = _smallest_paid_mvp(opp, assessment)
        opp.phase2_target_user = assessment.target_user
        opp.phase2_trigger_event = assessment.trigger_event
        opp.phase2_deliverable = assessment.deliverable
        opp.phase2_current_alternative = _current_alternative(opp, assessment)
        opp.phase2_why_existing_bad = _why_existing_solution_bad(opp, assessment)
        opp.phase2_why_now = _why_now_worth_doing(opp, assessment)
        opp.phase2_why_fit_for_user = _why_fit_for_user(opp, assessment)
        opp.phase2_boundary = _do_not_scale_boundary(opp, assessment)
        opp.phase2_final_conclusion = _final_conclusion(opp, assessment)
        opp.phase2_filtered_reason = _filtered_reason(opp, assessment)
        opp.phase2_raw_score = assessment.raw_score
        opp.phase2_evidence_score = assessment.evidence_score
        opp.score = assessment.adjusted_score
    return assessments


def _bucket_phase2_candidates(opportunities: List[Opportunity], assessments: Optional[dict] = None) -> tuple[List[Opportunity], List[Opportunity], List[Opportunity]]:
    assessments = assessments or {opp.id: _build_phase2_assessment(opp) for opp in opportunities}
    kept: List[Opportunity] = []
    watchlist: List[Opportunity] = []
    dropped: List[Opportunity] = []
    for opp in opportunities:
        assessment = assessments.get(opp.id)
        verdict = assessment.verdict if assessment else 'drop'
        if verdict == 'keep' and not kept:
            kept.append(opp)
        elif verdict == 'watch' and len(watchlist) < PHASE2_WATCH_LIMIT:
            watchlist.append(opp)
        elif verdict != 'keep' and len(dropped) < PHASE1_FILTER_LIMIT:
            dropped.append(opp)
    return kept, watchlist, dropped


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
            '缺的不是更高的分数，而是一个同时满足“14 天可收钱 + 首批用户名单明确 + 不正面撞大厂主战场”的切口。',
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


def _sanitize_secret_text(text: str, secrets: List[str]) -> str:
    sanitized = text or ''
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, '***')
    sanitized = re.sub(r'("app_id":"?)[^",\s]+', r'\1***', sanitized)
    sanitized = re.sub(r'("app_secret":"?)[^",\s]+', r'\1***', sanitized)
    return sanitized


def _resolve_feishu_runtime() -> tuple[Optional[str], Optional[str], Optional[str]]:
    node_candidates = []
    detected_node = shutil.which('node')
    if detected_node:
        node_candidates.append(detected_node)
    node_candidates.extend(['/opt/homebrew/bin/node', '/usr/local/bin/node'])

    node_bin = next((path for path in node_candidates if path and os.path.exists(path)), None)
    if not node_bin:
        return None, None, 'node runtime not found; install Node.js or add node to PATH'

    roots: List[str] = []
    existing_node_path = os.environ.get('NODE_PATH', '')
    if existing_node_path:
        roots.extend([p.strip() for p in existing_node_path.split(os.pathsep) if p.strip()])

    openclaw_bin = shutil.which('openclaw')
    if openclaw_bin:
        package_root = os.path.dirname(os.path.realpath(openclaw_bin))
        roots.append(os.path.join(package_root, 'node_modules'))

    roots.extend([
        '/opt/homebrew/lib/node_modules/openclaw/node_modules',
        '/usr/local/lib/node_modules/openclaw/node_modules',
    ])

    checked = []
    seen = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        checked.append(root)
        if os.path.exists(os.path.join(root, '@larksuiteoapi', 'node-sdk')):
            return node_bin, root, None

    checked_text = ', '.join(checked) if checked else '(none)'
    return node_bin, None, f'@larksuiteoapi/node-sdk not found; checked NODE_PATH candidates: {checked_text}'


def _feishu_sync_blocker_message(text: str) -> Optional[str]:
    normalized = (text or '').lower()
    if not normalized:
        return None
    if 'node runtime not found' in normalized:
        return 'node runtime not found; install Node.js or add node to PATH'
    if '@larksuiteoapi/node-sdk not found' in text:
        return text.strip()
    if 'feishu_app_id / feishu_app_secret not configured' in normalized:
        return 'FEISHU_APP_ID / FEISHU_APP_SECRET not configured'
    if 'connect eperm 127.0.0.1:7897' in normalized:
        return 'outbound Feishu API access is blocked by the current proxy/network sandbox (cannot connect to 127.0.0.1:7897)'
    if 'getaddrinfo enotfound open.feishu.cn' in normalized or 'enotfound open.feishu.cn' in normalized:
        return 'outbound DNS/network access to open.feishu.cn is unavailable in the current environment'
    if any(token in normalized for token in ['econnrefused', 'etimedout', 'network error', 'socket hang up']) and 'feishu' in normalized:
        return 'outbound network access to Feishu API is unavailable in the current environment'
    return None


def sync_report_to_feishu(md_filename: str = 'latest_phase1.md', title: Optional[str] = None) -> Optional[str]:
    """将指定 markdown 报告同步到 Feishu Doc，并返回可验证的真实 docx URL。"""
    if not FEISHU_DOC_SYNC_ENABLED:
        print("Feishu doc sync disabled, skipping")
        return None
    app_id, app_secret = _resolve_feishu_credentials()
    if _looks_like_placeholder(app_id) or _looks_like_placeholder(app_secret):
        print("Feishu doc sync blocked: FEISHU_APP_ID / FEISHU_APP_SECRET not configured")
        return None

    md_path = os.path.join(DATA_DIR, md_filename)
    if not os.path.exists(md_path):
        print(f"{md_filename} not found, skipping Feishu doc sync")
        return None

    title = title or f"Solo Venture Screener-{datetime.now().strftime('%Y-%m-%d')}"
    node_bin, node_path, runtime_error = _resolve_feishu_runtime()
    if runtime_error:
        print(f"Feishu doc sync blocked: {runtime_error}")
        return None

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
  const insertIndex = hIdx + 1;
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

        env['NODE_PATH'] = f"{node_path}:{env.get('NODE_PATH', '')}" if env.get('NODE_PATH') else node_path
        result = subprocess.run(
            [node_bin, script_path],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        out = (result.stdout or '').strip() or (result.stderr or '').strip()
        out = _sanitize_secret_text(out, [app_id or '', app_secret or ''])
        url = _extract_real_feishu_doc_url(out)
        if result.returncode == 0 and url:
            print(f'Feishu daily doc: {url}')
            return url
        blocker = _feishu_sync_blocker_message(out)
        if blocker:
            print(f'Feishu doc sync blocked: {blocker}')
            return None
        raise RuntimeError(out or 'unknown feishu doc sync error')
    except Exception as e:
        err_text = _sanitize_secret_text(str(e), [app_id or '', app_secret or ''])
        blocker = _feishu_sync_blocker_message(err_text)
        if blocker:
            print(f'Feishu doc sync blocked: {blocker}')
        else:
            print(f'Feishu doc sync failed: {err_text}')
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
            signal_label = _signal_strength_label(getattr(opp, 'phase2_adjusted_score', None) or opp.score)
            validation_action = getattr(opp, 'phase2_decision_label', '') or opp.decision_label()
            data = {
                "title": f"🚀 {opp.title[:50]} - {validation_action}",
                "body": f"""## 📊 机会评估

- **机会信号**: {signal_label}
- **验证动作**: {validation_action}
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


def print_phase1_results(kept: List[Opportunity], watchlist: List[Opportunity], dropped: List[Opportunity], total_count: int, assessments: Optional[dict] = None):
    """打印 Phase 1 screener 摘要。"""
    assessments = assessments or {}
    primary, remaining_watchlist = _primary_candidate(kept, watchlist)
    print("\n" + "=" * 80)
    print(f"Phase 1 Solo Venture Screener | 候选池 {total_count} 条")
    print("=" * 80 + "\n")

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
    
    for i, opp in enumerate(opportunities[:5], 1):  # 只显示 top 5
        print(f"#{i} [{opp.source.upper()}] {opp.decision_label()} | 信号：{_signal_strength_label(opp.display_score())}")
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


def _finalize_top0_run(reason: str):
    save_phase1_report([], {}, run_notes=[reason])
    feishu_doc_url = sync_report_to_feishu()
    print_phase1_results([], [], [], 0, {})
    if feishu_doc_url:
        print(f"Verified Feishu doc URL: {feishu_doc_url}")
    print("No kept candidate to send via direct Feishu message")
    print("GitHub issue creation disabled in Phase 1; use --enable-github-issues to override")
    print("MVP generation disabled in Phase 1; use --enable-mvp-generation to override")


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
            _finalize_top0_run("本次命中的机会与近 14 天重复，未产生新的 Top1/Watchlist。")
            return

        assessments = _annotate_phase2_assessments(opportunities)
        opportunities = rerank_for_solo(opportunities, assessments)
        kept_candidates, watch_candidates, dropped_candidates = _bucket_phase2_candidates(opportunities, assessments)

        save_results(opportunities)
        save_phase1_report(opportunities, assessments)
        feishu_doc_url = sync_report_to_feishu()
        print_phase1_results(kept_candidates, watch_candidates, dropped_candidates, len(opportunities), assessments)
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
        _finalize_top0_run("本次采集或分析未产出可排序候选；已输出 Top0 报告供后续排查。")


if __name__ == "__main__":
    main()
