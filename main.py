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
from typing import List
import hashlib
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mvp_generator import MVPGenerator
from config import DEBUG, DATA_DIR, LOG_DIR, BAILIAN_API_KEY, FEISHU_USER_ID, validate_config, GITHUB_TOKEN, GITHUB_REPO
from collectors import HNCollector, PHCollector, ChineseMediaCollector, GitHubTrendingCollector
from collectors.indiehackers import IndieHackersCollector
from collectors.reddit import RedditCollector
from analyzers import BailianAnalyzer
from models import Opportunity


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
                 indie_limit: int = 15, reddit_limit: int = 10, github_limit: int = 10) -> List[dict]:
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

    # Reddit (entrepreneur / SaaS)
    logger.info(f"Fetching Reddit (limit={reddit_limit})...")
    reddit_collector = RedditCollector()
    reddit_items = reddit_collector.fetch(limit=reddit_limit)
    logger.info(f"Got {len(reddit_items)} Reddit items")
    items.extend(reddit_items)

    # GitHub Trending
    logger.info(f"Fetching GitHub Trending (limit={github_limit})...")
    gh_collector = GitHubTrendingCollector()
    gh_items = gh_collector.fetch(limit=github_limit)
    logger.info(f"Got {len(gh_items)} GitHub Trending items")
    items.extend(gh_items)

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


def save_top10_report(opportunities: List[Opportunity]):
    """输出 Top10 决策报告（markdown + latest）"""
    if not opportunities:
        return

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = os.path.join(DATA_DIR, f'top10_report_{ts}.md')
    latest_file = os.path.join(DATA_DIR, 'latest_top10.md')

    top = opportunities[:10]
    lines = [
        '# Top 10 一人公司机会日报',
        '',
        f'- 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'- 样本数量: {len(opportunities)}',
        '',
    ]

    for idx, o in enumerate(top, 1):
        lines += [
            f'## {idx}. {o.title}',
            f'- 评分: **{o.score}/100**',
            f'- 来源: `{o.source}`',
            f'- 链接: {o.url}',
            f'- 一人可行性: {o.solo_feasibility or "待分析"}',
            f'- 启动成本: {o.startup_cost or "待分析"}',
            f'- 见钱周期: {o.time_to_revenue or "待分析"}',
            f'- 收入模式: {o.revenue_model or "待分析"}',
            f'- 月潜力: {o.monthly_potential or "待分析"}',
            f'- 第一步: {o.action_plan or "待分析"}',
            '',
        ]

    content = '\n'.join(lines)
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(content)
    with open(latest_file, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f'Report saved: {report_file}')



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
    parser.add_argument('--indie-mode', action='store_true', help='一人公司模式：专注 Indie Hacker/微 SaaS/自动化机会')
    
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
        items = collect_data(hn_limit=5, ph_limit=3, media_hours=args.media_hours, indie_limit=min(5, args.indie_limit), reddit_limit=min(4, args.reddit_limit), github_limit=min(4, args.github_limit))
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

        save_results(opportunities)
        save_top10_report(opportunities)
        print_results(opportunities)
        send_to_feishu(opportunities)
        create_github_issues(opportunities)
        generate_mvps(opportunities)
    else:
        print("未发现符合条件的机会")


if __name__ == "__main__":
    main()
