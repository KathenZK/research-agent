#!/usr/bin/env python3

import os
import tempfile
import unittest

from mvp_generator import MVPGenerator


class MVPGeneratorTests(unittest.TestCase):
    def test_generates_landing_page_and_readme(self):
        generator = MVPGenerator(output_dir=tempfile.mkdtemp())
        try:
            opportunity = {
                'title': 'Refund abuse audit for Shopify merchants',
                'description': 'Help Shopify merchants identify refund abuse weekly.',
                'summary': 'Weekly refund abuse audit reports.',
                'revenue_model': 'One-time + monthly',
                'startup_cost': '$1-5k',
                'phase2_target_user': 'Shopify merchants with $5-50k monthly GMV',
                'phase2_deliverable': 'Weekly refund abuse audit report',
                'phase2_why_existing_bad': 'Shopify native tools only flag after the fact.',
                'action_plan': 'Manually audit 20 merchants, deliver report.',
            }

            project_dir = generator.generate(opportunity)

            self.assertTrue(os.path.exists(os.path.join(project_dir, 'index.html')))
            self.assertTrue(os.path.exists(os.path.join(project_dir, 'README.md')))

            with open(os.path.join(project_dir, 'index.html'), 'r', encoding='utf-8') as fh:
                html = fh.read()
            self.assertIn('Refund abuse audit for Shopify merchants', html)
            self.assertIn('tailwindcss', html)
            self.assertIn('formspree', html.lower())
            self.assertIn('Join Waitlist', html)
            self.assertNotIn('pytest', html)
            self.assertNotIn('/100', html)

            with open(os.path.join(project_dir, 'README.md'), 'r', encoding='utf-8') as fh:
                readme = fh.read()
            self.assertIn('Landing Page Generator', readme)
            self.assertIn('Validation Plan', readme)
            self.assertIn('Revenue model', readme)
            self.assertNotIn('**Score**', readme)
        finally:
            pass


if __name__ == '__main__':
    unittest.main()
