#!/usr/bin/env python3
"""
调研 Agent - 发现产品机会（一人公司视角）

用法:
    python3 main.py              # 正常运行
    python3 main.py --test       # 测试模式
    python3 main.py --debug      # 调试模式
    python3 main.py --weekly-report  # 生成深筛周报
    python3 main.py --feedback   # 录入历史机会反馈

配置:
    复制 .env.example 为 .env 并填写 API Key
"""

import os
import sys
import json
import asyncio
import argparse
import hashlib
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DEBUG, DATA_DIR, LOG_DIR, BAILIAN_API_KEY, validate_config
from enrichers import WebEnricher
from collectors import (
    AgentReachBridge, AppStoreReviewsCollector, ChineseMediaCollector,
    GitHubIssuesCollector, GitHubTrendingCollector, HNCollector, PHCollector,
    RedditPainCollector, SaaSReviewsCollector,
    V2EXCollector, ZhihuCollector, SspaiCollector,
)
from collectors.reddit import RedditCollector
from analyzers import BailianAnalyzer
from models import Opportunity

from screening.constants import SOURCE_QUALITY, SOURCE_QUALITY_SCORE
from screening.phase2 import (
    _build_phase2_assessment, _annotate_phase2_assessments,
    _bucket_phase2_candidates, rerank_for_solo,
    _cross_source_correlation, _apply_feedback_boosts,
    _daily_rule_adjustment, _decision_label, _signal_strength_label,
    _filtered_reason, _load_feedback, _save_feedback,
    _normalize_title,
)
from reports import save_phase1_report, save_top10_report, print_phase1_results, print_results
from reports.weekly_report import save_weekly_report, _fingerprint_opportunity, _restore_opportunity_from_dict
from integrations import sync_report_to_feishu, send_to_feishu
from integrations.github_issues import create_github_issues
from mvp_generator import MVPGenerator


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging():
    import logging as loglib
    log_file = os.path.join(LOG_DIR, f"research_{datetime.now().strftime('%Y%m%d')}.log")
    loglib.basicConfig(
        level=loglib.DEBUG if DEBUG else loglib.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[loglib.FileHandler(log_file), loglib.StreamHandler()],
    )
    return loglib.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def collect_data(
    hn_limit=10, ph_limit=5, media_hours=48,
    reddit_limit=10, github_limit=10,
    enable_agent_reach=False, ar_limit=10,
    enable_app_store_reviews=True, app_store_review_limit=15,
    enable_github_pain_issues=True, github_pain_limit=15,
    reddit_pain_limit=15,
    enable_saas_reviews=True, saas_review_limit=12,
    v2ex_limit=15, zhihu_limit=15, sspai_limit=10,
) -> List[dict]:
    """收集数据 -- 按信号质量分组采集"""
    import logging
    logger = logging.getLogger(__name__)
    items = []

    # --- Pain-point sources (highest signal quality) ---
    if enable_app_store_reviews:
        logger.info(f"Fetching App Store reviews (limit={app_store_review_limit})...")
        items.extend(AppStoreReviewsCollector().fetch(limit=app_store_review_limit))

    if enable_github_pain_issues:
        logger.info(f"Fetching GitHub issue pains (limit={github_pain_limit})...")
        items.extend(GitHubIssuesCollector().fetch(limit=github_pain_limit))

    logger.info(f"Fetching Reddit pain signals (limit={reddit_pain_limit})...")
    items.extend(RedditPainCollector().fetch(limit=reddit_pain_limit))

    if enable_saas_reviews:
        logger.info(f"Fetching SaaS review complaints (limit={saas_review_limit})...")
        items.extend(SaaSReviewsCollector().fetch(limit=saas_review_limit))

    # --- Chinese pain-point sources ---
    logger.info(f"Fetching V2EX pain signals (limit={v2ex_limit})...")
    items.extend(V2EXCollector().fetch(limit=v2ex_limit))

    logger.info(f"Fetching Zhihu pain signals (limit={zhihu_limit})...")
    items.extend(ZhihuCollector().fetch(limit=zhihu_limit))

    logger.info(f"Fetching Sspai articles (limit={sspai_limit})...")
    items.extend(SspaiCollector().fetch(limit=sspai_limit))

    # --- Discussion sources ---
    logger.info(f"Fetching GitHub Trending (limit={github_limit})...")
    items.extend(GitHubTrendingCollector().fetch(limit=github_limit))

    if not enable_agent_reach:
        logger.info(f"Fetching Reddit (limit={reddit_limit})...")
        items.extend(RedditCollector().fetch(limit=reddit_limit))

    # --- Hype / news sources ---
    logger.info(f"Fetching HN (limit={hn_limit})...")
    items.extend(HNCollector.fetch(limit=hn_limit))

    logger.info(f"Fetching PH (limit={ph_limit})...")
    items.extend(PHCollector.fetch(limit=ph_limit))

    logger.info(f"Fetching Chinese Media (hours={media_hours})...")
    items.extend(ChineseMediaCollector.fetch(hours=media_hours, limit=20))

    # --- Agent Reach bridge ---
    if enable_agent_reach:
        logger.info(f"Fetching Agent Reach sources (limit={ar_limit})...")
        ar = AgentReachBridge(DATA_DIR)
        health = ar.check_health()
        for platform, fetcher in [('x', ar.fetch_x), ('youtube', ar.fetch_youtube), ('reddit', ar.fetch_reddit)]:
            if health.get(platform):
                items.extend(fetcher(limit=ar_limit))
            else:
                logger.info(f"Skip Agent Reach {platform} (unhealthy)")

    logger.info(f"Collected {len(items)} total items")
    return items


