#!/usr/bin/env python3
"""Phase 2 screening: evidence-based assessment and narrative generation for solo-founder opportunities."""

import re
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from models.opportunity import Opportunity
from screening.constants import (
    FEEDBACK_FILE,
    FINAL_ACTION_7DAY_MVP,
    FINAL_ACTION_DROP,
    FINAL_ACTION_LANDING_PAGE,
    PHASE1_FILTER_LIMIT,
    PHASE2_BIG_PLAYER_TERMS,
    PHASE2_CATEGORY_PROFILES,
    PHASE2_CONCRETE_DELIVERABLE_TERMS,
    PHASE2_CONCRETE_PLAN_TERMS,
    PHASE2_DELIVERABLE_HINTS,
    PHASE2_GENERIC_ACQUISITION_TERMS,
    PHASE2_GENERIC_PLAN_TERMS,
    PHASE2_GENERIC_WEDGE_TERMS,
    PHASE2_HEAVY_DELIVERY_TERMS,
    PHASE2_KEEP_MIN_SCORE,
    PHASE2_PLATFORM_DEPENDENCY_TERMS,
    PHASE2_SIGNAL_WEAK_TERMS,
    PHASE2_SPECIFIC_ACQUISITION_TERMS,
    PHASE2_TRIGGER_HINTS,
    PHASE2_VAGUE_ACQUISITION_TERMS,
    PHASE2_WATCH_LIMIT,
    PHASE2_WATCH_MIN_SCORE,
    SOURCE_QUALITY,
    SOURCE_QUALITY_SCORE,
)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helper / utility functions
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').strip())


def _truncate(text: str, limit: int = 160) -> str:
    text = _clean_text(text)
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + '…'


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
        'reddit_pain': '从 Reddit 痛点帖子的发帖者、评论者和同类抱怨帖里直接约访，这些人已经表达了明确不满。',
        'saas_reviews': '从差评用户、竞品差评区和同类不满评论者里定向触达，这些人已经在为类似方案付费。',
        'appstore_reviews': '从对应 App 的差评用户、竞品差评区和评论里提到的替代方案用户中定向约访。',
        'github': '从相关仓库的 issue、discussion、star 用户和 README 反馈里找早期用户。',
        'github_trending': '从相关仓库的 issue、discussion、star 用户和 README 反馈里找早期用户。',
        'github_issues': '从对应仓库的 issue 提交者、评论者和相关集成服务商客户里定向约访。',
        'indiehackers': '从 IndieHackers 发帖作者、评论区和同类项目创始人网络中直接约访。',
        '36kr': '从报道里出现的赛道从业者、微信群和相关服务商客户名单中做定向外联。',
        'huxiu': '从报道里出现的赛道从业者、微信群和相关服务商客户名单中做定向外联。',
    }
    if assessment and assessment.first_users_hint:
        return assessment.first_users_hint + '。'
    return mapping.get(source, '从原始信号对应的社区、评论区和现有人脉里做定向外联，先拿到 20 个深访/试用用户。')


# ---------------------------------------------------------------------------
# Internal helper used by _cross_source_correlation
# ---------------------------------------------------------------------------

def _normalize_title(title: str) -> str:
    t = (title or '').lower()
    t = re.sub(r'https?://\S+', '', t)
    t = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


# ---------------------------------------------------------------------------
# Core assessment functions
# ---------------------------------------------------------------------------

