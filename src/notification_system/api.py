"""Notification HTTP API (prefixed with /api/v1/notifications)."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.notification_system.models import (
    NotificationResponse,
    NotifyRequest,
    PreferenceRequest,
    PreferenceResponse,
)
from src.notification_system.service import NotificationService, UnknownUserError

router = APIRouter()


def get_notification_service(request: Request) -> NotificationService:
    return cast(NotificationService, request.app.state.services.notification)


@router.post(
    "/users",
    response_model=PreferenceResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["notifications"],
    summary="Register a user's notification preferences",
)
async def register_preferences(
    payload: PreferenceRequest,
    service: NotificationService = Depends(get_notification_service),
) -> PreferenceResponse:
    return await service.register_preferences(payload)


@router.post(
    "/events",
    response_model=NotificationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["notifications"],
    summary="Accept an event and fan it out to eligible channel queues",
)
async def notify(
    payload: NotifyRequest,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    try:
        return await service.notify(payload)
    except UnknownUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No preferences registered for user {exc}",
        ) from exc


@router.get(
    "/events/{idempotency_key}",
    response_model=NotificationResponse,
    tags=["notifications"],
    summary="Read delivery status for an event",
)
async def notification_status(
    idempotency_key: str,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    response = await service.status(idempotency_key)
    if response is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return response
