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
import argparse
from datetime import datetime
from typing import List

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DEBUG, DATA_DIR, LOG_DIR, BAILIAN_API_KEY, FEISHU_USER_ID, validate_config
from collectors import HNCollector, PHCollector
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


def collect_data(hn_limit: int = 30, ph_limit: int = 20) -> List[dict]:
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
    
    return items


def analyze_items(items: List[dict], min_score: int = 60) -> List[Opportunity]:
    """分析项目"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not BAILIAN_API_KEY:
        logger.error("BAILIAN_API_KEY not configured")
        return []
    
    analyzer = BailianAnalyzer()
    
    logger.info(f"Analyzing {len(items)} items (min_score={min_score})...")
    opportunities = analyzer.batch_analyze(items, min_score=min_score)
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
    """发送到飞书"""
    if not FEISHU_USER_ID:
        print("FEISHU_USER_ID not configured, skipping Feishu notification")
        return
    
    try:
        # 使用 OpenClaw message 工具发送
        # 这里简化处理，实际应该调用 OpenClaw API
        print(f"Would send {len(opportunities)} opportunities to Feishu user {FEISHU_USER_ID}")
        
        # TODO: 集成 OpenClaw message API
        # from openclaw import message
        # for opp in opportunities[:3]:  # 只发送 top 3
        #     message.send(
        #         channel="feishu",
        #         target=FEISHU_USER_ID,
        #         message=opp.to_message()
        #     )
        
    except Exception as e:
        print(f"Error sending to Feishu: {e}")


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
        print(f"   {opp.description[:200]}...")
        print()
        print(f"   💰 盈利模式")
        print(f"   {opp.business_model[:150] if opp.business_model else '待分析'}...")
        print()
        print(f"   🏆 竞争对手")
        print(f"   {opp.competitors[:150] if opp.competitors else '待分析'}...")
        print()
        print(f"   💡 建议方向")
        print(f"   {opp.suggestion[:150]}...")
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
    opportunities = analyze_items(items, min_score=args.min_score)
    
    if opportunities:
        save_results(opportunities)
        print_results(opportunities)
        send_to_feishu(opportunities)
    else:
        print("未发现符合条件的机会")


if __name__ == "__main__":
    main()
