"""Mock channel providers and the send contract used by workers."""

from __future__ import annotations

from typing import Protocol

from src.notification_system.models import Channel


class ChannelSendError(Exception):
    """A provider call failed and the delivery should be retried."""


class ChannelSender(Protocol):
    channel: Channel

    async def send(self, user_id: str, message: str) -> None: ...


class MockChannelSender:
    """In-process stand-in for an email/SMS/push provider.

    `fail_on_attempts` makes failures deterministic for the retry tests.
    """

    def __init__(self, channel: Channel, fail_on_attempts: set[int] | None = None) -> None:
        self.channel = channel
        self._fail_on_attempts = fail_on_attempts or set()
        self.attempts = 0
        self.sent: list[tuple[str, str]] = []

    async def send(self, user_id: str, message: str) -> None:
        self.attempts += 1
        if self.attempts in self._fail_on_attempts:
            raise ChannelSendError(f"{self.channel.value} provider temporarily unavailable")
        self.sent.append((user_id, message))
