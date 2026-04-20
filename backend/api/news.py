"""/news — recent market-moving headlines from RSS + CryptoPanic.

Backed by ``core.news_monitor.NewsMonitor`` which polls feeds in a
background thread and tags each headline with an Impact level
(LOW / MEDIUM / HIGH / CRITICAL) and a sentiment
(bullish / bearish / neutral). The UI's News dashboard panel polls
this every 30-60s.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.news_monitor import Impact, NewsMonitor

router = APIRouter(tags=["news"])


def get_news_monitor() -> NewsMonitor:
    raise HTTPException(status_code=503, detail="NewsMonitor not configured")


MonitorDep = Annotated[NewsMonitor, Depends(get_news_monitor)]


class NewsItemOut(BaseModel):
    uid: str
    headline: str
    source: str
    url: str
    published: datetime
    impact: str
    sentiment: str
    matched_keywords: list[str] = Field(default_factory=list)


class NewsListResponse(BaseModel):
    items: list[NewsItemOut] = Field(default_factory=list)
    sentiment_bias: str


_IMPACT_NAME = {
    Impact.LOW: "LOW",
    Impact.MEDIUM: "MEDIUM",
    Impact.HIGH: "HIGH",
    Impact.CRITICAL: "CRITICAL",
}


@router.get("/news/latest", response_model=NewsListResponse)
def latest(
    monitor: MonitorDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    min_impact: str = "LOW",
) -> NewsListResponse:
    try:
        floor = Impact[min_impact.upper()]
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"bad impact: {min_impact}") from exc
    items = monitor.get_items(limit=limit, min_impact=floor)
    return NewsListResponse(
        items=[
            NewsItemOut(
                uid=item.uid,
                headline=item.headline,
                source=item.source,
                url=item.url,
                published=item.published,
                impact=_IMPACT_NAME.get(item.impact, "LOW"),
                sentiment=item.sentiment,
                matched_keywords=list(item.matched_keywords or []),
            )
            for item in items
        ],
        sentiment_bias=monitor.get_sentiment_bias(),
    )


@router.get("/news/critical", response_model=NewsListResponse)
def critical(
    monitor: MonitorDep,
    since_minutes: Annotated[int, Query(ge=1, le=1440)] = 60,
) -> NewsListResponse:
    """Just the CRITICAL-impact items from the last N minutes. The UI
    shows a red banner when this returns anything."""
    items = monitor.get_critical_items(since_minutes=since_minutes)
    return NewsListResponse(
        items=[
            NewsItemOut(
                uid=item.uid,
                headline=item.headline,
                source=item.source,
                url=item.url,
                published=item.published,
                impact=_IMPACT_NAME.get(item.impact, "CRITICAL"),
                sentiment=item.sentiment,
                matched_keywords=list(item.matched_keywords or []),
            )
            for item in items
        ],
        sentiment_bias=monitor.get_sentiment_bias(),
    )
