"""Food delivery enums, ORM rows and Pydantic API models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field
from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.database import Base


class OrderStatus(str, Enum):
    PLACED = "placed"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    PICKED_UP = "picked_up"
    ON_THE_WAY = "on_the_way"
    DELIVERED = "delivered"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"


class UserRow(Base):
    __tablename__ = "food_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    salt: Mapped[str] = mapped_column(Text, nullable=False)


class RestaurantRow(Base):
    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)


class MenuItemRow(Base):
    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    restaurant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("restaurants.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)


class CartRow(Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("user_id", "menu_item_id", name="uq_cart_user_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("food_users.id"), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    menu_item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)


class OrderRow(Base):
    __tablename__ = "food_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("food_users.id"), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=OrderStatus.PLACED.value, nullable=False)
    payment_status: Mapped[str] = mapped_column(
        String(16), default=PaymentStatus.PENDING.value, nullable=False
    )
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class OrderItemRow(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("food_orders.id"), nullable=False)
    menu_item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)


class PaymentRow(Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("order_id", name="uq_payment_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("food_orders.id"), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class DeliveryEventRow(Base):
    __tablename__ = "delivery_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("food_orders.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class UserRegistration(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8)


class UserLogin(BaseModel):
    email: str
    password: str


class User(BaseModel):
    id: int
    name: str
    email: str


class RestaurantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    latitude: float
    longitude: float


class Restaurant(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float


class MenuItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    price: float = Field(gt=0)


class MenuItem(BaseModel):
    id: int
    restaurant_id: int
    name: str
    price: float


class CartItemRequest(BaseModel):
    restaurant_id: int
    menu_item_id: int
    quantity: int = Field(gt=0)


class CartItem(BaseModel):
    menu_item_id: int
    name: str
    quantity: int
    unit_price: float


class CartView(BaseModel):
    user_id: int
    items: list[CartItem]
    total_amount: float


class OrderItem(BaseModel):
    menu_item_id: int
    name: str
    quantity: int
    unit_price: float


class Order(BaseModel):
    id: int
    user_id: int
    restaurant_id: int
    status: OrderStatus
    payment_status: PaymentStatus
    total_amount: float
    created_at: datetime
    items: list[OrderItem]


class PaymentRequest(BaseModel):
    method: str = Field(min_length=1, max_length=32)


class PaymentResponse(BaseModel):
    order_id: int
    status: PaymentStatus
    amount: float


class DeliveryStatus(BaseModel):
    order_id: int
    status: OrderStatus
    updated_at: datetime
    note: str | None = None
