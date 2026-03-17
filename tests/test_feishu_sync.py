#!/usr/bin/env python3

import io
import os
import tempfile
import unittest
from unittest.mock import patch

import main


class FeishuSyncTests(unittest.TestCase):
    @patch("main.os.path.realpath", return_value="/opt/homebrew/lib/node_modules/openclaw/openclaw.mjs")
    @patch("main.os.path.exists")
    @patch("main.shutil.which")
    def test_resolve_feishu_runtime_uses_openclaw_node_modules(self, mock_which, mock_exists, _mock_realpath):
        mock_which.side_effect = lambda name: {
            "node": "/opt/homebrew/bin/node",
            "openclaw": "/opt/homebrew/bin/openclaw",
        }.get(name)

        def exists_side_effect(path):
            return path in {
                "/opt/homebrew/bin/node",
                "/opt/homebrew/lib/node_modules/openclaw/node_modules/@larksuiteoapi/node-sdk",
            }

        mock_exists.side_effect = exists_side_effect

        node_bin, node_path, error = main._resolve_feishu_runtime()

        self.assertEqual(node_bin, "/opt/homebrew/bin/node")
        self.assertEqual(node_path, "/opt/homebrew/lib/node_modules/openclaw/node_modules")
        self.assertIsNone(error)

    @patch("main.subprocess.run")
    @patch("main._resolve_feishu_runtime", return_value=(None, None, "node runtime not found"))
    @patch("main._resolve_feishu_credentials", return_value=("cli_valid", "secret_valid"))
    def test_sync_report_to_feishu_skips_cleanly_when_runtime_missing(self, _mock_creds, _mock_runtime, mock_run):
        old_enabled = main.FEISHU_DOC_SYNC_ENABLED
        old_data_dir = main.DATA_DIR
        try:
            main.FEISHU_DOC_SYNC_ENABLED = True
            with tempfile.TemporaryDirectory() as temp_dir:
                main.DATA_DIR = temp_dir
                with open(os.path.join(temp_dir, "latest_phase1.md"), "w", encoding="utf-8") as f:
                    f.write("# test report\n")

                with patch("sys.stdout", new=io.StringIO()) as stdout:
                    result = main.sync_report_to_feishu()

                self.assertIsNone(result)
                self.assertIn("Feishu doc sync blocked: node runtime not found", stdout.getvalue())
                mock_run.assert_not_called()
        finally:
            main.FEISHU_DOC_SYNC_ENABLED = old_enabled
            main.DATA_DIR = old_data_dir

    @patch("main.subprocess.run")
    @patch("main._resolve_feishu_runtime", return_value=("/opt/homebrew/bin/node", "/tmp/openclaw/node_modules", None))
    @patch("main._resolve_feishu_credentials", return_value=("cli_valid", "secret_valid"))
    def test_sync_report_to_feishu_reports_network_blocker(self, _mock_creds, _mock_runtime, mock_run):
        old_enabled = main.FEISHU_DOC_SYNC_ENABLED
        old_data_dir = main.DATA_DIR
        try:
            main.FEISHU_DOC_SYNC_ENABLED = True
            with tempfile.TemporaryDirectory() as temp_dir:
                main.DATA_DIR = temp_dir
                with open(os.path.join(temp_dir, "latest_phase1.md"), "w", encoding="utf-8") as f:
                    f.write("# test report\n")

                mock_run.return_value.stdout = """
[error]: [
  AxiosError: getaddrinfo ENOTFOUND open.feishu.cn
]
{"created":false,"write_ok":false,"index_update_ok":false,"doc_url":"","title":"x","error":"Cannot destructure property 'tenant_access_token' of '(intermediate value)' as it is undefined.","warning":""}
"""
                mock_run.return_value.stderr = ""
                mock_run.return_value.returncode = 1

                with patch("sys.stdout", new=io.StringIO()) as stdout:
                    result = main.sync_report_to_feishu()

                self.assertIsNone(result)
                self.assertIn(
                    "Feishu doc sync blocked: outbound DNS/network access to open.feishu.cn is unavailable in the current environment",
                    stdout.getvalue(),
                )
        finally:
            main.FEISHU_DOC_SYNC_ENABLED = old_enabled
            main.DATA_DIR = old_data_dir


if __name__ == "__main__":
    unittest.main()
