#!/usr/bin/env python3
"""Landing Page Generator -- produces a single-file validation page for each opportunity.

Replaces the previous empty-scaffold MVP generator with something that directly
enables the "do landing page validation" action recommended by Phase 2.
"""

import os
import re
import subprocess
from typing import Any, Dict, Optional
from datetime import datetime
from html import escape


class MVPGenerator:
    """Generate a single-file HTML landing page for idea validation."""

    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or os.path.expanduser("~/Code/one-company-lab/mvps")
        os.makedirs(self.output_dir, exist_ok=True)

    def generate(self, opportunity: Dict[str, Any]) -> Optional[str]:
        project_name = self._sanitize_name(opportunity.get('title', 'unknown'))
        project_dir = os.path.join(self.output_dir, project_name)
        os.makedirs(project_dir, exist_ok=True)

        print(f"\nGenerating landing page for: {opportunity.get('title', '')}")
        print(f"   Output: {project_dir}")

        self._generate_landing_page(project_dir, opportunity)
        self._generate_readme(project_dir, opportunity)
        self._commit_to_git(project_dir, opportunity)

        return project_dir

    def _sanitize_name(self, name: str) -> str:
        name = re.sub(r'[^a-zA-Z0-9\s-]', '', name)
        name = re.sub(r'\s+', '-', name)
        return name.lower()[:50]

    def _generate_landing_page(self, project_dir: str, opp: Dict[str, Any]):
        title = escape(opp.get('title', 'New Product'))
        description = escape(opp.get('description', opp.get('summary', '')))
        deliverable = escape(opp.get('phase2_deliverable', '') or opp.get('description', '')[:100])
        target_user = escape(opp.get('phase2_target_user', '') or 'teams struggling with this problem')
        why_bad = escape(opp.get('phase2_why_existing_bad', '') or 'Current solutions are too generic or require too much manual work.')
        action_plan = escape(opp.get('action_plan', '') or opp.get('summary', ''))
        revenue_model = escape(opp.get('revenue_model', 'Subscription'))
        startup_cost = escape(opp.get('startup_cost', '$1-5k'))

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {{ font-family: 'Inter', sans-serif; }}
    </style>
</head>
<body class="bg-white text-gray-900">
    <main class="max-w-2xl mx-auto px-6 py-16">
        <section class="mb-16">
            <p class="text-sm font-medium text-indigo-600 mb-3 uppercase tracking-wide">Early Access</p>
            <h1 class="text-4xl font-bold leading-tight mb-6">{title}</h1>
            <p class="text-xl text-gray-600 leading-relaxed mb-8">{description}</p>
        </section>

        <section class="mb-16 bg-gray-50 rounded-2xl p-8">
            <h2 class="text-lg font-semibold mb-4">The Problem</h2>
            <p class="text-gray-700 leading-relaxed mb-4">For <strong>{target_user}</strong>:</p>
            <p class="text-gray-600 leading-relaxed">{why_bad}</p>
        </section>

        <section class="mb-16">
            <h2 class="text-lg font-semibold mb-4">What We Deliver</h2>
            <p class="text-gray-700 leading-relaxed">{deliverable}</p>
        </section>

        <section class="mb-16 bg-indigo-50 rounded-2xl p-8">
            <h2 class="text-lg font-semibold mb-4">How It Works</h2>
            <p class="text-gray-700 leading-relaxed">{action_plan}</p>
            <div class="mt-4 flex gap-6 text-sm text-gray-500">
                <span>Model: {revenue_model}</span>
                <span>Starting at: {startup_cost}</span>
            </div>
        </section>

        <section class="mb-16" id="signup">
            <h2 class="text-2xl font-bold mb-4">Get Early Access</h2>
            <p class="text-gray-600 mb-6">Leave your email and we'll reach out when the first version is ready.</p>
            <form action="https://formspree.io/f/YOUR_FORM_ID" method="POST" class="flex gap-3">
                <input type="email" name="email" required placeholder="you@company.com"
                    class="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent">
                <button type="submit"
                    class="px-6 py-3 bg-indigo-600 text-white font-medium rounded-lg hover:bg-indigo-700 transition-colors">
                    Join Waitlist
                </button>
            </form>
            <p class="text-xs text-gray-400 mt-3">No spam. We only email when the product is ready.</p>
        </section>

        <footer class="text-center text-sm text-gray-400 pt-8 border-t border-gray-100">
            <p>Generated by Research Agent &middot; {datetime.now().strftime('%Y-%m-%d')}</p>
        </footer>
    </main>
