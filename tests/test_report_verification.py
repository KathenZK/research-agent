#!/usr/bin/env python3

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from subprocess import CompletedProcess
from unittest.mock import patch

import main
from main import _build_phase2_assessment
from models.opportunity import Opportunity


def _watch_opportunity(opp_id: str) -> Opportunity:
    return Opportunity(
        id=opp_id,
        title=f"AI playbook setup for engineering teams {opp_id}",
        source="hn",
        url=f"https://example.com/{opp_id}",
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


class ReportVerificationTests(unittest.TestCase):
    def test_finalize_top0_run_writes_report_and_console_summary(self):
        reason = "本次命中的机会与近 14 天重复，未产生新的 Top1/Watchlist。"
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(main, "DATA_DIR", tmpdir), patch.object(
            main, "sync_report_to_feishu", return_value=None
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                main._finalize_top0_run(reason)

            latest_report = os.path.join(tmpdir, "latest_phase1.md")
            self.assertTrue(os.path.exists(latest_report))

            with open(latest_report, "r", encoding="utf-8") as fh:
                report = fh.read()
            self.assertIn("- 结论: 今日没有值得立刻开工的切口", report)
            self.assertIn("## Run Notes", report)
            self.assertIn("## No Bet Today", report)
            self.assertIn(reason, report)

            console = stdout.getvalue()
            self.assertIn("No Bet Today | 今天没有值得立刻开工的切口", console)
            self.assertIn("No kept candidate to send via direct Feishu message", console)

    def test_save_phase1_report_keeps_watchlist_in_top0_report(self):
        opportunities = [_watch_opportunity("watch-1"), _drop_opportunity("drop-1")]
        assessments = {opp.id: _build_phase2_assessment(opp) for opp in opportunities}

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(main, "DATA_DIR", tmpdir):
            with redirect_stdout(io.StringIO()):
                main.save_phase1_report(opportunities, assessments)

            latest_report = os.path.join(tmpdir, "latest_phase1.md")
            self.assertTrue(os.path.exists(latest_report))

            with open(latest_report, "r", encoding="utf-8") as fh:
                report = fh.read()
            self.assertIn("- 结论: 今日没有值得立刻开工的切口", report)
            self.assertIn("## Keep Warm", report)
            self.assertIn("AI playbook setup for engineering teams watch-1", report)
            self.assertIn("## Pass For Now", report)
            self.assertIn("Planning - $10K MRR project management tool drop-1", report)

    def test_sync_report_to_feishu_redacts_subprocess_failure_output(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(main, "DATA_DIR", tmpdir), patch.object(
            main, "FEISHU_DOC_SYNC_ENABLED", True
        ), patch.object(main, "_resolve_feishu_credentials", return_value=("cli_secret", "top_secret")), patch.object(
            main, "_resolve_feishu_runtime", return_value=("/opt/homebrew/bin/node", "/tmp/openclaw/node_modules", None)
        ), patch.object(
            main.subprocess,
            "run",
            return_value=CompletedProcess(
                args=["node", "fake.js"],
                returncode=1,
                stdout='{"app_id":"cli_secret","app_secret":"top_secret"} and top_secret',
                stderr="",
            ),
        ):
            latest_report = os.path.join(tmpdir, "latest_phase1.md")
            with open(latest_report, "w", encoding="utf-8") as fh:
                fh.write("# test")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main.sync_report_to_feishu()

            self.assertIsNone(result)
            console = stdout.getvalue()
            self.assertIn("Feishu doc sync failed:", console)
            self.assertIn("***", console)
            self.assertNotIn("cli_secret", console)
            self.assertNotIn("top_secret", console)


if __name__ == "__main__":
    unittest.main()
