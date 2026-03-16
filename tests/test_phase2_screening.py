#!/usr/bin/env python3

import unittest

from main import (
    _build_phase2_assessment,
    _bucket_phase2_candidates,
    _filtered_reason,
    _sanitize_secret_text,
    _wedge_statement,
    rerank_for_solo,
)
from models.opportunity import Opportunity


class Phase2ScreeningTests(unittest.TestCase):
    def test_red_ocean_project_management_is_dropped(self):
        opp = Opportunity(
            id="pm-1",
            title="Planning - $10K MRR project management tool",
            source="indiehackers",
            url="https://example.com/planning",
            score=78,
            description="开发面向独立开发者和小团队的项目管理工具，解决任务跟踪、进度管理和团队协作痛点。",
            summary="项目管理工具市场成熟，已有成功案例证明可行性。",
            startup_cost="$1-5k",
            time_to_revenue="30天",
            revenue_model="订阅",
            monthly_potential="$10-50k",
            automation_rate="90%+",
            customer_acquisition="SEO",
            risks="市场竞争激烈，Linear、Jira、Notion 已经占据主战场，用户获取成本高。",
            tags=["SaaS", "B2B", "项目管理", "自动化"],
        )

        assessment = _build_phase2_assessment(opp)

        self.assertEqual(assessment.verdict, "drop")
        self.assertLess(assessment.adjusted_score, 60)
        self.assertIn("主战场", _filtered_reason(opp, assessment))

    def test_narrow_direct_demand_case_can_still_be_kept(self):
        opp = Opportunity(
            id="ops-1",
            title="Refund abuse audit for Shopify merchants",
            source="reddit_r/shopify",
            url="https://example.com/refunds",
            score=90,
            description="帮助 Shopify 商家每周识别退款滥用和高风险订单，目标用户为月销 5-50 万美元的 Shopify 商家运营负责人。",
            summary="直接解决高频退款损失问题，适合先卖一项人工兜底的审计服务。",
            startup_cost="$1-5k",
            time_to_revenue="14天",
            revenue_model="一次性",
            monthly_potential="$10-50k",
            automation_rate="90%+",
            customer_acquisition="从 Shopify 退款求助帖、DTC 创始人社群和支付风控讨论串里外联首批 20 家商家",
            risks="误报会影响商家信任，需要把交付边界收窄在审计建议而非自动封禁。",
            action_plan="先做一版每周退款滥用审计报告，外联 20 家近期讨论退款问题的 Shopify 商家，收取首批试点审计费。",
            tags=["SaaS", "B2B", "电商", "风控"],
        )

        assessment = _build_phase2_assessment(opp)

        self.assertEqual(assessment.verdict, "keep")
        self.assertGreaterEqual(assessment.adjusted_score, 83)

    def test_generic_acquisition_and_mvp_template_do_not_pass_keep_bar(self):
        opp = Opportunity(
            id="ops-2",
            title="Customer support copilot for SMB SaaS",
            source="reddit_r/entrepreneur",
            url="https://example.com/copilot",
            score=88,
            description="帮助小型 SaaS 团队更快处理客服工单，目标用户为 5-20 人 SaaS 团队创始人。",
            summary="问题存在，但当前分发与首单动作还比较泛。",
            startup_cost="$1-5k",
            time_to_revenue="14天",
            revenue_model="订阅",
            monthly_potential="$10-50k",
            automation_rate="90%+",
            customer_acquisition="Cold outreach and partnerships",
            risks="Zendesk 等客服平台可能补功能。",
            action_plan="先做 MVP，根据反馈迭代。",
            tags=["SaaS", "B2B", "客服", "AI"],
        )

        assessment = _build_phase2_assessment(opp)

        self.assertNotEqual(assessment.verdict, "keep")
        self.assertIn("首批用户来源", " ".join(assessment.keep_gaps))
        self.assertIn("模板话", " ".join(assessment.keep_gaps))

    def test_wedge_statement_is_specific_for_billing_analytics(self):
        opp = Opportunity(
            id="billing-1",
            title="Baremetrics - $15K MRR from Stripe analytics",
            source="indiehackers",
            url="https://example.com/baremetrics",
            score=82,
            description="提供 Stripe 支付数据的深度分析和可视化服务，帮助 SaaS 企业理解收入趋势、客户行为和财务指标。目标用户为使用 Stripe 的 B2B 公司创始人和财务负责人。",
            summary="Stripe 数据分析需求明确，但官方能力和同类产品竞争都很强。",
            startup_cost="$1-5k",
            time_to_revenue="30天",
            revenue_model="订阅",
            monthly_potential="$10-50k",
            automation_rate="90%+",
            customer_acquisition="SEO",
            risks="Stripe 可能推出官方分析工具形成竞争，API 变更影响产品稳定性。",
            tags=["SaaS", "B2B", "Stripe", "数据分析"],
        )

        assessment = _build_phase2_assessment(opp)
        wedge = _wedge_statement(opp, assessment)

        self.assertIn("Stripe", wedge)
        self.assertIn("failed payment", wedge)
        self.assertNotIn("围绕", wedge)

    def test_rerank_and_bucket_are_verdict_first(self):
        keep = Opportunity(
            id="keep-1",
            title="Refund abuse audit for Shopify merchants",
            source="reddit_r/shopify",
            url="https://example.com/refunds",
            score=90,
            description="帮助 Shopify 商家每周识别退款滥用和高风险订单，目标用户为月销 5-50 万美元的 Shopify 商家运营负责人。",
            summary="直接解决高频退款损失问题，适合先卖一项人工兜底的审计服务。",
            startup_cost="$1-5k",
            time_to_revenue="14天",
            revenue_model="一次性",
            monthly_potential="$10-50k",
            automation_rate="90%+",
            customer_acquisition="从 Shopify 退款求助帖、DTC 创始人社群和支付风控讨论串里外联首批 20 家商家",
            risks="误报会影响商家信任，需要把交付边界收窄在审计建议而非自动封禁。",
            action_plan="外联 20 家近期出现退款争议的 Shopify 商家，先卖每周一次的退款滥用审计报告。",
            tags=["SaaS", "B2B", "电商", "风控"],
        )
        watch = Opportunity(
            id="watch-1",
            title="AI playbook setup for engineering teams",
            source="hn",
            url="https://example.com/playbook",
            score=86,
            description="帮助工程团队把 AI 编程规范落进真实代码库，目标用户为 10 人左右工程团队负责人。",
            summary="需求方向明确，但还要验证团队是否愿意快速付费。",
            startup_cost="$1-5k",
            time_to_revenue="30天",
            revenue_model="一次性",
            monthly_potential="$10-50k",
            automation_rate="70%",
            customer_acquisition="去 HN 评论区和工程管理 Slack 社群外联首批 20 个团队负责人",
            risks="如果交付边界放大成长期咨询，会迅速变重。",
            action_plan="先卖一周内交付的 AI 编程评审清单与代码库 playbook 试点。",
            tags=["B2B", "内容", "培训"],
        )
        drop = Opportunity(
            id="drop-1",
            title="Planning - $10K MRR project management tool",
            source="indiehackers",
            url="https://example.com/planning",
            score=93,
            description="开发面向独立开发者和小团队的项目管理工具，解决任务跟踪、进度管理和团队协作痛点。",
            summary="项目管理工具市场成熟，已有成功案例证明可行性。",
            startup_cost="$1-5k",
            time_to_revenue="30天",
            revenue_model="订阅",
            monthly_potential="$10-50k",
            automation_rate="90%+",
            customer_acquisition="SEO",
            risks="市场竞争激烈，Linear、Jira、Notion 已经占据主战场，用户获取成本高。",
            action_plan="先做 MVP，根据反馈迭代。",
            tags=["SaaS", "B2B", "项目管理", "自动化"],
        )

        opportunities = [drop, watch, keep]
        assessments = {opp.id: _build_phase2_assessment(opp) for opp in opportunities}

        ranked = rerank_for_solo(opportunities, assessments)
        kept, watchlist, dropped = _bucket_phase2_candidates(ranked, assessments)

        self.assertEqual(ranked[0].id, "keep-1")
        self.assertEqual(kept[0].id, "keep-1")
        self.assertEqual(watchlist[0].id, "watch-1")
        self.assertEqual(dropped[0].id, "drop-1")

    def test_feishu_error_sanitization_masks_secrets(self):
        raw = '{"app_id":"cli_secret","app_secret":"top_secret"} and top_secret'
        sanitized = _sanitize_secret_text(raw, ["cli_secret", "top_secret"])

        self.assertNotIn("cli_secret", sanitized)
        self.assertNotIn("top_secret", sanitized)
        self.assertIn("***", sanitized)


if __name__ == "__main__":
    unittest.main()
