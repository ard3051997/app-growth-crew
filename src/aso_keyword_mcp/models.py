"""Pydantic models for ASO Keyword MCP Server."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class KeywordResult(BaseModel):
    """A keyword search result with metadata."""

    keyword: str = Field(..., description="The keyword")
    search_volume: int | None = Field(None, description="Estimated monthly search volume")
    difficulty: float | None = Field(None, description="Keyword difficulty score (0-100)")
    relevance: float | None = Field(None, description="Relevance score (0-1)")
    suggestion_type: str | None = Field(
        None, description="How the keyword was found (seed, related, competitor)"
    )


class KeywordDifficulty(BaseModel):
    """Keyword difficulty assessment."""

    keyword: str = Field(..., description="The keyword")
    difficulty_score: float = Field(..., description="Difficulty score (0-100)")
    difficulty_label: str = Field(
        ..., description="Difficulty label (Easy, Medium, Hard, Very Hard)"
    )
    top_apps_count: int = Field(0, description="Number of competing apps in top results")
    top_apps: list[dict[str, Any]] = Field(
        default_factory=list, description="Top competing apps for this keyword"
    )


class AdvancedKeywordScore(BaseModel):
    """Multi-factor keyword scoring on a 0-100 scale.

    Difficulty combines title competition, competitor strength, install barrier,
    and publisher authority. Traffic combines search depth, top-app installs,
    an autocomplete-position heuristic, and keyword characteristics. Opportunity
    is traffic weighted by inverse difficulty. Ported from a standalone ASO
    scoring model that used the same google-play-scraper data this server
    already fetches.
    """

    keyword: str = Field(..., description="The keyword")
    country: str = Field("us", description="Country code")
    difficulty_score: float = Field(..., description="Difficulty score (0-100)")
    traffic_score: float = Field(..., description="Estimated traffic score (0-100)")
    opportunity_score: float = Field(
        ..., description="Opportunity score (0-100): traffic weighted by inverse difficulty"
    )
    difficulty_label: str = Field(..., description="Very Easy/Easy/Moderate/Hard/Very Hard")
    traffic_label: str = Field(..., description="Very Low/Low/Medium/High/Very High")
    traffic_estimate: str = Field(..., description="Rough monthly search volume band")
    recommendation: str = Field(..., description="Human-readable prioritization guidance")
    difficulty_breakdown: dict[str, Any] = Field(
        default_factory=dict, description="Per-component difficulty scores and raw signals"
    )
    traffic_breakdown: dict[str, Any] = Field(
        default_factory=dict, description="Per-component traffic scores and raw signals"
    )


class KeywordVolume(BaseModel):
    """Keyword search volume estimate."""

    keyword: str = Field(..., description="The keyword")
    estimated_volume: int = Field(0, description="Estimated monthly search volume")
    trend: str | None = Field(None, description="Volume trend (rising, stable, declining)")
    competition_level: str | None = Field(None, description="Competition level (low, medium, high)")


class AppKeywords(BaseModel):
    """Keywords extracted from an app listing."""

    package_name: str = Field(..., description="App package name")
    title_keywords: list[str] = Field(default_factory=list, description="Keywords from title")
    description_keywords: list[str] = Field(
        default_factory=list, description="Keywords from description"
    )
    all_keywords: list[KeywordResult] = Field(
        default_factory=list, description="All extracted keywords with scores"
    )


class CompetitorAnalysis(BaseModel):
    """Competitor keyword analysis."""

    target_package: str = Field(..., description="Target app package name")
    competitor_package: str = Field(..., description="Competitor app package name")
    competitor_name: str | None = Field(None, description="Competitor app name")
    shared_keywords: list[str] = Field(
        default_factory=list, description="Keywords both apps target"
    )
    unique_competitor_keywords: list[str] = Field(
        default_factory=list, description="Keywords only the competitor targets"
    )
    keyword_gap: list[KeywordResult] = Field(
        default_factory=list, description="Keyword opportunities (competitor has, target doesn't)"
    )


class KeywordRanking(BaseModel):
    """App ranking for a specific keyword."""

    keyword: str = Field(..., description="The keyword")
    package_name: str = Field(..., description="App package name")
    rank: int | None = Field(None, description="Current rank position (None if not ranked)")
    was_found: bool = Field(False, description="Whether the app was found in search results")
    total_results: int = Field(0, description="Total apps in search results")


class CategoryApp(BaseModel):
    """An app in a category ranking."""

    rank: int = Field(..., description="Rank position")
    app_id: str = Field(..., description="App package name/ID")
    title: str | None = Field(None, description="App title")
    developer: str | None = Field(None, description="Developer name")
    score: float | None = Field(None, description="Rating score")
    installs: str | None = Field(None, description="Install count range")
    free: bool = Field(True, description="Whether the app is free")


class ASOScore(BaseModel):
    """ASO score analysis of a store listing."""

    package_name: str = Field(..., description="App package name")
    overall_score: int = Field(0, description="Overall ASO score (0-100)")
    title_score: int = Field(0, description="Title optimization score (0-100)")
    description_score: int = Field(0, description="Description optimization score (0-100)")
    keyword_density: float = Field(0.0, description="Keyword density percentage")
    recommendations: list[str] = Field(
        default_factory=list, description="Improvement recommendations"
    )
    title_length: int = Field(0, description="Title character count")
    description_length: int = Field(0, description="Description character count")
    has_video: bool = Field(False, description="Whether listing has a video")


class OptimizedListing(BaseModel):
    """AI-generated optimized store listing."""

    package_name: str = Field(..., description="App package name")
    original_title: str | None = Field(None, description="Original title")
    suggested_title: str = Field(..., description="Optimized title suggestion")
    original_short_description: str | None = Field(None, description="Original short description")
    suggested_short_description: str = Field(
        ..., description="Optimized short description suggestion"
    )
    original_description: str | None = Field(None, description="Original full description")
    suggested_description: str = Field(..., description="Optimized full description suggestion")
    target_keywords: list[str] = Field(
        default_factory=list, description="Target keywords incorporated"
    )
    improvements: list[str] = Field(default_factory=list, description="List of improvements made")
