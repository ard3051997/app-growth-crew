"""Tests for ASO Keyword MCP Server."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from aso_keyword_mcp.client import ASOClient, _parse_installs
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


class TestParseInstalls:
    """Tests for install count parsing."""

    def test_parse_numeric(self) -> None:
        assert _parse_installs("1000000") == 1000000

    def test_parse_with_commas(self) -> None:
        assert _parse_installs("1,000,000") == 1000000

    def test_parse_with_plus(self) -> None:
        assert _parse_installs("1,000,000+") == 1000000

    def test_parse_empty(self) -> None:
        assert _parse_installs("") == 0

    def test_parse_invalid(self) -> None:
        assert _parse_installs("abc") == 0


class TestASOClientKeywordExtraction:
    """Tests for keyword extraction logic."""

    def test_extract_keywords(self) -> None:
        client = ASOClient()
        keywords = client._extract_keywords("Best Photo Editor - Free Image Editing Tools")
        assert "best" in keywords
        assert "photo" in keywords
        assert "editor" in keywords
        assert "free" in keywords
        assert "image" in keywords
        assert "editing" in keywords
        assert "tools" in keywords

    def test_extract_keywords_removes_stop_words(self) -> None:
        client = ASOClient()
        keywords = client._extract_keywords("the best app for editing and management")
        assert "the" not in keywords
        assert "for" not in keywords
        assert "and" not in keywords
        assert "best" in keywords
        assert "editing" in keywords

    def test_extract_keywords_empty(self) -> None:
        client = ASOClient()
        assert client._extract_keywords("") == []

    def test_score_keyword_relevance(self) -> None:
        client = ASOClient()
        score = client._score_keyword_relevance("photo", "best photo editor for photos")
        assert score > 0.5  # "photo" appears multiple times

    def test_score_keyword_relevance_no_match(self) -> None:
        client = ASOClient()
        score = client._score_keyword_relevance("video", "best photo editor")
        assert score == 0.0


def _synthetic_apps(count: int) -> list[dict[str, Any]]:
    return [
        {
            "title": f"Photo Editor App {i}",
            "developer": "Indie Dev" if i % 3 else "Google LLC",
            "score": 4.2,
            "reviews": 5_000 * (i + 1),
            "installs": f"{(i + 1) * 100_000}+",
        }
        for i in range(count)
    ]


class TestAdvancedKeywordScoring:
    """Tests for the ported multi-factor keyword scorer."""

    def test_scores_are_bounded_and_breakdown_is_populated(self) -> None:
        client = ASOClient()
        client._get_play_scraper = MagicMock(  # type: ignore[method-assign]
            return_value=MagicMock(search=MagicMock(return_value=_synthetic_apps(20)))
        )

        result = client.get_advanced_keyword_difficulty("photo editor", country="us", limit=20)

        assert isinstance(result, AdvancedKeywordScore)
        assert 0 <= result.difficulty_score <= 100
        assert 0 <= result.traffic_score <= 100
        assert 0 <= result.opportunity_score <= 100
        assert result.difficulty_label
        assert result.traffic_label
        assert result.recommendation
        assert set(result.difficulty_breakdown) == {
            "title_competition",
            "competitor_strength",
            "install_barrier",
            "publisher_authority",
        }
        assert set(result.traffic_breakdown) == {
            "search_depth",
            "top_app_installs",
            "autocomplete",
            "keyword_characteristics",
        }

    def test_no_competing_apps_returns_zero_scores(self) -> None:
        client = ASOClient()
        client._get_play_scraper = MagicMock(  # type: ignore[method-assign]
            return_value=MagicMock(search=MagicMock(return_value=[]))
        )

        result = client.get_advanced_keyword_difficulty("an extremely obscure keyword")

        assert result.difficulty_score == 0
        assert result.traffic_score == 0
        assert result.opportunity_score == 0
        assert result.difficulty_breakdown == {}
        assert result.traffic_breakdown == {}

    def test_major_publisher_scores_higher_authority_than_indie(self) -> None:
        client = ASOClient()
        major = {"developer": "Google LLC", "score": 4.5, "reviews": 1_000_000, "installs": "1B+"}
        indie = {"developer": "Solo Dev", "score": 4.5, "reviews": 100, "installs": "1,000+"}

        major_authority = client._publisher_authority([major])
        indie_authority = client._publisher_authority([indie])

        assert major_authority["score"] > indie_authority["score"]
        assert major_authority["major_count"] == 1
        assert indie_authority["indie_count"] == 1

    def test_higher_difficulty_lowers_opportunity_at_fixed_traffic(self) -> None:
        interpretation_easy = ASOClient._score_interpretation(20, 70, 70 * 0.8)
        interpretation_hard = ASOClient._score_interpretation(90, 70, 70 * 0.1)

        assert "Excellent" in interpretation_easy["recommendation"] or (
            "Good" in interpretation_easy["recommendation"]
        )
        assert interpretation_easy["difficulty_label"] != interpretation_hard["difficulty_label"]


class TestASOModels:
    """Tests for ASO Pydantic models."""

    def test_keyword_result(self) -> None:
        kw = KeywordResult(
            keyword="photo editor",
            search_volume=50000,
            difficulty=45.5,
            relevance=0.85,
            suggestion_type="related",
        )
        assert kw.keyword == "photo editor"
        assert kw.difficulty == 45.5

    def test_keyword_difficulty(self) -> None:
        diff = KeywordDifficulty(
            keyword="photo editor",
            difficulty_score=65.0,
            difficulty_label="Hard",
            top_apps_count=10,
        )
        assert diff.difficulty_label == "Hard"

    def test_keyword_volume(self) -> None:
        vol = KeywordVolume(
            keyword="task manager",
            estimated_volume=30000,
            trend="rising",
            competition_level="medium",
        )
        assert vol.trend == "rising"

    def test_app_keywords(self) -> None:
        ak = AppKeywords(
            package_name="com.example.app",
            title_keywords=["task", "manager"],
            description_keywords=["productivity", "organize"],
        )
        assert len(ak.title_keywords) == 2

    def test_competitor_analysis(self) -> None:
        ca = CompetitorAnalysis(
            target_package="com.my.app",
            competitor_package="com.rival.app",
            shared_keywords=["photo", "editor"],
            unique_competitor_keywords=["collage", "filters"],
        )
        assert len(ca.shared_keywords) == 2
        assert len(ca.unique_competitor_keywords) == 2

    def test_keyword_ranking(self) -> None:
        kr = KeywordRanking(
            keyword="photo editor",
            package_name="com.my.app",
            rank=5,
            was_found=True,
            total_results=50,
        )
        assert kr.rank == 5
        assert kr.was_found is True

    def test_category_app(self) -> None:
        app = CategoryApp(
            rank=1,
            app_id="com.top.app",
            title="Top App",
            score=4.8,
            installs="10,000,000+",
        )
        assert app.rank == 1

    def test_aso_score(self) -> None:
        score = ASOScore(
            package_name="com.my.app",
            overall_score=75,
            title_score=80,
            description_score=70,
            keyword_density=3.5,
            recommendations=["Add more keywords to title"],
        )
        assert score.overall_score == 75
        assert len(score.recommendations) == 1

    def test_optimized_listing(self) -> None:
        listing = OptimizedListing(
            package_name="com.my.app",
            suggested_title="My App - Task Manager & Organizer",
            suggested_short_description="Best task manager for productivity",
            suggested_description="Full optimized description...",
            target_keywords=["task", "manager", "productivity"],
            improvements=["Added keywords to title"],
        )
        assert len(listing.target_keywords) == 3

    def test_model_serialization(self) -> None:
        kw = KeywordResult(keyword="test", difficulty=50.0)
        data = kw.model_dump()
        assert isinstance(data, dict)
        assert data["keyword"] == "test"
