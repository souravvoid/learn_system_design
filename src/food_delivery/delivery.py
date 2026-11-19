"""Simulated delivery lifecycle with in-memory pub/sub for SSE consumers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections import defaultdict
from contextlib import asynccontextmanager

from src.food_delivery.models import DeliveryStatus, OrderStatus
from src.food_delivery.repository import FoodRepository
from src.shared.database import Database

STATUS_FLOW: tuple[tuple[OrderStatus, str], ...] = (
    (OrderStatus.CONFIRMED, "Restaurant accepted the order"),
    (OrderStatus.PREPARING, "Food is being prepared"),
    (OrderStatus.PICKED_UP, "Rider picked up the order"),
    (OrderStatus.ON_THE_WAY, "Rider is on the way"),
    (OrderStatus.DELIVERED, "Order delivered"),
)


class DeliverySubscription:
    def __init__(self, tracker: DeliveryTracker, order_id: int) -> None:
        self._tracker = tracker
        self.order_id = order_id
        self._queue: asyncio.Queue[DeliveryStatus] = asyncio.Queue()

    async def __aenter__(self) -> DeliverySubscription:
        self._tracker._subscribers[self.order_id].add(self)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self._tracker._subscribers[self.order_id].discard(self)

    def __aiter__(self) -> AsyncIterator[DeliveryStatus]:
        return self

    async def __anext__(self) -> DeliveryStatus:
        return await self._queue.get()

    def put(self, status: DeliveryStatus) -> None:
        self._queue.put_nowait(status)


class DeliveryTracker:
    """Runs one background asyncio task per paid order."""

    def __init__(self, database: Database, step_delay: float = 0.05) -> None:
        self._repository = FoodRepository(database)
        self._step_delay = step_delay
        self._subscribers: dict[int, set[DeliverySubscription]] = defaultdict(set)
        self._tasks: dict[int, asyncio.Task[None]] = {}

    @asynccontextmanager
    async def subscribe(self, order_id: int) -> AsyncIterator[DeliverySubscription]:
        async with DeliverySubscription(self, order_id) as subscription:
            yield subscription

    async def current_status(self, order_id: int) -> DeliveryStatus | None:
        event = await self._repository.latest_delivery_status(order_id)
        if event is None:
            return None
        return DeliveryStatus(
            order_id=order_id,
            status=OrderStatus(event.status),
            updated_at=event.created_at,
            note=event.note,
        )

    async def start(self, order_id: int) -> None:
        existing = self._tasks.get(order_id)
        if existing is not None and not existing.done():
            return
        self._tasks[order_id] = asyncio.create_task(self._run(order_id))

    async def _run(self, order_id: int) -> None:
        for status, note in STATUS_FLOW:
            await asyncio.sleep(self._step_delay)
            event = await self._repository.update_delivery_status(order_id, status, note)
            update = DeliveryStatus(
                order_id=order_id,
                status=status,
                updated_at=event.created_at,
                note=note,
            )
            for subscriber in tuple(self._subscribers.get(order_id, ())):
                subscriber.put(update)

    async def stop_all(self) -> None:
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