# ---------------------------------------------------------------------------
# Analysis (with enrichment)
# ---------------------------------------------------------------------------

def analyze_items(items: List[dict], min_score: int = 60) -> List[Opportunity]:
    return asyncio.run(analyze_items_async(items, min_score=min_score))


async def analyze_items_async(items: List[dict], min_score: int = 60) -> List[Opportunity]:
    """异步分析项目（含 enrichment 注入）"""
    import logging
    logger = logging.getLogger(__name__)

    if not BAILIAN_API_KEY:
        logger.error("BAILIAN_API_KEY not configured")
        return []

    for item in items:
        source = (item.get('source') or '').lower()
        item['source_quality'] = SOURCE_QUALITY.get(source, 'hype')

    logger.info(f"Running web enrichment for {len(items)} items...")
    enricher = WebEnricher()
    try:
        enrichment_map = await enricher.batch_enrich_async(items)
        logger.info(f"Enrichment completed: {len(enrichment_map)} results")
    except Exception as e:
        logger.warning(f"Enrichment failed (continuing without): {e}")
        enrichment_map = {}

    analyzer = BailianAnalyzer()
    logger.info(f"Analyzing {len(items)} items (min_score={min_score})...")
    opportunities = await analyzer.batch_analyze_async(items, min_score=min_score, enrichment_map=enrichment_map)

    for opp in opportunities:
        enrichment = enrichment_map.get(str(opp.id))
        if enrichment:
            opp.enrichment_evidence_score = enrichment.evidence_score
            opp.enrichment_competitor_count = enrichment.competitor_count
            opp.enrichment_pain_post_count = enrichment.pain_post_count
            opp.enrichment_summary = enrichment.enrichment_summary
            opp.enrichment_page_content = enrichment.page_content

    logger.info(f"Found {len(opportunities)} opportunities")
    return opportunities


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _normalize_title_local(title: str) -> str:
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
        blocked = ('utm_', 'spm', 'from', 'source', 'ref', 'ref_src', 'fbclid', 'gclid', 'igshid', 'mkt_')
        clean_q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=False) if not k.lower().startswith(blocked)]
        clean_q.sort(key=lambda kv: kv[0])
        return urlunparse((scheme, netloc, path, '', urlencode(clean_q, doseq=True), ''))
    except Exception:
        return (url or '').strip()


def _fingerprint_opp(opp: Opportunity) -> str:
    title_norm = _normalize_title_local(opp.title)
    canonical_url = _normalize_url(opp.url or opp.source_url or '')
    domain = ''
    try:
        domain = urlparse(canonical_url).netloc.lower()
    except Exception:
        pass
    return hashlib.sha1(f"{title_norm[:160]}|{domain}|{canonical_url}".encode('utf-8')).hexdigest()


