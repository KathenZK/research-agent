"""Collectors package"""

from .hn import HNCollector
from .ph import PHCollector
from .chinese_media import ChineseMediaCollector
from .indiehackers import IndieHackersCollector
from .reddit import RedditCollector
from .reddit_pain import RedditPainCollector
from .github_trending import GitHubTrendingCollector
from .agent_reach_bridge import AgentReachBridge
from .appstore_reviews import AppStoreReviewsCollector
from .github_issues import GitHubIssuesCollector
from .saas_reviews import SaaSReviewsCollector

__all__ = [
    'HNCollector',
    'PHCollector',
    'ChineseMediaCollector',
    'IndieHackersCollector',
    'RedditCollector',
    'RedditPainCollector',
    'GitHubTrendingCollector',
    'AgentReachBridge',
    'AppStoreReviewsCollector',
    'GitHubIssuesCollector',
    'SaaSReviewsCollector',
]
