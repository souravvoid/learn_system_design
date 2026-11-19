"""URL shortener HTTP API: POST /api/v1/urls and GET /{short_code}."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.url_shortener.models import ShortenRequest, ShortenResponse
from src.url_shortener.service import AnalyticsService, UrlShortenerService

router = APIRouter()


def get_url_service(request: Request) -> UrlShortenerService:
    return cast(UrlShortenerService, request.app.state.services.url_shortener)


def get_analytics_service(request: Request) -> AnalyticsService:
    return cast(AnalyticsService, request.app.state.services.analytics)


@router.post(
    "/api/v1/urls",
    response_model=ShortenResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["url-shortener"],
    summary="Create a short URL (write path)",
)
async def shorten_url(
    payload: ShortenRequest,
    request: Request,
    service: UrlShortenerService = Depends(get_url_service),
) -> ShortenResponse:
    long_url = str(payload.long_url)
    short_code = await service.shorten(long_url)
    return ShortenResponse(
        short_code=short_code,
        short_url=f"{request.base_url}{short_code}",
        long_url=long_url,
    )


@router.get(
    "/{short_code}",
    tags=["url-shortener"],
    summary="Redirect to the original URL (read path)",
)
async def redirect(
    short_code: str,
    service: UrlShortenerService = Depends(get_url_service),
    analytics: AnalyticsService = Depends(get_analytics_service),
) -> None:
    long_url = await service.resolve(short_code)
    if long_url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Short URL not found")

    await analytics.record_click(short_code)
    raise HTTPException(
        status_code=status.HTTP_302_FOUND,
        headers={"Location": long_url},
        detail="Redirecting",
    )
