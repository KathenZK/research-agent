"""Collectors package"""

from .hn import HNCollector
from .ph import PHCollector
from .chinese_media import ChineseMediaCollector
from .indiehackers import IndieHackersCollector
from .reddit import RedditCollector
from .github_trending import GitHubTrendingCollector

__all__ = [
    'HNCollector',
    'PHCollector',
    'ChineseMediaCollector',
    'IndieHackersCollector',
    'RedditCollector',
    'GitHubTrendingCollector'
]
