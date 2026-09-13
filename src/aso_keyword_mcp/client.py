"""ASO Keyword research client using Google Play scraping and NLP."""

from __future__ import annotations

import collections
import math
import os
import re
import statistics
from typing import Any, ClassVar

import structlog

from aso_keyword_mcp.models import (
    AdvancedKeywordScore,
    AppKeywords,
    ASOScore,
    CategoryApp,
    CompetitorAnalysis,
    KeywordDifficulty,
    KeywordRanking,
    KeywordResult,
    KeywordVolume,
    OptimizedListing,
)

logger = structlog.get_logger(__name__)


class ASOClientError(Exception):
    """Base exception for ASO client errors."""


# Common English stop words to filter from keyword extraction
STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "up",
        "about",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "s",
        "t",
        "can",
        "will",
        "just",
        "don",
        "should",
        "now",
        "d",
        "ll",
        "m",
        "o",
        "re",
        "ve",
        "y",
        "ain",
        "aren",
        "couldn",
        "didn",
        "doesn",
        "hadn",
        "hasn",
        "haven",
        "isn",
        "ma",
        "mightn",
        "mustn",
        "needn",
        "shan",
        "shouldn",
        "wasn",
        "weren",
        "won",
        "wouldn",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "having",
        "do",
        "does",
        "did",
        "doing",
        "would",
        "could",
        "might",
        "must",
        "shall",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "i",
        "me",
        "my",
        "myself",
        "we",
        "our",
        "ours",
        "ourselves",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "he",
        "him",
        "his",
        "himself",
        "she",
        "her",
        "hers",
        "herself",
        "they",
        "them",
        "their",
        "theirs",
        "themselves",
        "what",
        "which",
        "who",
        "whom",
        "if",
        "also",
        "app",
        "new",
        "get",
        "use",
    }
)


