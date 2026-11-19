"""Notification enums, routing policy, ORM entities and API schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.database import Base


class NotificationType(str, Enum):
    ORDER_UPDATE = "order_update"
    ALERT = "alert"
    REMINDER = "reminder"


class Channel(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


class DeliveryStatus(str, Enum):
    QUEUED = "queued"
    RETRYING = "retrying"
    SENT = "sent"
    DEAD_LETTERED = "dead_lettered"


DEFAULT_CHANNELS: dict[NotificationType, tuple[Channel, ...]] = {
    NotificationType.ORDER_UPDATE: (Channel.PUSH,),
    NotificationType.ALERT: (Channel.SMS, Channel.PUSH),
    NotificationType.REMINDER: (Channel.EMAIL,),
}


class UserPreference(Base):
    __tablename__ = "notification_preferences"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    def allows(self, channel: Channel) -> bool:
        return {
            Channel.EMAIL: self.email_enabled,
            Channel.SMS: self.sms_enabled,
            Channel.PUSH: self.push_enabled,
        }[channel]


class NotificationRecord(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("idempotency_key", "channel", name="uq_notification_idempotency_channel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=DeliveryStatus.QUEUED.value, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PreferenceRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    email_enabled: bool = True
    sms_enabled: bool = True
    push_enabled: bool = True


class PreferenceResponse(BaseModel):
    user_id: str
    email_enabled: bool
    sms_enabled: bool
    push_enabled: bool


class NotifyRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=64)
    type: NotificationType
    message: str = Field(min_length=1)
    channels: list[Channel] | None = None


class ChannelDelivery(BaseModel):
    channel: Channel
    status: DeliveryStatus
    attempts: int


class NotificationResponse(BaseModel):
    idempotency_key: str
    user_id: str
    type: NotificationType
    deliveries: list[ChannelDelivery]
