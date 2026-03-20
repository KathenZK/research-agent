#!/usr/bin/env python3

import os
import tempfile
import unittest
from unittest.mock import patch

from screening.phase2 import (
    _build_phase2_assessment,
    _bucket_phase2_candidates,
    _daily_rule_adjustment,
    _filtered_reason,
    _wedge_statement,
    rerank_for_solo,
)
from integrations.feishu import _sanitize_secret_text
from reports.daily_report import save_phase1_report, save_top10_report
from models.opportunity import Opportunity


class Phase2ScreeningTests(unittest.TestCase):
    def _make_keep_watch_drop_triplet(self):
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
        return keep, watch, drop

    def test_red_ocean_project_management_is_dropped(self):
        _, _, drop = self._make_keep_watch_drop_triplet()
        assessment = _build_phase2_assessment(drop)

        self.assertEqual(assessment.verdict, "drop")
        self.assertLess(assessment.adjusted_score, 60)
        self.assertIn("主战场", _filtered_reason(drop, assessment))

    def test_narrow_direct_demand_case_can_still_be_kept(self):
        keep, _, _ = self._make_keep_watch_drop_triplet()
        keep.action_plan = "先做一版每周退款滥用审计报告，外联 20 家近期讨论退款问题的 Shopify 商家，收取首批试点审计费。"

        assessment = _build_phase2_assessment(keep)

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

        self.assertEqual(assessment.verdict, "drop")
        self.assertIn("首批用户来源", " ".join(assessment.keep_gaps))
        self.assertIn("模板话", " ".join(assessment.keep_gaps))
        self.assertIn("首客名单和首单动作都还是模板话", " ".join(assessment.kill_reasons))

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

    def test_wedge_statement_prefers_extracted_refund_wedge_over_loose_profile_match(self):
        keep, _, _ = self._make_keep_watch_drop_triplet()
        keep.id = "refund-2"
        keep.url = "https://example.com/refunds-2"
        keep.summary = "先卖人工兜底的退款审计服务。"
        keep.action_plan = "先做一版每周退款滥用审计报告，外联 20 家近期讨论退款问题的 Shopify 商家，收取首批试点审计费。"

        assessment = _build_phase2_assessment(keep)
        wedge = _wedge_statement(keep, assessment)

        self.assertEqual(assessment.verdict, "keep")
        self.assertIn("退款滥用审计报告", wedge)
        self.assertIn("退款争议", wedge)
        self.assertNotIn("Stripe", wedge)

    def test_rerank_and_bucket_are_verdict_first(self):
        keep, watch, drop = self._make_keep_watch_drop_triplet()
        opportunities = [drop, watch, keep]
        assessments = {opp.id: _build_phase2_assessment(opp) for opp in opportunities}

        ranked = rerank_for_solo(opportunities, assessments)
        kept, watchlist, dropped = _bucket_phase2_candidates(ranked, assessments)

        self.assertEqual(ranked[0].id, "keep-1")
        self.assertEqual(kept[0].id, "keep-1")
        self.assertEqual(watchlist[0].id, "watch-1")
        self.assertEqual(dropped[0].id, "drop-1")

    def test_weak_story_signal_defaults_to_drop_instead_of_watch(self):
        opp = Opportunity(
            id="weak-1",
            title="AI founder newsletter from launch stories",
            source="indiehackers",
            url="https://example.com/newsletter",
            score=92,
            description="整理 AI founder launch story 与 best practice，做成 newsletter 和内容站。",
            summary="成功案例很多，热度高。",
            startup_cost="$1-5k",
            time_to_revenue="30天",
            revenue_model="订阅",
            monthly_potential="$10-50k",
            automation_rate="90%+",
            customer_acquisition="SEO and social media",
            risks="内容竞争激烈。",
            action_plan="先做 MVP，根据反馈迭代。",
            tags=["内容", "培训"],
        )

        assessment = _build_phase2_assessment(opp)

        self.assertEqual(assessment.verdict, "drop")
        self.assertLess(assessment.evidence_score, 4)
        self.assertIn("案例热度", " ".join(assessment.kill_reasons))

    def test_feishu_error_sanitization_masks_secrets(self):
        raw = '{"app_id":"cli_secret","app_secret":"top_secret"} and top_secret'
        sanitized = _sanitize_secret_text(raw, ["cli_secret", "top_secret"])

        self.assertNotIn("cli_secret", sanitized)
        self.assertNotIn("top_secret", sanitized)
        self.assertIn("***", sanitized)

    def test_phase1_report_uses_decision_support_wording_without_numeric_scores(self):
        keep, watch, drop = self._make_keep_watch_drop_triplet()
        opportunities = [keep, watch, drop]
        assessments = {opp.id: _build_phase2_assessment(opp) for opp in opportunities}

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("reports.daily_report.DATA_DIR", tmpdir), patch("reports.daily_report._agent_reach_health_summary_lines", return_value=[]):
                save_phase1_report(opportunities, assessments)

            with open(os.path.join(tmpdir, "latest_phase1.md"), "r", encoding="utf-8") as f:
                report = f.read()

        self.assertIn("## 今日唯一候选", report)
        self.assertIn("- 切口名称:", report)
        self.assertIn("- 目标用户:", report)
        self.assertIn("- 高频场景:", report)
        self.assertIn("- 当前替代方案:", report)
        self.assertIn("- 为什么现有方案不好:", report)
        self.assertIn("- 为什么现在值得做:", report)
        self.assertIn("- 为什么适合用户:", report)
        self.assertIn("- 6 周最小收费版本:", report)
        self.assertIn("- 首批 20 用户从哪里来:", report)
        self.assertIn("- 验证动作（landing page / 7 day MVP / 丢弃）:", report)
        self.assertIn("- 不该做大的边界:", report)
        self.assertIn("- 最终结论:", report)
        self.assertIn("## 继续观察", report)
        self.assertIn("## 今天不值得做", report)
        self.assertIn("- 机会信号:", report)
        self.assertIn("- 证据摘要:", report)
        self.assertIn("做 7 天 MVP 验证", report)
        self.assertIn("做 landing page 验证", report)
        self.assertIn("丢弃", report)
        self.assertNotIn("/100", report)
        self.assertNotIn("筛选分", report)
        self.assertNotIn("## Recommended Bet", report)
        self.assertNotIn("## Keep Warm", report)
        self.assertNotIn("## Pass For Now", report)

    def test_top0_report_uses_drop_wording(self):
        _, _, drop = self._make_keep_watch_drop_triplet()
        assessments = {drop.id: _build_phase2_assessment(drop)}

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("reports.daily_report.DATA_DIR", tmpdir), patch("reports.daily_report._agent_reach_health_summary_lines", return_value=[]):
                save_phase1_report([drop], assessments, run_notes=["dedupe run"])

            with open(os.path.join(tmpdir, "latest_phase1.md"), "r", encoding="utf-8") as f:
                report = f.read()

        self.assertIn("## 今日唯一候选", report)
        self.assertNotIn("## Top0", report)
        self.assertIn("**丢弃**", report)
        self.assertIn("今天没有出现值得继续验证的唯一候选。", report)

    def test_top10_report_uses_signal_labels_instead_of_scores(self):
        keep, _, _ = self._make_keep_watch_drop_triplet()
        keep.phase2_adjusted_score = _build_phase2_assessment(keep).adjusted_score
        keep.phase2_decision_label = "做 7 天 MVP 验证"
        keep.phase2_target_user = "月销 5-50 万美元的 Shopify 商家运营负责人"
        keep.phase2_trigger_event = "出现退款争议、退款滥用或高风险订单时"
        keep.phase2_paid_mvp = "先卖每周一次的退款滥用审计报告试点。"
        keep.phase2_final_conclusion = "做 7 天 MVP 验证。先把退款滥用审计报告卖给近期正在处理退款争议的商家。"

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("reports.daily_report.DATA_DIR", tmpdir):
                save_top10_report([keep])

            with open(os.path.join(tmpdir, "latest_top10.md"), "r", encoding="utf-8") as f:
                report = f.read()

        self.assertIn("- 机会信号:", report)
        self.assertIn("- 验证动作（landing page / 7 day MVP / 丢弃）:", report)
        self.assertNotIn("/100", report)

    def test_daily_rule_adjustment_prefers_generic_acquisition_hardening_when_repeated(self):
        opps = []
        for idx in range(3):
            opps.append(
                Opportunity(
                    id=f"acq-{idx}",
                    title=f"Ops copilot {idx}",
                    source="reddit_r/entrepreneur",
                    url=f"https://example.com/acq-{idx}",
                    score=82,
                    description="帮助小型 SaaS 团队更快处理客服工单，目标用户为 5-20 人 SaaS 团队创始人。",
                    summary="问题存在，但当前分发证据还比较泛。",
                    startup_cost="$1-5k",
                    time_to_revenue="14天",
                    revenue_model="订阅",
                    monthly_potential="$10-50k",
                    automation_rate="90%+",
                    customer_acquisition="SEO and social media",
                    risks="需求存在，但分发信号仍然很弱。",
                    action_plan="先卖一份工单分流与回复建议清单，拿 10 个客服团队做收费试点。",
                    tags=["SaaS", "B2B", "客服", "AI"],
                )
            )

        assessments = {opp.id: _build_phase2_assessment(opp) for opp in opps}
        suggestion = _daily_rule_adjustment(opps, assessments)

        self.assertIn("首批 20 用户来源仍是 SEO / 社媒 / 泛 cold outreach", suggestion["suggestion"])
        self.assertIn("今天有 3 条样本", suggestion["evidence"])

    def test_irrelevant_ticket_deliverable_does_not_leak_into_non_support_topics(self):
        opp = Opportunity(
            id="netcatty-1",
            title="Netcatty - 开源免费的 SSH 终端软件, 使用 AI 加速你的日常运维工作",
            source="v2ex",
            url="https://www.v2ex.com/t/1199762",
            score=80,
            description="一个面向程序员和运维人员的 SSH 终端工具。",
            summary="用户讨论 AI 加速运维和终端体验。",
            startup_cost="$1-5k",
            time_to_revenue="14天",
            revenue_model="订阅",
            monthly_potential="$10-50k",
            automation_rate="80%",
            customer_acquisition="V2EX 帖子评论区与运维社群外联",
            risks="终端工具竞争激烈。",
            action_plan="先联系帖子评论者，验证他们是否愿意为更好的 SSH 工作流付费。",
            tags=["ssh", "terminal", "ops", "developer tool"],
        )

        assessment = _build_phase2_assessment(opp)
        wedge = _wedge_statement(opp, assessment)

        self.assertNotEqual(assessment.deliverable, "一份工单分流与回复建议清单")
        self.assertNotIn("工单分流与回复建议清单", wedge)


if __name__ == "__main__":
    unittest.main()
