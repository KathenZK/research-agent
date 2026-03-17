#!/usr/bin/env python3

import unittest
from unittest.mock import Mock, patch

import main
from collectors.appstore_reviews import AppStoreReviewsCollector
from collectors.github_issues import GitHubIssuesCollector


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class NewSourceCollectorTests(unittest.TestCase):
    def test_app_store_reviews_collector_extracts_low_rating_reviews(self):
        top_apps_payload = {
            "feed": {
                "entry": {
                    "id": {"attributes": {"im:id": "12345"}},
                    "im:name": {"label": "Focus App"},
                    "link": {"attributes": {"href": "https://apps.apple.com/app/id12345"}},
                }
            }
        }
        reviews_payload = {
            "feed": {
                "entry": [
                    {"id": {"label": "meta"}},
                    {
                        "id": {"label": "review-1"},
                        "im:rating": {"label": "1"},
                        "title": {"label": "Keeps failing"},
                        "content": {"label": "The sync breaks every morning and I still need to export data manually to finish my workflow."},
                        "author": {"name": {"label": "founder1"}},
                        "link": {"attributes": {"href": "https://apps.apple.com/review/1"}},
                    },
                    {
                        "id": {"label": "review-2"},
                        "im:rating": {"label": "5"},
                        "title": {"label": "Great"},
                        "content": {"label": "Works well."},
                        "author": {"name": {"label": "happy-user"}},
                        "link": {"attributes": {"href": "https://apps.apple.com/review/2"}},
                    },
                ]
            }
        }

        fake_session = Mock()
        fake_session.get.side_effect = [_FakeResponse(top_apps_payload), _FakeResponse(reviews_payload)]

        collector = AppStoreReviewsCollector()
        with patch.object(AppStoreReviewsCollector, "_session", return_value=fake_session):
            items = collector.fetch(limit=1, per_app_reviews=2)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "appstore_reviews")
        self.assertIn("Focus App", items[0]["title"])
        self.assertIn("Rating: 1/5", items[0]["description"])

    def test_github_issues_collector_extracts_high_comment_pain_threads(self):
        issues_payload = [
            {
                "number": 101,
                "title": "Missing support for team refund review workflow",
                "body": "We cannot reliably review refund disputes without exporting data by hand every week.",
                "comments": 6,
                "labels": [{"name": "enhancement"}],
                "html_url": "https://github.com/example/repo/issues/101",
            },
            {
                "number": 102,
                "title": "Docs update",
                "body": "small typo",
                "comments": 1,
                "labels": [{"name": "documentation"}],
                "html_url": "https://github.com/example/repo/issues/102",
            },
        ]

        fake_session = Mock()
        fake_session.get.return_value = _FakeResponse(issues_payload)

        collector = GitHubIssuesCollector(repos=["example/repo"], token="")
        with patch.object(GitHubIssuesCollector, "_session", return_value=fake_session):
            items = collector.fetch(limit=5, min_comments=3)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "github_issues")
        self.assertIn("example/repo", items[0]["title"])
        self.assertEqual(items[0]["score"], 6)

    def test_collect_data_includes_pain_sources_by_default(self):
        with patch.object(main.HNCollector, "fetch", return_value=[]), \
             patch.object(main.PHCollector, "fetch", return_value=[]), \
             patch("main.ChineseMediaCollector.fetch", return_value=[]), \
             patch("main.GitHubTrendingCollector.fetch", return_value=[]), \
             patch("main.RedditCollector.fetch", return_value=[]), \
             patch("main.RedditPainCollector.fetch", return_value=[]), \
             patch("main.SaaSReviewsCollector.fetch", return_value=[]), \
             patch.object(AppStoreReviewsCollector, "fetch", return_value=[
                 {"id": "a1", "title": "app review", "source": "appstore_reviews", "url": "https://example.com"}
             ]), \
             patch.object(GitHubIssuesCollector, "fetch", return_value=[
                 {"id": "g1", "title": "issue pain", "source": "github_issues", "url": "https://example.com"}
             ]):
            items = main.collect_data(
                hn_limit=0, ph_limit=0, media_hours=1,
                reddit_limit=0, github_limit=0,
                enable_app_store_reviews=True, app_store_review_limit=2,
                enable_github_pain_issues=True, github_pain_limit=2,
                reddit_pain_limit=0, enable_saas_reviews=False,
            )

        sources = {item["source"] for item in items}
        self.assertIn("appstore_reviews", sources)
        self.assertIn("github_issues", sources)


if __name__ == "__main__":
    unittest.main()
