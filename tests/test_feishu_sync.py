#!/usr/bin/env python3

import io
import os
import tempfile
import unittest
from unittest.mock import patch

import integrations.feishu as feishu_mod


class FeishuSyncTests(unittest.TestCase):
    @patch("integrations.feishu.os.path.realpath", return_value="/opt/homebrew/lib/node_modules/openclaw/openclaw.mjs")
    @patch("integrations.feishu.os.path.exists")
    @patch("integrations.feishu.shutil.which")
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

        node_bin, node_path, error = feishu_mod._resolve_feishu_runtime()

        self.assertEqual(node_bin, "/opt/homebrew/bin/node")
        self.assertEqual(node_path, "/opt/homebrew/lib/node_modules/openclaw/node_modules")
        self.assertIsNone(error)

    @patch("integrations.feishu.subprocess.run")
    @patch("integrations.feishu._resolve_feishu_runtime", return_value=(None, None, "node runtime not found"))
    @patch("integrations.feishu._resolve_feishu_credentials", return_value=("cli_valid", "secret_valid"))
    def test_sync_report_to_feishu_skips_cleanly_when_runtime_missing(self, _mock_creds, _mock_runtime, mock_run):
        old_enabled = feishu_mod.FEISHU_DOC_SYNC_ENABLED
        old_data_dir = feishu_mod.DATA_DIR
        try:
            feishu_mod.FEISHU_DOC_SYNC_ENABLED = True
            with tempfile.TemporaryDirectory() as temp_dir:
                feishu_mod.DATA_DIR = temp_dir
                with open(os.path.join(temp_dir, "latest_phase1.md"), "w", encoding="utf-8") as f:
                    f.write("# test report\n")

                with patch("sys.stdout", new=io.StringIO()) as stdout:
                    result = feishu_mod.sync_report_to_feishu()

                self.assertIsNone(result)
                self.assertIn("Feishu doc sync blocked: node runtime not found", stdout.getvalue())
                mock_run.assert_not_called()
        finally:
            feishu_mod.FEISHU_DOC_SYNC_ENABLED = old_enabled
            feishu_mod.DATA_DIR = old_data_dir

    @patch("integrations.feishu.subprocess.run")
    @patch("integrations.feishu._resolve_feishu_runtime", return_value=("/opt/homebrew/bin/node", "/tmp/openclaw/node_modules", None))
    @patch("integrations.feishu._resolve_feishu_credentials", return_value=("cli_valid", "secret_valid"))
    def test_sync_report_to_feishu_reports_network_blocker(self, _mock_creds, _mock_runtime, mock_run):
        old_enabled = feishu_mod.FEISHU_DOC_SYNC_ENABLED
        old_data_dir = feishu_mod.DATA_DIR
        try:
            feishu_mod.FEISHU_DOC_SYNC_ENABLED = True
            with tempfile.TemporaryDirectory() as temp_dir:
                feishu_mod.DATA_DIR = temp_dir
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
                    result = feishu_mod.sync_report_to_feishu()

                self.assertIsNone(result)
                self.assertIn(
                    "Feishu doc sync blocked: outbound DNS/network access to open.feishu.cn is unavailable in the current environment",
                    stdout.getvalue(),
                )
        finally:
            feishu_mod.FEISHU_DOC_SYNC_ENABLED = old_enabled
            feishu_mod.DATA_DIR = old_data_dir


if __name__ == "__main__":
    unittest.main()
