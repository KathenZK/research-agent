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
from datetime import datetime
from typing import List

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


def collect_data(hn_limit: int = 10, ph_limit: int = 5, twitter_limit: int = 20, 
                 media_hours: int = 48, crunchbase_limit: int = 10) -> List[dict]:
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
    logger.info(f"Fetching IndieHackers (limit=15)...")
    ih_collector = IndieHackersCollector()
    ih_items = ih_collector.fetch(limit=15)
    logger.info(f"Got {len(ih_items)} IndieHackers items")
    items.extend(ih_items)
    
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


def send_to_feishu(opportunities: List[Opportunity]):
    """发送到飞书（通过 OpenClaw CLI）"""
    if not FEISHU_USER_ID:
        print("FEISHU_USER_ID not configured, skipping Feishu notification")
        return
    
    try:
        import subprocess
        
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
            if result.returncode == 0:
                print(f"✅ Sent to Feishu: {opp.title[:50]}...")
            else:
                print(f"⚠️  Send failed: {result.stderr[:100]}")
        
        print(f"✅ Sent Top {min(10, len(opportunities))} opportunities to Feishu")
        
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
        items = collect_data(hn_limit=5, ph_limit=3)
        print(f"Collected {len(items)} items")
        for item in items[:3]:
            print(f"  - {item['title']}")
        return
    
    # 正常运行
    items = collect_data(hn_limit=args.hn_limit, ph_limit=args.ph_limit)
    opportunities = asyncio.run(analyze_items_async(items, min_score=args.min_score))
    
    if opportunities:
        save_results(opportunities)
        print_results(opportunities)
        send_to_feishu(opportunities)
        create_github_issues(opportunities)
        generate_mvps(opportunities)
    else:
        print("未发现符合条件的机会")


if __name__ == "__main__":
    main()