def _load_seen_fingerprints(days: int = 14):
    seen_file = os.path.join(DATA_DIR, 'seen_fingerprints.json')
    cutoff = datetime.now() - timedelta(days=days)
    data = {'items': []}
    if os.path.exists(seen_file):
        try:
            with open(seen_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {'items': []}
    kept, seen_map = [], {}
    for it in data.get('items', []):
        ts, fp = it.get('seen_at', ''), it.get('fp', '')
        try:
            dt = datetime.fromisoformat(ts)
        except Exception:
            continue
        if dt >= cutoff and fp:
            kept.append({'fp': fp, 'seen_at': ts})
            seen_map[fp] = dt
    return seen_file, kept, seen_map


def deduplicate_across_days(opportunities: List[Opportunity], days: int = 14) -> List[Opportunity]:
    seen_file, kept_items, seen_map = _load_seen_fingerprints(days=days)
    fresh = []
    for opp in opportunities:
        fp = _fingerprint_opp(opp)
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
    best = {}
    for opp in opportunities:
        key = _normalize_title_local(opp.title)[:120]
        if not key:
            continue
        old = best.get(key)
        if old is None or opp.score > old.score:
            best[key] = opp
    return list(best.values())


# ---------------------------------------------------------------------------
# Data persistence
# ---------------------------------------------------------------------------

def save_results(opportunities: List[Opportunity]):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_file = os.path.join(DATA_DIR, f"opportunities_{timestamp}.json")
    with open(json_file, 'w', encoding='utf-8') as f:
        try:
            json.dump([opp.to_dict() for opp in opportunities], f, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            json.dump([{'id': opp.id, 'title': opp.title, 'score': opp.score} for opp in opportunities], f, ensure_ascii=False, indent=2)
    latest_file = os.path.join(DATA_DIR, "latest.json")
    try:
        with open(latest_file, 'w', encoding='utf-8') as f:
            json.dump([opp.to_dict() for opp in opportunities], f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    print(f"Saved to {json_file}")
    cleanup_old_data(retention_days=14)


def cleanup_old_data(retention_days: int = 14):
    cutoff = datetime.now() - timedelta(days=retention_days)
    pattern = re.compile(r'^opportunities_(\d{8})_(\d{6})\.json$')
    removed = 0
    for name in os.listdir(DATA_DIR):
        m = pattern.match(name)
        if not m:
            continue
        try:
            dt = datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S')
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


# ---------------------------------------------------------------------------
# MVP generation
# ---------------------------------------------------------------------------

def generate_mvps(opportunities: List[Opportunity]):
    print("\nGenerating MVPs...")
    generator = MVPGenerator()
    generated = 0
    for opp in opportunities[:2]:
        try:
            opp_dict = {
                'title': opp.title, 'summary': opp.summary,
                'description': opp.description or opp.summary,
                'score': opp.score, 'revenue_model': opp.revenue_model or 'Subscription',
                'startup_cost': opp.startup_cost or '$1-5k',
                'time_to_revenue': opp.time_to_revenue or '30 days',
                'monthly_potential': opp.monthly_potential or '$10-50k',
                'automation_rate': opp.automation_rate or '90%+',
                'agent_roles': opp.agent_roles or ['Development Agent'],
            }
            project_dir = generator.generate(opp_dict)
            if project_dir:
                generated += 1
                print(f"Generated: {project_dir}")
        except Exception as e:
            print(f"Failed to generate MVP for {opp.title}: {e}")
    print(f"\nGenerated {generated}/{len(opportunities[:2])} MVPs")


# ---------------------------------------------------------------------------
# Feedback CLI
# ---------------------------------------------------------------------------

def run_feedback_cli():
    """Interactive CLI for recording feedback on recent opportunities."""
    latest_file = os.path.join(DATA_DIR, 'latest.json')
    if not os.path.exists(latest_file):
        print("No latest.json found. Run the agent first.")
        return
    try:
        with open(latest_file, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as e:
        print(f"Error reading latest.json: {e}")
        return

    candidates = [item for item in raw if isinstance(item, dict) and item.get('phase2_verdict') in ('keep', 'watch')]
    if not candidates:
        print("No kept/watch opportunities found in latest run.")
        return

    feedback = _load_feedback()
    print(f"\n{'='*60}\nFeedback for {len(candidates)} recent opportunities\n{'='*60}\n")

    for idx, item in enumerate(candidates, 1):
        title = item.get('title', 'Unknown')[:60]
        verdict = item.get('phase2_verdict', '?')
        opp = _restore_opportunity_from_dict(item)
        fp = _fingerprint_opportunity(opp)

        if fp in feedback:
            print(f"  #{idx} {title} [{verdict}] -- already has feedback")
            continue

        print(f"\n  #{idx} {title} [{verdict}]")
        print(f"      {item.get('description', '')[:120]}\n")
        print("  Action? (p)ursued / (s)kipped / (i)rrelevant / Enter to skip:")
        action_input = input("  > ").strip().lower()
        if not action_input:
            continue
        action = {'p': 'pursued', 's': 'skipped', 'i': 'irrelevant'}.get(action_input[0], '')
        if not action:
            continue

        outcome = ''
        if action == 'pursued':
            print("  Outcome? (v)alidated / (f)ailed / (o)ngoing / Enter to skip:")
            oi = input("  > ").strip().lower()
            outcome = {'v': 'validated', 'f': 'failed', 'o': 'ongoing'}.get(oi[0] if oi else '', '')

        print("  Notes (optional):")
        notes = input("  > ").strip()

        feedback[fp] = {
            'title': item.get('title', ''), 'action': action, 'outcome': outcome,
            'notes': notes, 'tags': item.get('tags', []), 'rated_at': datetime.now().isoformat(),
        }

    _save_feedback(feedback)
    print(f"\nFeedback saved ({len(feedback)} entries total)")


# ---------------------------------------------------------------------------
# Finalize empty run
# ---------------------------------------------------------------------------

def _finalize_top0_run(reason: str):
    rule_adjustment = _daily_rule_adjustment([], {})
    save_phase1_report([], {}, run_notes=[reason])
    feishu_doc_url = sync_report_to_feishu()
    print_phase1_results([], [], [], 0, {}, rule_adjustment=rule_adjustment)
    if feishu_doc_url:
        print(f"Verified Feishu doc URL: {feishu_doc_url}")
    print("No kept candidate to send via direct Feishu message")
    print("GitHub issue creation disabled in Phase 1; use --enable-github-issues to override")
    print("MVP generation disabled in Phase 1; use --enable-mvp-generation to override")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="调研 Agent - 发现产品机会")
    parser.add_argument('--test', action='store_true', help='测试模式')
    parser.add_argument('--debug', action='store_true', help='调试模式')
    parser.add_argument('--feedback', action='store_true', help='录入对近期机会的反馈')
    parser.add_argument('--weekly-report', action='store_true', help='基于历史快照生成深筛周报')
    parser.add_argument('--weekly-days', type=int, default=7, help='深筛周报回看天数（默认 7）')
    parser.add_argument('--hn-limit', type=int, default=30)
    parser.add_argument('--ph-limit', type=int, default=20)
    parser.add_argument('--min-score', type=int, default=60)
    parser.add_argument('--media-hours', type=int, default=48)
    parser.add_argument('--reddit-limit', type=int, default=10)
    parser.add_argument('--github-limit', type=int, default=10)
    parser.add_argument('--enable-agent-reach', action='store_true')
    parser.add_argument('--ar-limit', type=int, default=10)
    parser.add_argument('--disable-app-store-reviews', action='store_true', help='禁用 App Store 差评采集（默认开启）')
    parser.add_argument('--app-store-review-limit', type=int, default=15)
    parser.add_argument('--disable-github-pain-issues', action='store_true', help='禁用 GitHub issue 痛点采集（默认开启）')
    parser.add_argument('--github-pain-limit', type=int, default=15)
    parser.add_argument('--reddit-pain-limit', type=int, default=15)
    parser.add_argument('--disable-saas-reviews', action='store_true', help='禁用 SaaS 评论差评采集（默认开启）')
    parser.add_argument('--saas-review-limit', type=int, default=12)
    parser.add_argument('--v2ex-limit', type=int, default=15, help='V2EX 痛点帖采集数量（默认 15）')
    parser.add_argument('--zhihu-limit', type=int, default=15, help='知乎痛点采集数量（默认 15）')
    parser.add_argument('--sspai-limit', type=int, default=10, help='少数派文章采集数量（默认 10）')
    parser.add_argument('--indie-mode', action='store_true', help='一人公司模式：痛点源翻倍、热度源减半、降低 keep 阈值、自动生成 Landing Page')
    parser.add_argument('--enable-github-issues', action='store_true')
    parser.add_argument('--enable-mvp-generation', action='store_true')
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.debug:
        os.environ['DEBUG'] = 'true'

    global DEBUG
    DEBUG = args.debug or DEBUG

    logger = setup_logging()
    logger.info("Starting research agent...")

    if args.feedback:
        run_feedback_cli()
        return

    if args.weekly_report:
        report_file = save_weekly_report(window_days=max(1, args.weekly_days))
        if report_file:
            print(f"Weekly report ready: {report_file}")
        return

    # --indie-mode: pain sources get double quota, hype sources halved, lower keep threshold
    if args.indie_mode:
        logger.info("Indie mode active: boosting pain sources, reducing hype sources")
        args.app_store_review_limit = max(args.app_store_review_limit, 20)
        args.github_pain_limit = max(args.github_pain_limit, 20)
        args.reddit_pain_limit = max(args.reddit_pain_limit, 20)
        args.saas_review_limit = max(args.saas_review_limit, 16)
        args.v2ex_limit = max(args.v2ex_limit, 20)
        args.zhihu_limit = max(args.zhihu_limit, 20)
        args.sspai_limit = max(args.sspai_limit, 12)
        args.hn_limit = min(args.hn_limit, 15)
        args.ph_limit = min(args.ph_limit, 10)
        args.min_score = min(args.min_score, 55)
        args.enable_mvp_generation = True
        from screening import constants as sc
        sc.PHASE2_KEEP_MIN_SCORE = 78
        sc.PHASE2_WATCH_MIN_SCORE = 68

    if args.test:
        logger.info("Test mode: fetching sample data...")
        items = collect_data(
            hn_limit=5, ph_limit=3, media_hours=args.media_hours,
            reddit_limit=min(4, args.reddit_limit),
            github_limit=min(4, args.github_limit),
            enable_agent_reach=args.enable_agent_reach, ar_limit=min(5, args.ar_limit),
            enable_app_store_reviews=not args.disable_app_store_reviews,
            app_store_review_limit=min(4, args.app_store_review_limit),
            enable_github_pain_issues=not args.disable_github_pain_issues,
            github_pain_limit=min(4, args.github_pain_limit),
            reddit_pain_limit=min(4, args.reddit_pain_limit),
            enable_saas_reviews=not args.disable_saas_reviews,
            saas_review_limit=min(4, args.saas_review_limit),
            v2ex_limit=min(4, args.v2ex_limit),
            zhihu_limit=min(4, args.zhihu_limit),
            sspai_limit=min(3, args.sspai_limit),
        )
        print(f"Collected {len(items)} items")
        for item in items[:3]:
            print(f"  - {item['title']}")
        return

    # --- Config validation (only needed for normal run with LLM) ---
    try:
        validate_config()
    except ValueError as e:
        print(f"配置错误：{e}")
        sys.exit(1)

    if not BAILIAN_API_KEY:
        logger.error("BAILIAN_API_KEY not configured.")
        print("错误：请配置 BAILIAN_API_KEY")
        sys.exit(1)

    # --- Normal run ---
    items = collect_data(
        hn_limit=args.hn_limit, ph_limit=args.ph_limit, media_hours=args.media_hours,
        reddit_limit=args.reddit_limit, github_limit=args.github_limit,
        enable_agent_reach=args.enable_agent_reach, ar_limit=args.ar_limit,
        enable_app_store_reviews=not args.disable_app_store_reviews,
        app_store_review_limit=args.app_store_review_limit,
        enable_github_pain_issues=not args.disable_github_pain_issues,
        github_pain_limit=args.github_pain_limit,
        reddit_pain_limit=args.reddit_pain_limit,
        enable_saas_reviews=not args.disable_saas_reviews,
        saas_review_limit=args.saas_review_limit,
        v2ex_limit=args.v2ex_limit,
        zhihu_limit=args.zhihu_limit,
        sspai_limit=args.sspai_limit,
    )
    opportunities = asyncio.run(analyze_items_async(items, min_score=args.min_score))

    if opportunities:
        opportunities = deduplicate_opportunities(opportunities)
        opportunities = deduplicate_across_days(opportunities, days=14)

        if not opportunities:
            print("本次机会均与近14天重复，已全部过滤")
            _finalize_top0_run("本次命中的机会与近 14 天重复，未产生新的 Top1/Watchlist。")
            return

        _cross_source_correlation(opportunities)
        _apply_feedback_boosts(opportunities)
        assessments = _annotate_phase2_assessments(opportunities)
        opportunities = rerank_for_solo(opportunities, assessments)
        kept, watch, dropped = _bucket_phase2_candidates(opportunities, assessments)
        rule_adj = _daily_rule_adjustment(opportunities, assessments)

        save_results(opportunities)
        save_phase1_report(opportunities, assessments)
        feishu_doc_url = sync_report_to_feishu()
        print_phase1_results(kept, watch, dropped, len(opportunities), assessments, rule_adjustment=rule_adj)

        if feishu_doc_url:
            print(f"Verified Feishu doc URL: {feishu_doc_url}")
        if kept:
            send_to_feishu(kept)
        else:
            print("No kept candidate to send via direct Feishu message")

        if args.enable_github_issues:
            create_github_issues(kept)
        else:
            print("GitHub issue creation disabled; use --enable-github-issues to override")

        if args.enable_mvp_generation:
            generate_mvps(kept)
        else:
            print("MVP generation disabled; use --enable-mvp-generation to override")
    else:
        print("未发现符合条件的机会")
        _finalize_top0_run("本次采集或分析未产出可排序候选。")


if __name__ == "__main__":
    main()
