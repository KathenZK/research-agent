#!/usr/bin/env python3

import os
import tempfile
import unittest

from mvp_generator import MVPGenerator


class MVPGeneratorTests(unittest.TestCase):
    def test_generated_readme_uses_signal_and_validation_action_labels(self):
        generator = MVPGenerator(output_dir=tempfile.mkdtemp())
        try:
            project_dir = tempfile.mkdtemp(dir=generator.output_dir)
            opportunity = {
                'title': 'Refund abuse audit for Shopify merchants',
                'description': '帮助 Shopify 商家每周识别退款滥用和高风险订单。',
                'summary': '先卖退款滥用审计报告。',
                'signal_label': '高',
                'decision_label': '做 7 天 MVP 验证',
            }

            generator._generate_readme(project_dir, opportunity)

            with open(os.path.join(project_dir, 'README.md'), 'r', encoding='utf-8') as fh:
                readme = fh.read()

            self.assertIn('**机会信号**: 高', readme)
            self.assertIn('**验证动作**: 做 7 天 MVP 验证', readme)
            self.assertIn('python3 -m unittest discover -s tests -q', readme)
            self.assertNotIn('pytest', readme)
            self.assertNotIn('**Score**', readme)
            self.assertNotIn('/100', readme)
        finally:
            # tempfile dirs are fine to leave to OS cleanup in tests; base_dir removed best-effort
            pass


if __name__ == '__main__':
    unittest.main()
