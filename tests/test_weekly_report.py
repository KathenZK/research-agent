#!/usr/bin/env python3

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from unittest.mock import patch

import main
from models.opportunity import Opportunity


def _refund_opportunity(opp_id: str, url_suffix: str) -> Opportunity:
    return Opportunity(
        id=opp_id,
        title=f"Refund abuse audit for Shopify merchants {opp_id}",
        source="reddit_r/shopify",
        url=f"https://example.com/{url_suffix}",
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


def _drop_opportunity(opp_id: str) -> Opportunity:
    return Opportunity(
        id=opp_id,
        title=f"Planning - $10K MRR project management tool {opp_id}",
        source="indiehackers",
        url=f"https://example.com/{opp_id}",
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


class WeeklyReportTests(unittest.TestCase):
    def _write_snapshot(self, tmpdir: str, stamp: str, opportunities: list[Opportunity]) -> None:
        path = os.path.join(tmpdir, f"opportunities_{stamp}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([opp.to_dict() for opp in opportunities], fh, ensure_ascii=False, indent=2)

    def test_weekly_report_summarizes_repeated_patterns_and_unique_direction(self):
        now = datetime(2026, 3, 17, 10, 0, 0)
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(main, "DATA_DIR", tmpdir):
            self._write_snapshot(
                tmpdir,
                "20260312_080000",
                [_refund_opportunity("refund-1", "refund-1"), _drop_opportunity("drop-1")],
            )
            self._write_snapshot(
                tmpdir,
                "20260314_080000",
                [_refund_opportunity("refund-2", "refund-2"), _drop_opportunity("drop-2")],
            )
            self._write_snapshot(
                tmpdir,
                "20260316_080000",
                [_refund_opportunity("refund-3", "refund-3"), _drop_opportunity("drop-3")],
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                main.save_weekly_report(window_days=7, now=now)

            latest_report = os.path.join(tmpdir, "latest_weekly.md")
            self.assertTrue(os.path.exists(latest_report))
            with open(latest_report, "r", encoding="utf-8") as fh:
                report = fh.read()

        self.assertIn("# 深筛周报", report)
        self.assertIn("## 反复出现的痛点", report)
        self.assertIn("## 重复出现的切口", report)
        self.assertIn("## 最常见伪机会类型", report)
        self.assertIn("## 本周唯一值得认真验证的方向", report)
        self.assertIn("出现退款争议、退款滥用或高风险订单时", report)
        self.assertIn("退款滥用审计报告", report)
        self.assertIn("项目管理型机会", report)
        self.assertIn("Shopify 商家运营负责人", report)
        self.assertIn("Weekly report saved:", stdout.getvalue())

    def test_weekly_report_handles_empty_history(self):
        now = datetime(2026, 3, 17, 10, 0, 0)
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(main, "DATA_DIR", tmpdir):
            with redirect_stdout(io.StringIO()):
                main.save_weekly_report(window_days=7, now=now)

            with open(os.path.join(tmpdir, "latest_weekly.md"), "r", encoding="utf-8") as fh:
                report = fh.read()

        self.assertIn("当前窗口内没有可用历史快照", report)
        self.assertIn("先继续积累 3-7 天快照", report)

    def test_weekly_report_does_not_force_direction_when_all_history_is_drop(self):
        now = datetime(2026, 3, 17, 10, 0, 0)
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(main, "DATA_DIR", tmpdir):
            self._write_snapshot(tmpdir, "20260316_080000", [_drop_opportunity("drop-1"), _drop_opportunity("drop-2")])

            with redirect_stdout(io.StringIO()):
                main.save_weekly_report(window_days=7, now=now)

            with open(os.path.join(tmpdir, "latest_weekly.md"), "r", encoding="utf-8") as fh:
                report = fh.read()

        self.assertIn("keep 0 / watch 0", report)
        self.assertIn("本周没有形成可复用的痛点聚类", report)
        self.assertIn("本周没有出现重复到值得命名的切口", report)
        self.assertIn("当前窗口里还没有出现一个值得单点加码的方向", report)


if __name__ == "__main__":
    unittest.main()
