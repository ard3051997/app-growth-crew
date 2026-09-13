"""Tests for aso_keyword_mcp/server.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aso_keyword_mcp.client import ASOClient, ASOClientError
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
from aso_keyword_mcp.server import (
    analyze_listing_aso,
    generate_optimized_listing,
    get_advanced_keyword_difficulty,
    get_app_keywords,
    get_category_top_apps,
    get_competitor_keywords,
    get_keyword_difficulty,
    get_keyword_volume,
    mcp,
    search_keywords,
    track_keyword_ranking,
)


def _mock_context(client: MagicMock) -> MagicMock:
    """Create a mock MCP context with the given client."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"client": client}
    return ctx


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock ASOClient."""
    return MagicMock(spec=ASOClient)


@pytest.fixture(autouse=True)
def _patch_mcp_context(mock_client: MagicMock) -> Any:
    """Patch mcp.get_context to return our mock client."""
    ctx = _mock_context(mock_client)
    with patch.object(mcp, "get_context", return_value=ctx):
        yield


class TestLifespan:
    """Test ASO Keyword server lifespan."""

    @pytest.mark.asyncio
    async def test_lifespan_success(self) -> None:
        """Test successful lifespan initialization."""
        from aso_keyword_mcp.server import lifespan

        mock_server = MagicMock()

        with (
            patch("aso_keyword_mcp.server.ASOClient") as MockClient,
            patch("aso_keyword_mcp.server.ASOClientError", ASOClientError),
        ):
            instance = MockClient.return_value
            async with lifespan(mock_server) as ctx:
                assert ctx["client"] is instance

    @pytest.mark.asyncio
    async def test_lifespan_failure(self) -> None:
        """Test lifespan initialization failure."""
        from aso_keyword_mcp.server import lifespan

        mock_server = MagicMock()

        with (
            patch("aso_keyword_mcp.server.ASOClient", side_effect=ASOClientError("init error")),
            patch("aso_keyword_mcp.server.ASOClientError", ASOClientError),
        ):
            async with lifespan(mock_server) as ctx:
                assert ctx["client"] is None


class TestKeywordResearchTools:
    """Test keyword research server tools."""

    def test_search_keywords(self, mock_client: MagicMock) -> None:
        mock_client.search_keywords.return_value = [
            KeywordResult(keyword="test", search_volume=10, difficulty=5.0),
        ]

        result = search_keywords("test", language="en", country="us", limit=10)
        mock_client.search_keywords.assert_called_once_with("test", "en", "us", 10)
        assert len(result) == 1
        assert result[0]["keyword"] == "test"

    def test_get_keyword_difficulty(self, mock_client: MagicMock) -> None:
        mock_client.get_keyword_difficulty.return_value = KeywordDifficulty(
            keyword="test",
            difficulty_score=30.0,
            difficulty_label="Easy",
        )

        result = get_keyword_difficulty("test", language="en", country="us")
        mock_client.get_keyword_difficulty.assert_called_once_with("test", "en", "us")
        assert result["difficulty_score"] == 30.0

    def test_get_advanced_keyword_difficulty(self, mock_client: MagicMock) -> None:
        mock_client.get_advanced_keyword_difficulty.return_value = AdvancedKeywordScore(
            keyword="test",
            country="us",
            difficulty_score=45.0,
            traffic_score=60.0,
            opportunity_score=33.0,
            difficulty_label="Moderate",
            traffic_label="Medium",
            traffic_estimate="1,000-10,000",
            recommendation="Moderate opportunity.",
        )

        result = get_advanced_keyword_difficulty("test", country="us", limit=50)
        mock_client.get_advanced_keyword_difficulty.assert_called_once_with("test", "us", 50)
        assert result["difficulty_score"] == 45.0
        assert result["opportunity_score"] == 33.0

    def test_get_keyword_volume(self, mock_client: MagicMock) -> None:
        mock_client.get_keyword_volume.return_value = [
            KeywordVolume(keyword="test", estimated_volume=100),
        ]

        result = get_keyword_volume(["test"], language="en", country="us")
        mock_client.get_keyword_volume.assert_called_once_with(["test"], "en", "us")
        assert len(result) == 1
        assert result[0]["estimated_volume"] == 100


class TestAppKeywordAnalysisTools:
    """Test app keyword analysis tools."""

    def test_get_app_keywords(self, mock_client: MagicMock) -> None:
        mock_client.get_app_keywords.return_value = AppKeywords(
            package_name="com.test",
            title_keywords=["test"],
            description_keywords=[],
        )

        result = get_app_keywords("com.test", language="en", country="us")
        mock_client.get_app_keywords.assert_called_once_with("com.test", "en", "us")
        assert result["package_name"] == "com.test"

    def test_get_competitor_keywords(self, mock_client: MagicMock) -> None:
        mock_client.get_competitor_keywords.return_value = CompetitorAnalysis(
            target_package="com.test",
            competitor_package="com.rival",
            shared_keywords=[],
            unique_competitor_keywords=[],
        )

        result = get_competitor_keywords("com.test", "com.rival", language="en", country="us")
        mock_client.get_competitor_keywords.assert_called_once_with(
            "com.test", "com.rival", "en", "us"
        )
        assert result["target_package"] == "com.test"


class TestRankingCategoryTools:
    """Test ranking and category tools."""

    def test_track_keyword_ranking(self, mock_client: MagicMock) -> None:
        mock_client.track_keyword_ranking.return_value = KeywordRanking(
            keyword="test",
            package_name="com.test",
            rank=3,
            was_found=True,
            total_results=20,
        )

        result = track_keyword_ranking("test", "com.test", language="en", country="us")
        mock_client.track_keyword_ranking.assert_called_once_with("test", "com.test", "en", "us")
        assert result["rank"] == 3

    def test_get_category_top_apps(self, mock_client: MagicMock) -> None:
        mock_client.get_category_top_apps.return_value = [
            CategoryApp(rank=1, app_id="com.test", title="Top App"),
        ]

        result = get_category_top_apps("PRODUCTIVITY", language="en", country="us", limit=5)
        mock_client.get_category_top_apps.assert_called_once_with("PRODUCTIVITY", "en", "us", 5)
        assert len(result) == 1


class TestASOOptimizationTools:
    """Test ASO optimization tools."""

    def test_analyze_listing_aso(self, mock_client: MagicMock) -> None:
        mock_client.analyze_listing_aso.return_value = ASOScore(
            package_name="com.test",
            overall_score=80,
            title_score=90,
            description_score=70,
            keyword_density=2.5,
            recommendations=[],
        )

        result = analyze_listing_aso("com.test", language="en", country="us")
        mock_client.analyze_listing_aso.assert_called_once_with("com.test", "en", "us")
        assert result["overall_score"] == 80

    def test_generate_optimized_listing(self, mock_client: MagicMock) -> None:
        mock_client.generate_optimized_listing.return_value = OptimizedListing(
            package_name="com.test",
            suggested_title="Optimized App",
            suggested_short_description="Short desc",
            suggested_description="Long desc",
            target_keywords=[],
            improvements=[],
        )

        result = generate_optimized_listing(
            "com.test", target_keywords=["test"], language="en", country="us"
        )
        mock_client.generate_optimized_listing.assert_called_once_with(
            "com.test", ["test"], "en", "us"
        )
        assert result["suggested_title"] == "Optimized App"


class TestServerMain:
    """Test server main entry point."""

    def test_main_calls_mcp_run(self) -> None:
        from aso_keyword_mcp.server import main

        with patch.object(mcp, "run") as mock_run:
            main([])
            mock_run.assert_called_once()