def _build_phase2_assessment(opp: Opportunity) -> ScreeningAssessment:
    _, text_lower = _combined_signal_text(opp)
    profile = _pick_phase2_profile(text_lower)
    target_user = _extract_target_user(opp, profile)
    trigger_candidate = _extract_trigger_candidate(opp)
    deliverable_candidate = _extract_deliverable_candidate(opp)
    trigger_event = trigger_candidate or (profile['trigger'] if profile else '用户最着急解决这个问题时')
    deliverable = deliverable_candidate or (profile['deliverable'] if profile else '一个单点可收费结果')
    avoid_label = profile['avoid_label'] if profile else f'一个泛化复制"{opp.title}"的产品'
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
        strengths.append(f'切口已经压到"{_truncate(deliverable, limit=36)}"这类可收费结果')
    elif profile:
        evidence_score += 1
        adjusted_score += 3
        strengths.append(f'目标切口至少落在"{profile["category_label"]}"这个具体工作流上')
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
            keep_gaps.append('第一步仍然是"先做 MVP 再迭代"式模板话，没有落到首单交付动作')
            adjusted_score -= 8
        else:
            evidence_score += 1
            adjusted_score += 4
            strengths.append('首单动作已经落到可执行交付')
    else:
        keep_gaps.append('没有写清 7-14 天内怎么拿首单')
        adjusted_score -= 8

    source = (opp.source or '').lower()
    source_quality = SOURCE_QUALITY.get(source, 'hype')
    source_delta = SOURCE_QUALITY_SCORE.get(source_quality, 0)
    adjusted_score += source_delta
    if source_quality == 'pain':
        evidence_score += 2
        strengths.append(f'{opp.source} 是真实用户痛点信号源')
    elif source_quality == 'discussion':
        evidence_score += 1
        strengths.append(f'{opp.source} 更接近真实需求现场')
    elif source_quality == 'story':
        if re.search(r'\$\d|mrr', (opp.title or '').lower()):
            keep_gaps.append('这是成功案例信号，不是未满足需求本身')
            adjusted_score -= 3
    elif source_quality in ('hype', 'news'):
        if source == 'hn' and any(term in text_lower for term in ['how i', 'show hn', 'essay']):
            keep_gaps.append('这是经验分享/展示，不是用户催着付钱的强需求信号')
            adjusted_score -= 4
        elif source_quality == 'news':
            keep_gaps.append('媒体报道更像行业观察，不足以直接证明首单需求')

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

    enrichment_evidence = getattr(opp, 'enrichment_evidence_score', 0) or 0
    enrichment_competitors = getattr(opp, 'enrichment_competitor_count', 0) or 0
    enrichment_pain_posts = getattr(opp, 'enrichment_pain_post_count', 0) or 0
    if enrichment_evidence > 0:
        adjusted_score += enrichment_evidence
        evidence_score += min(3, enrichment_evidence // 2)
    if enrichment_pain_posts >= 5:
        strengths.append(f'Reddit 上有 {enrichment_pain_posts} 条相关痛点帖，需求信号较强')
    elif enrichment_pain_posts >= 2:
        strengths.append(f'Reddit 上有 {enrichment_pain_posts} 条相关痛点帖')
    if enrichment_competitors == 0:
        strengths.append('暂未发现直接竞品')
    elif enrichment_competitors >= 8:
        keep_gaps.append(f'搜索到 {enrichment_competitors} 个竞品/替代方案，市场已经较拥挤')
        adjusted_score -= 3

    cross_source_boost = getattr(opp, 'cross_source_boost', 0) or 0
    if cross_source_boost > 0:
        adjusted_score += cross_source_boost
        evidence_score += min(2, cross_source_boost // 4)
        strengths.append(f'同一痛点在多个独立数据源出现（跨源加分 +{cross_source_boost}）')

    feedback_boost = getattr(opp, 'feedback_boost', 0) or 0
    if feedback_boost > 0:
        adjusted_score += feedback_boost
        evidence_score += 2
        strengths.append('历史反馈中同类痛点已被验证可行')
    elif feedback_boost < 0:
        adjusted_score += feedback_boost
        keep_gaps.append('历史反馈中同类痛点验证失败过')

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
        kill_reasons.append('现在更多是"有人会讨论/会注册"，不是"有人会在 14 天内掏钱催你交付"。')
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


def _cross_source_correlation(opportunities: List[Opportunity]) -> None:
    """Find pain themes appearing across multiple independent source types and boost them.

    Mutates opportunities in-place by setting opp.cross_source_boost.
    """
    theme_buckets: Dict[str, Dict[str, Any]] = {}

    for opp in opportunities:
        tags = [t.lower() for t in (opp.tags or [])]
        title_words = set(_normalize_title(opp.title).split())
        theme_keys = set(tags) | {w for w in title_words if len(w) > 3}

        source_type = SOURCE_QUALITY.get((opp.source or '').lower(), 'hype')
        for key in theme_keys:
            if not key or len(key) < 3:
                continue
            bucket = theme_buckets.setdefault(key, {
                'source_types': set(),
                'opp_ids': [],
            })
            bucket['source_types'].add(source_type)
            bucket['opp_ids'].append(opp.id)

    opp_boosts: Dict[str, int] = defaultdict(int)
    for key, bucket in theme_buckets.items():
        unique_types = len(bucket['source_types'])
        if unique_types >= 3:
            boost = 8
        elif unique_types >= 2:
            boost = 5
        else:
            continue
        for opp_id in bucket['opp_ids']:
            opp_boosts[opp_id] = max(opp_boosts[opp_id], boost)

    for opp in opportunities:
        boost = opp_boosts.get(opp.id, 0)
        opp.cross_source_boost = boost


# ---------------------------------------------------------------------------
# Feedback functions
# ---------------------------------------------------------------------------

def _load_feedback() -> Dict[str, Any]:
    if not os.path.exists(FEEDBACK_FILE):
        return {}
    try:
        with open(FEEDBACK_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_feedback(data: Dict[str, Any]) -> None:
    with open(FEEDBACK_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _apply_feedback_boosts(opportunities: List[Opportunity]) -> None:
    """Apply score adjustments based on historical feedback on similar pain themes."""
    feedback = _load_feedback()
    if not feedback:
        return

    validated_themes: set[str] = set()
    failed_themes: set[str] = set()
    for fp, entry in feedback.items():
        tags = entry.get('tags', [])
        outcome = entry.get('outcome', '')
        for tag in tags:
            tag_lower = tag.lower()
            if outcome == 'validated':
                validated_themes.add(tag_lower)
            elif outcome == 'failed':
                failed_themes.add(tag_lower)

    for opp in opportunities:
        opp_tags = {t.lower() for t in (opp.tags or [])}
        if opp_tags & validated_themes:
            opp.feedback_boost = 10
        elif opp_tags & failed_themes:
            opp.feedback_boost = -5
        else:
            opp.feedback_boost = 0


# ---------------------------------------------------------------------------
# Display / narrative functions
# ---------------------------------------------------------------------------

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
    prefix = f'{target}在{trigger}，先为他们交付"{deliverable}"'
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
        return f'最可能先付钱的是 {target} 里刚经历过这个触发场景的人，先卖"{deliverable}"的 {model} 版本。'
    return f'现在还看不到 14 天内会主动掏钱的买家名单。理论上应先找 {target}，用"{deliverable}"试卖一单，但证据还不够。'


def _first_20_users_source(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    acquisition = _clean_text(opp.customer_acquisition)
    if acquisition and not _is_generic_acquisition_text(acquisition):
        return acquisition
    if acquisition:
        return f'{_default_first_users_source(opp, assessment)} 当前模型只给了"{acquisition}"这类泛渠道词，还不算真正的首客名单。'
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
        return f'目前并不存在明确的抗碾压逻辑。只要不把交付压缩成"{assessment.deliverable}"这种单结果，你就会回到和 {names} 正面拼功能的主战场。'
    if assessment.crowded_hits:
        category = assessment.category_label or assessment.crowded_hits[0]
        return f'只有把交付压到"{assessment.deliverable}"这一单结果，才可能避开 {category} 的功能清单战争。'
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
        return f'先卖一个只交付"{deliverable}"的 {model} 试点，目标客户锁定为 {target}。落地路径：{_truncate(plan, limit=180)}'
    return f'先卖一个只承诺"{deliverable}"的 {model} 试点，先用表单/脚本/人工兜底把首单交付出来。'


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
        return f'{names} 这类方案更偏通用平台，不会只为"{assessment.deliverable}"这个单结果优化；用户最后还是得自己补人工。'
    if assessment.crowded_hits:
        return f'现有替代方案大多覆盖泛需求，不会围绕"{assessment.deliverable}"这个触发场景给出可直接付费的单点交付。'
    return f'现有替代方案要么太泛，要么还是人工兜底，没把"{assessment.deliverable}"压成可直接购买的结果。'


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
    return f'{target} 会在 {scenario} 立刻感受到损失或延误；只要你直接交付"{deliverable}"，他们不需要先改流程就能试用。'


def _do_not_scale_boundary(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    not_crushed = _why_not_crushed(opp, assessment)
    return f'别做 {assessment.avoid_label}。{not_crushed}'


def _final_conclusion(opp: Opportunity, assessment: Optional[ScreeningAssessment] = None) -> str:
    assessment = assessment or _build_phase2_assessment(opp)
    action = _decision_label(opp.score, assessment.verdict)
    if assessment.verdict == 'keep':
        return f'{action}。先把"{assessment.deliverable}"卖给最先痛的那批 {assessment.target_user}，不要扩成功能平台。'
    if assessment.verdict == 'watch':
        return f'{action}。先验证 {assessment.target_user} 是否愿意为"{assessment.deliverable}"留下联系方式或预约沟通，再决定要不要做 7 天 MVP。'
    return f'{action}。{_filtered_reason(opp, assessment)}'


# ---------------------------------------------------------------------------
# Report helper functions
# ---------------------------------------------------------------------------

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


def _daily_rule_adjustment(opportunities: List[Opportunity], assessments: Optional[dict] = None) -> Dict[str, str]:
    assessments = assessments or {opp.id: _build_phase2_assessment(opp) for opp in opportunities}

    if not opportunities:
        return {
            'suggestion': '继续把"14 天内能收钱 + 首批 20 用户来源具体"当作硬门槛，不因为样本少就放松。',
            'evidence': '今天没有新的候选样本，当前最稳的做法仍然是先守住付费窗口和首客名单这两条线。',
        }

    candidates: List[Dict[str, Any]] = []

    def _pick_rule(key: str, hits: List[Opportunity], suggestion: str, evidence_builder) -> None:
        if not hits:
            return
        candidates.append({
            'key': key,
            'hits': len(hits),
            'suggestion': suggestion,
            'evidence': evidence_builder(hits),
        })

    generic_acquisition_hits = [
        opp for opp in opportunities
        if _acquisition_specificity_level(opp.customer_acquisition) == 0
    ]
    _pick_rule(
        'generic_acquisition',
        generic_acquisition_hits,
        '把"首批 20 用户来源仍是 SEO / 社媒 / 泛 cold outreach"的机会直接降为丢弃，不再给继续观察名额。',
        lambda hits: f'今天有 {len(hits)} 条样本的首客来源仍停留在泛渠道词，最典型的是「{hits[0].title}」。',
    )

    generic_plan_hits = [
        opp for opp in opportunities
        if _is_generic_action_plan(opp.action_plan)
    ]
    _pick_rule(
        'generic_plan',
        generic_plan_hits,
        '把"第一步还是先做 MVP 再迭代"的机会再降一档，除非同时给出可收费交付和具体客户名单。',
        lambda hits: f'今天有 {len(hits)} 条样本在首单动作上仍是模板话，继续保留只会稀释验证精力。',
    )

    crowded_frontline_hits = [
        opp for opp in opportunities
        if (assessments.get(opp.id) or _build_phase2_assessment(opp)).crowded_hits
        and (assessments.get(opp.id) or _build_phase2_assessment(opp)).frontline_hits
    ]
    _pick_rule(
        'crowded_frontline',
        crowded_frontline_hits,
        '把"落在大厂或成熟产品主战场"的机会直接过滤，不再给 watch 名额。',
        lambda hits: f'今天有 {len(hits)} 条样本同时踩中红海类目和平台原生能力，最典型的是「{hits[0].title}」。',
    )

    weak_story_source_hits = [
        opp for opp in opportunities
        if (
            (assessments.get(opp.id) or _build_phase2_assessment(opp)).verdict == 'drop'
            and (opp.source or '').lower() in {'hn', 'ph', 'indiehackers', '36kr', 'huxiu', 'tiehan'}
            and not _is_fast_payback_window(opp.time_to_revenue)
        )
    ]
    _pick_rule(
        'weak_story_source',
        weak_story_source_hits,
        '把"成功案例 / 媒体报道 / Show HN"默认当背景噪音，除非同时给出 14 天收钱窗口和具体外联名单。',
        lambda hits: f'今天有 {len(hits)} 条样本来源更像故事或报道，而不是用户催着付钱的前线信号。',
    )

    heavy_delivery_hits = [
        opp for opp in opportunities
        if (assessments.get(opp.id) or _build_phase2_assessment(opp)).heavy_delivery_hits
    ]
    _pick_rule(
        'heavy_delivery',
        heavy_delivery_hits,
        '把"需要长期实施 / 集成 / 定制交付"的机会直接判掉，别让服务化题目挤占验证名额。',
        lambda hits: f'今天有 {len(hits)} 条样本一开始就要求重交付，单人模型很难复制扩张。',
    )

    if candidates:
        priority = {
            'generic_acquisition': 5,
            'crowded_frontline': 4,
            'generic_plan': 3,
            'weak_story_source': 2,
            'heavy_delivery': 1,
        }
        best = max(candidates, key=lambda item: (item['hits'], priority.get(item['key'], 0)))
        return {
            'suggestion': best['suggestion'],
            'evidence': best['evidence'],
        }

    keep_exceptions = [
        opp for opp in opportunities
        if (
            (assessments.get(opp.id) or _build_phase2_assessment(opp)).verdict in {'keep', 'watch'}
            and (opp.source or '').lower() in {'hn', 'ph', 'indiehackers', '36kr', 'huxiu', 'tiehan'}
            and _acquisition_specificity_level(opp.customer_acquisition) >= 2
            and not _is_generic_action_plan(opp.action_plan)
            and _is_fast_payback_window(opp.time_to_revenue)
        )
    ]
    if keep_exceptions:
        sample = keep_exceptions[0]
        return {
            'suggestion': '别按来源一刀切丢掉 HN / IndieHackers / 媒体信号；只要同时满足 14 天收钱窗口和具体首客名单，允许继续跟进。',
            'evidence': f'今天至少有 1 条这类例外样本成立，代表案例是「{sample.title}」。',
        }

    return {
        'suggestion': '继续把"14 天内能收钱 + 首批 20 用户来源具体"当作 keep 前置条件，本轮没有足够证据支持放松。',
        'evidence': '今天的样本没有形成单一新模式，先守住现有硬门槛比频繁改规则更稳。',
    }
