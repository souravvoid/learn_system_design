"""Async in-memory message broker used to simulate Kafka / Redis Streams topics."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4


@dataclass(frozen=True)
class Message:
    id: str = field(default_factory=lambda: uuid4().hex)
    topic: str = ""
    body: dict[str, Any] = field(default_factory=dict)


class Subscription:
    """A single consumer's queue for one topic."""

    def __init__(self, broker: InMemoryMessageBroker, topic: str) -> None:
        self._broker = broker
        self.topic = topic
        self._queue: asyncio.Queue[Message] = asyncio.Queue()

    async def __aenter__(self) -> Subscription:
        self._broker._subscribers[self.topic].add(self)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self._broker._subscribers[self.topic].discard(self)

    def __aiter__(self) -> AsyncIterator[Message]:
        return self

    async def __anext__(self) -> Message:
        return await self._queue.get()

    def put(self, message: Message) -> None:
        self._queue.put_nowait(message)

    @property
    def pending(self) -> int:
        return self._queue.qsize()


class MessageBroker(Protocol):
    async def publish(self, topic: str, body: dict[str, Any]) -> Message: ...

    def subscribe(self, topic: str) -> Subscription: ...


class InMemoryMessageBroker:
    """Fan-out broker: every subscriber of a topic receives every message."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[Subscription]] = defaultdict(set)
        self.published: list[Message] = []

    async def publish(self, topic: str, body: dict[str, Any]) -> Message:
        message = Message(topic=topic, body=dict(body))
        self.published.append(message)
        for subscriber in tuple(self._subscribers.get(topic, ())):
            subscriber.put(message)
        return message

    def subscribe(self, topic: str) -> Subscription:
        return Subscription(self, topic)

    def pending(self, topic: str) -> int:
        return sum(subscriber.pending for subscriber in self._subscribers.get(topic, ()))
