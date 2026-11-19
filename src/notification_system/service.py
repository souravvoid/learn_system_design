"""Notification orchestrator, channel queues, retry worker and dead-letter handling."""

from __future__ import annotations

import asyncio
from typing import cast

from src.notification_system.channels import ChannelSender, ChannelSendError
from src.notification_system.models import (
    DEFAULT_CHANNELS,
    Channel,
    DeliveryStatus,
    NotificationResponse,
    NotificationType,
    NotifyRequest,
    PreferenceRequest,
    PreferenceResponse,
)
from src.notification_system.repository import NotificationRepository
from src.shared.database import Database
from src.shared.message_queue import MessageBroker

DEAD_LETTER_TOPIC = "notification.dead_letter"


def topic_for(channel: Channel) -> str:
    return f"notification.{channel.value}"


def exponential_backoff(attempt: int, base_delay: float, max_delay: float) -> float:
    """Delay before retry number `attempt` (1-based): base * 2^(attempt-1), capped."""
    if attempt < 1:
        raise ValueError("attempt must be >= 1")
    return min(max_delay, base_delay * (2 ** (attempt - 1)))


class UnknownUserError(Exception):
    """Raised when an event targets a user with no registered preferences."""


class NotificationService:
    """The orchestrator: filters by preference and publishes to channel queues."""

    def __init__(self, database: Database, broker: MessageBroker) -> None:
        self._repository = NotificationRepository(database)
        self._broker = broker

    async def register_preferences(self, payload: PreferenceRequest) -> PreferenceResponse:
        await self._repository.save_preferences(payload)
        return PreferenceResponse(**payload.model_dump())

    async def notify(self, request: NotifyRequest) -> NotificationResponse:
        preferences = await self._repository.get_preferences(request.user_id)
        if preferences is None:
            raise UnknownUserError(request.user_id)

        channels = request.channels or list(DEFAULT_CHANNELS[request.type])
        for channel in channels:
            if not preferences.allows(channel):
                continue
            record, created_now = await self._repository.create_delivery(
                idempotency_key=request.idempotency_key,
                user_id=request.user_id,
                notification_type=request.type,
                channel=channel,
                message=request.message,
            )
            if created_now:
                await self._broker.publish(topic_for(channel), {"delivery_id": record.id})

        return await self.status(request.idempotency_key) or self._empty_response(request)

    async def status(self, idempotency_key: str) -> NotificationResponse | None:
        records = await self._repository.find_by_key(idempotency_key)
        if not records:
            return None
        return NotificationResponse(
            idempotency_key=records[0].idempotency_key,
            user_id=records[0].user_id,
            type=NotificationType(records[0].type),
            deliveries=[
                {"channel": Channel(row.channel), "status": DeliveryStatus(row.status), "attempts": row.attempts}
                for row in records
            ],
        )

    @staticmethod
    def _empty_response(request: NotifyRequest) -> NotificationResponse:
        return NotificationResponse(
            idempotency_key=request.idempotency_key,
            user_id=request.user_id,
            type=request.type,
            deliveries=[],
        )


class NotificationWorker:
    """One consumer per channel topic with retries and a dead-letter topic."""

    def __init__(
        self,
        database: Database,
        broker: MessageBroker,
        senders: dict[Channel, ChannelSender],
        *,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 30.0,
    ) -> None:
        self._repository = NotificationRepository(database)
        self._broker = broker
        self._senders = senders
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._retry_tasks: set[asyncio.Task[None]] = set()

    async def run(self) -> None:
        consumers = [asyncio.create_task(self._consume(channel)) for channel in Channel]
        try:
            await asyncio.gather(*consumers)
        finally:
            for task in (*consumers, *tuple(self._retry_tasks)):
                task.cancel()
            await asyncio.gather(*consumers, *tuple(self._retry_tasks), return_exceptions=True)

    async def _consume(self, channel: Channel) -> None:
        async with self._broker.subscribe(topic_for(channel)) as messages:
            async for message in messages:
                await self.process(cast(int, message.body["delivery_id"]))

    async def process(self, delivery_id: int) -> None:
        record = await self._repository.get_delivery(delivery_id)
        if record is None or record.status in (DeliveryStatus.SENT.value, DeliveryStatus.DEAD_LETTERED.value):
            return

        channel = Channel(record.channel)
        sender = self._senders[channel]
        attempt = record.attempts + 1
        try:
            await sender.send(record.user_id, record.message)
        except ChannelSendError as exc:
            reason = str(exc)
            if attempt >= self._max_attempts:
                await self._repository.update_delivery(
                    delivery_id,
                    status=DeliveryStatus.DEAD_LETTERED,
                    attempts=attempt,
                    error=reason,
                )
                await self._broker.publish(DEAD_LETTER_TOPIC, {"delivery_id": delivery_id, "reason": reason})
                return

            await self._repository.update_delivery(
                delivery_id,
                status=DeliveryStatus.RETRYING,
                attempts=attempt,
                error=reason,
            )
            delay = exponential_backoff(attempt, self._base_delay, self._max_delay)
            task = asyncio.create_task(self._requeue(delivery_id, channel, delay))
            self._retry_tasks.add(task)
            task.add_done_callback(self._retry_tasks.discard)
            return

        await self._repository.update_delivery(
            delivery_id,
            status=DeliveryStatus.SENT,
            attempts=attempt,
            error=None,
        )

    async def _requeue(self, delivery_id: int, channel: Channel, delay: float) -> None:
        await asyncio.sleep(delay)
        await self._broker.publish(topic_for(channel), {"delivery_id": delivery_id})