class ASOClient:
    """Client for ASO keyword research using Google Play data."""

    def __init__(self) -> None:
        """Initialize the ASO client."""
        self._logger = logger.bind(component="ASOClient")

    def _get_play_scraper(self) -> Any:
        """Import and return google_play_scraper module."""
        try:
            import google_play_scraper

            return google_play_scraper
        except ImportError:
            raise ASOClientError(
                "google-play-scraper not installed. Install with: pip install google-play-scraper"
            )

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract meaningful keywords from text."""
        # Normalize and tokenize
        words = re.findall(r"[a-z]+", text.lower())
        # Filter stop words and short words
        keywords = [w for w in words if w not in STOP_WORDS and len(w) > 2]
        return keywords

    def _score_keyword_relevance(self, keyword: str, app_text: str) -> float:
        """Score keyword relevance to app text (0-1)."""
        app_lower = app_text.lower()
        keyword_lower = keyword.lower()

        if keyword_lower in app_lower:
            # Exact match gets high score
            occurrences = app_lower.count(keyword_lower)
            return min(1.0, 0.5 + (occurrences * 0.1))

        # Partial word match
        words = keyword_lower.split()
        matches = sum(1 for w in words if w in app_lower)
        return matches / len(words) if words else 0

    # =========================================================================
    # Keyword Search & Suggestions
    # =========================================================================

    def search_keywords(
        self,
        seed_keyword: str,
        language: str = "en",
        country: str = "us",
        limit: int = 20,
    ) -> list[KeywordResult]:
        """Search for keyword suggestions related to a seed term.

        Args:
            seed_keyword: Seed keyword to find suggestions for.
            language: Language code.
            country: Country code.
            limit: Max results.

        Returns:
            List of keyword suggestions with metadata.
        """
        self._logger.info("Searching keywords", seed=seed_keyword)
        gps = self._get_play_scraper()

        # Search for apps matching the seed keyword
        results = gps.search(seed_keyword, lang=language, country=country, n_hits=30)

        # Extract keywords from search result titles and descriptions
        keyword_freq: collections.Counter[str] = collections.Counter()
        for app in results:
            title = app.get("title", "")
            desc = app.get("description", "")[:500]
            keywords = self._extract_keywords(f"{title} {desc}")
            keyword_freq.update(keywords)

        # Also add seed keyword variations
        seed_words = seed_keyword.lower().split()
        for word in seed_words:
            if word not in STOP_WORDS and len(word) > 2:
                keyword_freq[word] = keyword_freq.get(word, 0) + 10

        # Build results sorted by frequency
        keyword_results: list[KeywordResult] = []
        for kw, freq in keyword_freq.most_common(limit * 2):
            if len(kw) < 3:
                continue

            # Estimate difficulty based on frequency in top results
            difficulty = min(100.0, freq * 5.0)

            keyword_results.append(
                KeywordResult(
                    keyword=kw,
                    search_volume=freq * 100,  # Rough estimate
                    difficulty=round(difficulty, 1),
                    relevance=self._score_keyword_relevance(kw, seed_keyword),
                    suggestion_type="related",
                )
            )

        # Sort by relevance * estimated volume
        keyword_results.sort(
            key=lambda k: (k.relevance or 0) * (k.search_volume or 0),
            reverse=True,
        )

        return keyword_results[:limit]

    def get_keyword_difficulty(
        self,
        keyword: str,
        language: str = "en",
        country: str = "us",
    ) -> KeywordDifficulty:
        """Estimate keyword difficulty based on competition.

        Args:
            keyword: Keyword to analyze.
            language: Language code.
            country: Country code.

        Returns:
            Keyword difficulty assessment.
        """
        self._logger.info("Analyzing keyword difficulty", keyword=keyword)

        api_key = os.environ.get("APPFOLLOW_API_KEY")
        if api_key:
            try:
                import json
                import urllib.parse
                import urllib.request

                device = "android"
                url = f"https://api.appfollow.io/api/v2/aso/search?term={urllib.parse.quote(keyword)}&country={country}&device={device}"
                req = urllib.request.Request(  # noqa: S310 - URL is fixed to HTTPS above
                    url, headers={"X-AppFollow-API-Token": api_key}
                )
                with urllib.request.urlopen(  # noqa: S310 - request URL is fixed to HTTPS
                    req, timeout=5
                ) as response:
                    data = json.loads(response.read().decode())
                    results = data.get("result", [])

                    top_apps = []
                    for i, app in enumerate(results[:10]):
                        top_apps.append(
                            {
                                "rank": app.get("pos", i + 1),
                                "app_id": app.get("extId")
                                or app.get("ext_id")
                                or app.get("id", ""),
                                "title": app.get("title", ""),
                                "score": app.get("rating_avg"),
                                "installs": "1M+" if app.get("pos", 1) <= 3 else "100k+",
                                "developer": app.get("artist_name", ""),
                            }
                        )

                    avg_rating = (
                        sum(a.get("score", 0) or 0 for a in top_apps) / len(top_apps)
                        if top_apps
                        else 0.0
                    )
                    difficulty = min(100.0, (avg_rating * 12) + len(top_apps) * 4)

                    if difficulty < 25:
                        label = "Easy"
                    elif difficulty < 50:
                        label = "Medium"
                    elif difficulty < 75:
                        label = "Hard"
                    else:
                        label = "Very Hard"

                    return KeywordDifficulty(
                        keyword=keyword,
                        difficulty_score=round(difficulty, 1),
                        difficulty_label=label,
                        top_apps_count=len(top_apps),
                        top_apps=top_apps,
                    )
            except Exception as e:
                self._logger.warning(
                    "AppFollow keyword difficulty fetch failed, falling back to scraper",
                    error=str(e),
                )

        gps = self._get_play_scraper()
        results = gps.search(keyword, lang=language, country=country, n_hits=10)

        top_apps = []
        for i, app in enumerate(results[:10]):
            top_apps.append(
                {
                    "rank": i + 1,
                    "app_id": app.get("appId", ""),
                    "title": app.get("title", ""),
                    "score": app.get("score"),
                    "installs": app.get("installs", ""),
                    "developer": app.get("developer", ""),
                }
            )

        # Calculate difficulty based on top apps' strength
        avg_rating = (
            sum(a.get("score", 0) or 0 for a in top_apps) / len(top_apps) if top_apps else 0
        )
        high_install_count = sum(
            1 for a in top_apps if _parse_installs(a.get("installs", "")) > 1_000_000
        )

        difficulty = min(100.0, (avg_rating * 10) + (high_install_count * 8) + len(top_apps) * 3)

        if difficulty < 25:
            label = "Easy"
        elif difficulty < 50:
            label = "Medium"
        elif difficulty < 75:
            label = "Hard"
        else:
            label = "Very Hard"

        return KeywordDifficulty(
            keyword=keyword,
            difficulty_score=round(difficulty, 1),
            difficulty_label=label,
            top_apps_count=len(top_apps),
            top_apps=top_apps,
        )

    def get_keyword_volume(
        self,
        keywords: list[str],
        language: str = "en",
        country: str = "us",
    ) -> list[KeywordVolume]:
        """Estimate search volume for keywords.

        Args:
            keywords: List of keywords to analyze.
            language: Language code.
            country: Country code.

        Returns:
            Volume estimates for each keyword.
        """
        self._logger.info("Estimating keyword volumes", count=len(keywords))

        api_key = os.environ.get("APPFOLLOW_API_KEY")
        if api_key:
            try:
                import json
                import urllib.parse
                import urllib.request

                device = "android"
                appfollow_results: list[KeywordVolume] = []
                for keyword in keywords:
                    url = f"https://api.appfollow.io/api/v2/aso/search?term={urllib.parse.quote(keyword)}&country={country}&device={device}"
                    req = urllib.request.Request(  # noqa: S310 - URL is fixed to HTTPS above
                        url, headers={"X-AppFollow-API-Token": api_key}
                    )
                    with urllib.request.urlopen(  # noqa: S310 - request URL is fixed to HTTPS
                        req, timeout=5
                    ) as response:
                        data = json.loads(response.read().decode())
                        search_results = data.get("result", [])

                        result_count = len(search_results)
                        estimated_volume = int(result_count * 4.5)  # scale to 0-100 index range

                        competition = "low"
                        if result_count >= 20:
                            competition = "high"
                        elif result_count >= 10:
                            competition = "medium"

                        appfollow_results.append(
                            KeywordVolume(
                                keyword=keyword,
                                estimated_volume=estimated_volume,
                                trend="stable",
                                competition_level=competition,
                            )
                        )
                return appfollow_results
            except Exception as e:
                self._logger.warning(
                    "AppFollow keyword volume fetch failed, falling back to scraper", error=str(e)
                )

        gps = self._get_play_scraper()
        results: list[KeywordVolume] = []
        for keyword in keywords:
            search_results = gps.search(keyword, lang=language, country=country, n_hits=5)

            # Estimate volume from result quality signals
            total_installs = sum(_parse_installs(app.get("installs", "")) for app in search_results)
            result_count = len(search_results)

            # Rough volume estimation heuristic
            estimated_volume = int(math.sqrt(total_installs) * result_count * 0.1)

            if estimated_volume > 50000:
                competition = "high"
            elif estimated_volume > 10000:
                competition = "medium"
            else:
                competition = "low"

            results.append(
                KeywordVolume(
                    keyword=keyword,
                    estimated_volume=estimated_volume,
                    trend="stable",
                    competition_level=competition,
                )
            )

        return results

    # =========================================================================
    # Advanced Keyword Scoring
    # =========================================================================

    _PUBLISHER_TIERS: ClassVar[dict[str, list[str]]] = {
        "major": [
            "Google LLC",
            "Meta Platforms",
            "Microsoft Corporation",
            "Apple Inc.",
            "Amazon Mobile LLC",
            "ByteDance",
            "Tencent",
            "Alibaba",
            "Netflix",
            "Spotify",
            "Meta Platforms, Inc.",
            "Google Inc.",
        ],
        "large": [
            "Zynga",
            "King",
            "Supercell",
            "Electronic Arts",
            "Activision",
            "Ubisoft",
            "Sony",
            "Nintendo",
            "Snap Inc",
            "Twitter",
            "Pinterest",
            "LinkedIn",
            "Zynga Inc.",
            "Electronic Arts Inc.",
        ],
    }

    @staticmethod
    def _normalize_log(value: float, min_val: float, max_val: float) -> float:
        """Logarithmic normalization of value into a 0-100 range."""
        if value <= min_val:
            return 0.0
        if value >= max_val:
            return 100.0
        log_min = math.log10(min_val)
        log_max = math.log10(max_val)
        log_val = math.log10(value)
        return ((log_val - log_min) / (log_max - log_min)) * 100

    @classmethod
    def _publisher_tier(cls, publisher: str) -> str:
        if not publisher:
            return "indie"
        publisher_clean = publisher.strip().lower()
        if any(major.lower() in publisher_clean for major in cls._PUBLISHER_TIERS["major"]):
            return "major"
        if any(large.lower() in publisher_clean for large in cls._PUBLISHER_TIERS["large"]):
            return "large"
        return "indie"

    def _app_performance_score(self, app: dict[str, Any]) -> float:
        """Dynamic 0-10 authority score from an app's own install/rating/review stats."""
        installs = _parse_installs(str(app.get("installs", "0")))
        rating = app.get("score", 0) or 0
        reviews = app.get("reviews", 0) or 0
        install_score = self._normalize_log(installs, min_val=1_000, max_val=1_000_000_000)
        rating_score = (float(rating) / 5.0) * 100 if rating > 0 else 0
        review_score = self._normalize_log(reviews, min_val=100, max_val=10_000_000)
        performance = install_score * 0.6 + rating_score * 0.2 + review_score * 0.2
        return min(performance / 10, 10.0)

    def _title_competition(self, keyword: str, apps: list[dict[str, Any]]) -> dict[str, Any]:
        """Position-weighted keyword matches in competing app titles."""
        exact_matches = broad_matches = partial_matches = 0
        weighted_score = 0.0
        keyword_lower = keyword.lower()
        keyword_words = set(keyword_lower.split())

        for i, app in enumerate(apps[:50]):
            position_weight = 1 / math.sqrt(i + 1)
            title_lower = str(app.get("title", "")).lower()
            title_words = set(re.findall(r"\b\w+\b", title_lower))
            if keyword_lower in title_lower:
                exact_matches += 1
                weighted_score += position_weight
            elif keyword_words.issubset(title_words):
                broad_matches += 1
                weighted_score += position_weight * 0.7
            elif keyword_words & title_words:
                partial_matches += 1
                weighted_score += position_weight * 0.3

        max_possible = sum(1 / math.sqrt(i + 1) for i in range(min(50, len(apps))))
        raw_score = (weighted_score / max_possible) * 100 if max_possible > 0 else 0
        return {
            "exact_matches": exact_matches,
            "broad_matches": broad_matches,
            "partial_matches": partial_matches,
            "score": min(raw_score, 100),
        }

    def _competitor_strength(self, top_apps: list[dict[str, Any]]) -> dict[str, Any]:
        if not top_apps:
            return {"avg_installs": 0, "avg_rating": 0, "avg_reviews": 0, "score": 0}
        installs = [_parse_installs(str(app.get("installs", "0"))) for app in top_apps]
        ratings = [float(app.get("score", 0) or 0) for app in top_apps]
        reviews = [int(app.get("reviews", 0) or 0) for app in top_apps]
        avg_installs = statistics.mean(installs)
        avg_rating = statistics.mean(ratings)
        avg_reviews = statistics.mean(reviews)
        install_score = self._normalize_log(avg_installs, min_val=1_000, max_val=1_000_000_000)
        rating_score = ((avg_rating - 3.0) / 2.0) * 100 if avg_rating > 0 else 0
        review_score = self._normalize_log(avg_reviews, min_val=100, max_val=10_000_000)
        raw_score = install_score * 0.5 + rating_score * 0.25 + review_score * 0.25
        return {
            "avg_installs": int(avg_installs),
            "avg_rating": round(avg_rating, 2),
            "avg_reviews": int(avg_reviews),
            "score": min(raw_score, 100),
        }

    def _install_barrier(self, top_5_apps: list[dict[str, Any]]) -> dict[str, Any]:
        if not top_5_apps:
            return {"top5_avg_installs": 0, "barrier_installs": 0, "score": 0}
        installs = [_parse_installs(str(app.get("installs", "0"))) for app in top_5_apps]
        avg_installs = statistics.mean(installs)
        min_installs = min(installs)
        raw_score = self._normalize_log(min_installs, min_val=10_000, max_val=100_000_000)
        return {
            "top5_avg_installs": int(avg_installs),
            "barrier_installs": int(min_installs),
            "score": min(raw_score, 100),
        }

    def _publisher_authority(self, top_apps: list[dict[str, Any]]) -> dict[str, Any]:
        """Higher of a static publisher tier score or a dynamic performance score per app."""
        if not top_apps:
            return {"major_count": 0, "large_count": 0, "indie_count": 0, "score": 0}
        major_count = large_count = indie_count = 0
        weighted = 0.0
        tier_scores = {"major": 10, "large": 7}
        for app in top_apps:
            publisher = str(app.get("developer", ""))
            tier = self._publisher_tier(publisher)
            static_score = tier_scores.get(tier, 0.5)
            if tier == "major":
                major_count += 1
            elif tier == "large":
                large_count += 1
            else:
                indie_count += 1
            weighted += max(static_score, self._app_performance_score(app))
        return {
            "major_count": major_count,
            "large_count": large_count,
            "indie_count": indie_count,
            "score": min((weighted / 100) * 100, 100),
        }

    @staticmethod
    def _autocomplete_heuristic(keyword: str) -> dict[str, Any]:
        """Heuristic autocomplete-position estimate (no live autocomplete API available)."""
        length = len(keyword)
        word_count = len(keyword.split())
        if length <= 8 and word_count <= 2:
            position, score = 1, 100
        elif length <= 15 and word_count <= 3:
            position, score = 3, 70
        elif length <= 25:
            position, score = 7, 40
        else:
            position, score = 0, 10
        return {"position": position, "present": position > 0, "score": score}

    @staticmethod
    def _keyword_characteristics(keyword: str) -> dict[str, Any]:
        length = len(keyword)
        word_count = len(keyword.split())
        length_score = 90 if length <= 8 else 70 if length <= 15 else 50 if length <= 25 else 30
        word_score = {1: 95, 2: 80, 3: 60}.get(word_count, 40)
        return {
            "length": length,
            "word_count": word_count,
            "score": min((length_score + word_score) / 2, 100),
        }

    @staticmethod
    def _score_interpretation(
        difficulty: float, traffic: float, opportunity: float
    ) -> dict[str, str]:
        if difficulty >= 81:
            diff_label, diff_desc = "Very Hard", "dominated by major players"
        elif difficulty >= 61:
            diff_label, diff_desc = "Hard", "needs significant installs/authority"
        elif difficulty >= 41:
            diff_label, diff_desc = "Moderate", "requires a strong app plus ASO"
        elif difficulty >= 21:
            diff_label, diff_desc = "Easy", "achievable with good ASO"
        else:
            diff_label, diff_desc = "Very Easy", "new apps can rank within weeks"

        if traffic >= 81:
            traffic_label, traffic_est = "Very High", "100,000+"
        elif traffic >= 61:
            traffic_label, traffic_est = "High", "10,000-100,000"
        elif traffic >= 41:
            traffic_label, traffic_est = "Medium", "1,000-10,000"
        elif traffic >= 21:
            traffic_label, traffic_est = "Low", "100-1,000"
        else:
            traffic_label, traffic_est = "Very Low", "<100"

        if opportunity >= 60:
            recommendation = (
                f"Excellent opportunity! {traffic_label} traffic with manageable "
                f"competition ({diff_label}). Prioritize this keyword."
            )
        elif opportunity >= 40:
            recommendation = (
                f"Good opportunity. {traffic_label} traffic but {diff_label} competition. "
                "Consider targeting with strong ASO."
            )
        elif opportunity >= 20:
            recommendation = f"Moderate opportunity. {diff_desc.capitalize()}. May take significant effort to rank."
        elif traffic < 30:
            recommendation = f"Low opportunity due to {traffic_label} traffic. Consider higher-volume alternatives."
        else:
            recommendation = (
                f"Low opportunity. {traffic_label} traffic but {diff_label} competition. "
                "Consider long-tail variations."
            )

        return {
            "difficulty_label": diff_label,
            "traffic_label": traffic_label,
            "traffic_estimate": traffic_est,
            "recommendation": recommendation,
        }

    def get_advanced_keyword_difficulty(
        self,
        keyword: str,
        country: str = "us",
        limit: int = 50,
    ) -> AdvancedKeywordScore:
        """Multi-factor difficulty/traffic/opportunity scoring for a keyword.

        Difficulty = title competition (30%) + competitor strength (25%) +
        install barrier (20%) + publisher authority (25%, combining the PRD's
        publisher-authority and ranking-stability weights since ranking history
        isn't available from a single scrape). Traffic = search depth (30%) +
        top-app installs (25%) + autocomplete heuristic (20%) + keyword
        characteristics (25%). Opportunity = traffic * (100 - difficulty) / 100.

        Args:
            keyword: The keyword to analyze (e.g., 'photo editor').
            country: Country code (default: us).
            limit: Number of competing apps to sample (default: 50).

        Returns:
            Difficulty, traffic, and opportunity scores with component breakdowns.
        """
        self._logger.info("Analyzing advanced keyword score", keyword=keyword)
        gps = self._get_play_scraper()
        apps = gps.search(keyword, lang="en", country=country, n_hits=limit)

        if not apps:
            interpretation = self._score_interpretation(0, 0, 0)
            return AdvancedKeywordScore(
                keyword=keyword,
                country=country,
                difficulty_score=0,
                traffic_score=0,
                opportunity_score=0,
                difficulty_breakdown={},
                traffic_breakdown={},
                **interpretation,
            )

        difficulty_breakdown = {
            "title_competition": self._title_competition(keyword, apps),
            "competitor_strength": self._competitor_strength(apps[:10]),
            "install_barrier": self._install_barrier(apps[:5]),
            "publisher_authority": self._publisher_authority(apps[:10]),
        }
        traffic_breakdown = {
            "search_depth": {
                "total_results": len(apps),
                "score": min((len(apps) / limit) * 100, 100) if limit else 0,
            },
            "top_app_installs": {
                "installs": _parse_installs(str(apps[0].get("installs", "0"))),
                "score": min(
                    self._normalize_log(
                        _parse_installs(str(apps[0].get("installs", "0"))),
                        min_val=1_000,
                        max_val=1_000_000_000,
                    ),
                    100,
                ),
            },
            "autocomplete": self._autocomplete_heuristic(keyword),
            "keyword_characteristics": self._keyword_characteristics(keyword),
        }

        difficulty_score = min(
            difficulty_breakdown["title_competition"]["score"] * 0.30
            + difficulty_breakdown["competitor_strength"]["score"] * 0.25
            + difficulty_breakdown["install_barrier"]["score"] * 0.20
            + difficulty_breakdown["publisher_authority"]["score"] * 0.25,
            100,
        )
        traffic_score = min(
            traffic_breakdown["search_depth"]["score"] * 0.30
            + traffic_breakdown["top_app_installs"]["score"] * 0.25
            + traffic_breakdown["autocomplete"]["score"] * 0.20
            + traffic_breakdown["keyword_characteristics"]["score"] * 0.25,
            100,
        )
        opportunity_score = min(traffic_score * ((100 - difficulty_score) / 100), 100)
        interpretation = self._score_interpretation(
            difficulty_score, traffic_score, opportunity_score
        )

        return AdvancedKeywordScore(
            keyword=keyword,
            country=country,
            difficulty_score=round(difficulty_score, 1),
            traffic_score=round(traffic_score, 1),
            opportunity_score=round(opportunity_score, 1),
            difficulty_breakdown=difficulty_breakdown,
            traffic_breakdown=traffic_breakdown,
            **interpretation,
        )

    # =========================================================================
    # App Keyword Analysis
    # =========================================================================

    def get_app_keywords(
        self,
        package_name: str,
        language: str = "en",
        country: str = "us",
    ) -> AppKeywords:
        """Extract keywords from an app's current store listing.

        Args:
            package_name: App package name.
            language: Language code.
            country: Country code.

        Returns:
            Extracted keywords from title and description.
        """
        self._logger.info("Extracting app keywords", package=package_name)
        gps = self._get_play_scraper()

        app_info = gps.app(package_name, lang=language, country=country)

        title = app_info.get("title", "")
        description = app_info.get("description", "")

        title_kws = self._extract_keywords(title)
        desc_kws = self._extract_keywords(description)

        # Count keyword frequency in description
        desc_freq = collections.Counter(desc_kws)

        all_kws: list[KeywordResult] = []
        seen: set[str] = set()

        # Title keywords get higher weight
        for kw in title_kws:
            if kw not in seen:
                seen.add(kw)
                all_kws.append(
                    KeywordResult(
                        keyword=kw,
                        relevance=1.0,
                        suggestion_type="title",
                    )
                )

        # Description keywords
        for kw, freq in desc_freq.most_common(50):
            if kw not in seen:
                seen.add(kw)
                all_kws.append(
                    KeywordResult(
                        keyword=kw,
                        relevance=min(1.0, freq / 10.0),
                        suggestion_type="description",
                    )
                )

        return AppKeywords(
            package_name=package_name,
            title_keywords=title_kws,
            description_keywords=list(desc_freq.keys())[:30],
            all_keywords=all_kws,
        )

    def get_competitor_keywords(
        self,
        package_name: str,
        competitor_package: str,
        language: str = "en",
        country: str = "us",
    ) -> CompetitorAnalysis:
        """Analyze competitor app keywords and find gaps.

        Args:
            package_name: Your app package name.
            competitor_package: Competitor app package name.
            language: Language code.
            country: Country code.

        Returns:
            Competitor keyword analysis with gaps and opportunities.
        """
        self._logger.info(
            "Analyzing competitor keywords",
            target=package_name,
            competitor=competitor_package,
        )

        target_kws = self.get_app_keywords(package_name, language, country)
        competitor_kws = self.get_app_keywords(competitor_package, language, country)

        target_set = set(target_kws.description_keywords + target_kws.title_keywords)
        competitor_set = set(competitor_kws.description_keywords + competitor_kws.title_keywords)

        shared = list(target_set & competitor_set)
        unique_competitor = list(competitor_set - target_set)

        # Score keyword gaps as opportunities
        gap_keywords = [
            KeywordResult(
                keyword=kw,
                relevance=self._score_keyword_relevance(kw, " ".join(target_kws.title_keywords)),
                suggestion_type="competitor_gap",
            )
            for kw in unique_competitor[:20]
        ]

        gps = self._get_play_scraper()
        competitor_info = gps.app(competitor_package, lang=language, country=country)

        return CompetitorAnalysis(
            target_package=package_name,
            competitor_package=competitor_package,
            competitor_name=competitor_info.get("title"),
            shared_keywords=shared,
            unique_competitor_keywords=unique_competitor,
            keyword_gap=gap_keywords,
        )

    # =========================================================================
    # Ranking & Category
    # =========================================================================

    def track_keyword_ranking(
        self,
        keyword: str,
        package_name: str,
        language: str = "en",
        country: str = "us",
    ) -> KeywordRanking:
        """Check current ranking for a keyword.

        Args:
            keyword: Keyword to check.
            package_name: App package name to find.
            language: Language code.
            country: Country code.

        Returns:
            Current ranking position.
        """
        self._logger.info("Tracking keyword ranking", keyword=keyword, package=package_name)

        api_key = os.environ.get("APPFOLLOW_API_KEY")
        if api_key:
            try:
                import json
                import urllib.parse
                import urllib.request

                device = "android"
                url = f"https://api.appfollow.io/api/v2/aso/search?term={urllib.parse.quote(keyword)}&country={country}&device={device}"
                req = urllib.request.Request(  # noqa: S310 - URL is fixed to HTTPS above
                    url, headers={"X-AppFollow-API-Token": api_key}
                )
                with urllib.request.urlopen(  # noqa: S310 - request URL is fixed to HTTPS
                    req, timeout=5
                ) as response:
                    data = json.loads(response.read().decode())
                    results = data.get("result", [])
                    for i, app in enumerate(results):
                        app_id = app.get("extId") or app.get("ext_id") or app.get("id")
                        if app_id == package_name:
                            return KeywordRanking(
                                keyword=keyword,
                                package_name=package_name,
                                rank=app.get("pos", i + 1),
                                was_found=True,
                                total_results=len(results),
                            )
                    return KeywordRanking(
                        keyword=keyword,
                        package_name=package_name,
                        rank=None,
                        was_found=False,
                        total_results=len(results),
                    )
            except Exception as e:
                self._logger.warning(
                    "AppFollow keyword ranking fetch failed, falling back to scraper", error=str(e)
                )

        gps = self._get_play_scraper()
        results = gps.search(keyword, lang=language, country=country, n_hits=50)

        for i, app in enumerate(results):
            if app.get("appId") == package_name:
                return KeywordRanking(
                    keyword=keyword,
                    package_name=package_name,
                    rank=i + 1,
                    was_found=True,
                    total_results=len(results),
                )

        return KeywordRanking(
            keyword=keyword,
            package_name=package_name,
            rank=None,
            was_found=False,
            total_results=len(results),
        )

    def get_category_top_apps(
        self,
        category: str,
        language: str = "en",
        country: str = "us",
        limit: int = 30,
    ) -> list[CategoryApp]:
        """Get top apps in a Play Store category.

        Args:
            category: Play Store category (e.g., 'PRODUCTIVITY', 'GAME_ACTION').
            language: Language code.
            country: Country code.
            limit: Max apps to return.

        Returns:
            Top apps in the category.
        """
        self._logger.info("Fetching category top apps", category=category)
        gps = self._get_play_scraper()

        # Use collection for top charts
        try:
            results = gps.search(
                category,
                lang=language,
                country=country,
                n_hits=limit,
            )
        except Exception:
            # Fall back to searching category name
            results = gps.search(
                category.replace("_", " ").lower(),
                lang=language,
                country=country,
                n_hits=limit,
            )

        apps: list[CategoryApp] = []
        for i, app in enumerate(results[:limit]):
            apps.append(
                CategoryApp(
                    rank=i + 1,
                    app_id=app.get("appId", ""),
                    title=app.get("title"),
                    developer=app.get("developer"),
                    score=app.get("score"),
                    installs=app.get("installs"),
                    free=app.get("free", True),
                )
            )

        return apps

    # =========================================================================
    # ASO Analysis & Optimization
    # =========================================================================

    def analyze_listing_aso(
        self,
        package_name: str,
        language: str = "en",
        country: str = "us",
    ) -> ASOScore:
        """Analyze ASO quality of current store listing.

        Args:
            package_name: App package name.
            language: Language code.
            country: Country code.

        Returns:
            ASO score with recommendations.
        """
        self._logger.info("Analyzing listing ASO", package=package_name)
        gps = self._get_play_scraper()

        app_info = gps.app(package_name, lang=language, country=country)

        title = app_info.get("title", "")
        short_desc = app_info.get("summary", "")
        full_desc = app_info.get("description", "")
        video = app_info.get("video")

        recommendations: list[str] = []
        title_score = 0
        desc_score = 0

        # Title analysis (max 30 chars for optimal)
        title_len = len(title)
        if 20 <= title_len <= 50:
            title_score += 40
        elif title_len < 20:
            title_score += 20
            recommendations.append("Title is too short. Include target keywords.")
        else:
            title_score += 30

        # Check if title has keywords (not just brand)
        title_words = self._extract_keywords(title)
        if len(title_words) >= 2:
            title_score += 30
        else:
            title_score += 10
            recommendations.append("Add descriptive keywords to your title.")

        # Unique words in title
        if len(set(title_words)) == len(title_words):
            title_score += 30
        else:
            title_score += 15
            recommendations.append("Avoid repeating words in the title.")

        # Description analysis
        desc_len = len(full_desc)
        if desc_len >= 2000:
            desc_score += 30
        elif desc_len >= 1000:
            desc_score += 20
            recommendations.append("Expand description to 2000+ characters for better SEO.")
        else:
            desc_score += 10
            recommendations.append("Description is too short. Aim for 2000-4000 characters.")

        # Keyword density in description
        desc_words = self._extract_keywords(full_desc)
        keyword_density = 0.0
        if desc_words:
            freq = collections.Counter(desc_words)
            top_kw_count = sum(c for _, c in freq.most_common(5))
            keyword_density = (top_kw_count / len(desc_words)) * 100

        if 2.0 <= keyword_density <= 5.0:
            desc_score += 30
        elif keyword_density < 2.0:
            desc_score += 15
            recommendations.append("Increase keyword usage in description (aim for 2-5% density).")
        else:
            desc_score += 10
            recommendations.append("Reduce keyword stuffing in description.")

        # Structure (bullet points, formatting)
        if "•" in full_desc or "✓" in full_desc or "★" in full_desc or "✔" in full_desc:
            desc_score += 20
        else:
            desc_score += 5
            recommendations.append("Use bullet points and emojis to improve readability.")

        # Short description
        if short_desc and len(short_desc) >= 40:
            desc_score += 20
        else:
            recommendations.append("Write a compelling short description (max 80 chars).")

        # Video bonus
        has_video = video is not None and video != ""
        if not has_video:
            recommendations.append("Add a promo video to increase conversion rates.")

        overall = int(title_score * 0.4 + desc_score * 0.6)
        if has_video:
            overall = min(100, overall + 5)

        return ASOScore(
            package_name=package_name,
            overall_score=overall,
            title_score=title_score,
            description_score=desc_score,
            keyword_density=round(keyword_density, 2),
            recommendations=recommendations,
            title_length=title_len,
            description_length=desc_len,
            has_video=has_video,
        )

    def generate_optimized_listing(
        self,
        package_name: str,
        target_keywords: list[str] | None = None,
        language: str = "en",
        country: str = "us",
    ) -> OptimizedListing:
        """Generate ASO-optimized store listing suggestions.

        Uses current listing data and keyword analysis to suggest improvements.

        Args:
            package_name: App package name.
            target_keywords: Keywords to target in optimization.
            language: Language code.
            country: Country code.

        Returns:
            Optimized listing suggestions.
        """
        self._logger.info("Generating optimized listing", package=package_name)
        gps = self._get_play_scraper()

        app_info = gps.app(package_name, lang=language, country=country)

        title = app_info.get("title", "")
        short_desc = app_info.get("summary", "")
        full_desc = app_info.get("description", "")

        # Get keywords if not provided
        if not target_keywords:
            app_kws = self.get_app_keywords(package_name, language, country)
            target_keywords = [kw.keyword for kw in app_kws.all_keywords[:5]]

        improvements: list[str] = []

        # Optimize title — add top keyword if missing
        suggested_title = title
        for kw in target_keywords[:2]:
            if kw.lower() not in title.lower() and len(suggested_title) + len(kw) + 3 <= 50:
                suggested_title = f"{suggested_title} - {kw.title()}"
                improvements.append(f"Added keyword '{kw}' to title")
                break

        # Optimize short description
        suggested_short = short_desc or ""
        if not suggested_short or len(suggested_short) < 40:
            kw_str = ", ".join(target_keywords[:3])
            suggested_short = f"{title.split('-')[0].strip()}: {kw_str}. Try it free!"
            improvements.append("Generated compelling short description with keywords")

        # Optimize full description
        suggested_desc = full_desc
        if len(full_desc) < 1500:
            # Add structured keyword sections
            keyword_section = "\n\n🔑 KEY FEATURES:\n"
            for kw in target_keywords[:5]:
                keyword_section += f"✅ {kw.title()} support\n"
            suggested_desc = full_desc + keyword_section
            improvements.append("Added structured keyword features section")

        # Add call-to-action if missing
        cta_words = ["download", "install", "try", "get started", "free"]
        if not any(w in suggested_desc.lower() for w in cta_words):
            suggested_desc += "\n\n📥 Download now and get started for free!"
            improvements.append("Added call-to-action at the end")

        return OptimizedListing(
            package_name=package_name,
            original_title=title,
            suggested_title=suggested_title,
            original_short_description=short_desc,
            suggested_short_description=suggested_short[:80],
            original_description=full_desc[:500] + "..." if len(full_desc) > 500 else full_desc,
            suggested_description=suggested_desc[:4000],
            target_keywords=target_keywords,
            improvements=improvements,
        )


# =============================================================================
# Helpers
# =============================================================================


def _parse_installs(installs_str: str) -> int:
    """Parse install count string to integer."""
    if not installs_str:
        return 0
    cleaned = installs_str.replace(",", "").replace("+", "").strip()
    try:
        return int(cleaned)
    except ValueError:
        return 0