</body>
</html>"""

        with open(os.path.join(project_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"   Generated index.html (landing page)")

    def _generate_readme(self, project_dir: str, opp: Dict[str, Any]):
        readme = f"""# {opp.get('title', 'Landing Page')}

**Generated by**: Research Agent Landing Page Generator
**Date**: {datetime.now().strftime('%Y-%m-%d')}

## Quick Start

1. Replace `YOUR_FORM_ID` in `index.html` with your [Formspree](https://formspree.io) or [Tally](https://tally.so) form ID
2. Open `index.html` in a browser to preview
3. Deploy to any static hosting:
   - **Cloudflare Pages**: `npx wrangler pages deploy .`
   - **Vercel**: `npx vercel --prod`
   - **Netlify**: drag & drop the folder

## Validation Plan

- **Target user**: {opp.get('phase2_target_user', 'TBD')}
- **Revenue model**: {opp.get('revenue_model', 'TBD')}
- **Startup cost**: {opp.get('startup_cost', 'TBD')}
- **First 20 users**: {opp.get('customer_acquisition', 'TBD')}

## Next Steps

1. Deploy this page
2. Share the URL in the communities where your target users hang out
3. Track email signups for 7 days
4. If > 10 signups, proceed to 7-day MVP build
5. If < 10, pivot or drop

---
*Auto-generated by Research Agent*
"""
        with open(os.path.join(project_dir, 'README.md'), 'w', encoding='utf-8') as f:
            f.write(readme)
        print(f"   Generated README.md")

    def _commit_to_git(self, project_dir: str, opportunity: Dict[str, Any]):
        try:
            one_company_dir = os.path.expanduser("~/Code/one-company-lab")
            if not os.path.exists(os.path.join(one_company_dir, '.git')):
                print(f"   one-company-lab is not a git repo, skipping commit")
                return
            subprocess.run(['git', 'add', '.'], cwd=one_company_dir, capture_output=True)
            commit_msg = f"feat: landing page for {opportunity.get('title', '')[:50]}\n\nAuto-generated by Research Agent"
            subprocess.run(['git', 'commit', '-m', commit_msg], cwd=one_company_dir, capture_output=True)
            subprocess.run(['git', 'push'], cwd=one_company_dir, capture_output=True)
            print(f"   Committed and pushed to one-company-lab")
        except Exception as e:
            print(f"   Git commit failed: {e}")


if __name__ == '__main__':
    test_opp = {
        'title': 'Refund Abuse Audit for Shopify',
        'summary': 'Weekly refund abuse audit reports for Shopify merchants',
        'description': 'Help Shopify merchants identify refund abuse and high-risk orders weekly.',
        'score': 85,
        'revenue_model': 'One-time setup + monthly',
        'startup_cost': '$1-5k',
        'phase2_target_user': 'Shopify merchants with $5-50k monthly GMV',
        'phase2_deliverable': 'Weekly refund abuse audit report',
        'phase2_why_existing_bad': 'Shopify native tools only flag after the fact; no proactive audit.',
        'action_plan': 'Manually audit 20 merchants, deliver report, charge $99/month for ongoing.',
        'customer_acquisition': 'DM Shopify merchants in r/shopify who posted about refund issues.',
    }
    generator = MVPGenerator()
    project_dir = generator.generate(test_opp)
    print(f"\nLanding page generated at: {project_dir}")
