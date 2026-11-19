"""Persistence for preferences, notification history and delivery status."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.shared.database import Database
from src.notification_system.models import (
    Channel,
    DeliveryStatus,
    NotificationRecord,
    NotificationType,
    PreferenceRequest,
    UserPreference,
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class NotificationRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def save_preferences(self, payload: PreferenceRequest) -> None:
        async with self._database.session() as session:
            row = await session.get(UserPreference, payload.user_id)
            if row is None:
                row = UserPreference(user_id=payload.user_id, created_at=_now())
                session.add(row)
            row.email_enabled = payload.email_enabled
            row.sms_enabled = payload.sms_enabled
            row.push_enabled = payload.push_enabled
            await session.commit()

    async def get_preferences(self, user_id: str) -> UserPreference | None:
        async with self._database.session() as session:
            return await session.get(UserPreference, user_id)

    async def create_delivery(
        self,
        *,
        idempotency_key: str,
        user_id: str,
        notification_type: NotificationType,
        channel: Channel,
        message: str,
    ) -> tuple[NotificationRecord, bool]:
        """Insert one channel delivery. Returns (row, created_now).

        The unique (idempotency_key, channel) constraint makes redelivery safe.
        """
        now = _now()
        async with self._database.session() as session:
            record = NotificationRecord(
                idempotency_key=idempotency_key,
                user_id=user_id,
                type=notification_type.value,
                channel=channel.value,
                message=message,
                status=DeliveryStatus.QUEUED.value,
                attempts=0,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await self.find_delivery(idempotency_key, channel)
                if existing is None:
                    raise
                return existing, False
            return record, True

    async def find_delivery(self, idempotency_key: str, channel: Channel) -> NotificationRecord | None:
        async with self._database.session() as session:
            result = await session.execute(
                select(NotificationRecord).where(
                    NotificationRecord.idempotency_key == idempotency_key,
                    NotificationRecord.channel == channel.value,
                )
            )
            return result.scalar_one_or_none()

    async def get_delivery(self, delivery_id: int) -> NotificationRecord | None:
        async with self._database.session() as session:
            return await session.get(NotificationRecord, delivery_id)

    async def find_by_key(self, idempotency_key: str) -> list[NotificationRecord]:
        async with self._database.session() as session:
            result = await session.execute(
                select(NotificationRecord)
                .where(NotificationRecord.idempotency_key == idempotency_key)
                .order_by(NotificationRecord.id)
            )
            return list(result.scalars().all())

    async def update_delivery(
        self,
        delivery_id: int,
        *,
        status: DeliveryStatus,
        attempts: int,
        error: str | None,
    ) -> None:
        async with self._database.session() as session:
            record = await session.get(NotificationRecord, delivery_id)
            if record is None:
                return
            record.status = status.value
            record.attempts = attempts
            record.last_error = error
            record.updated_at = _now()
            await session.commit()
