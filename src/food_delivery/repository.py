"""SQLAlchemy persistence for users, restaurants, carts, orders and delivery events."""

from __future__ import annotations

from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from src.food_delivery.models import (
    CartItem,
    CartItemRequest,
    CartRow,
    DeliveryEventRow,
    MenuItemCreate,
    MenuItemRow,
    OrderItemRow,
    OrderRow,
    OrderStatus,
    PaymentRow,
    PaymentStatus,
    RestaurantCreate,
    RestaurantRow,
    UserRegistration,
    UserRow,
)
from src.shared.database import Database

EARTH_RADIUS_KM = 6371.0


class DuplicateEmailError(Exception):
    pass


class DuplicatePaymentError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine great-circle distance (local stand-in for PostGIS indexing)."""
    phi1, phi2 = radians(lat1), radians(lat2)
    delta_phi = radians(lat2 - lat1)
    delta_lambda = radians(lon2 - lon1)
    a = sin(delta_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(delta_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


class FoodRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create_user(self, payload: UserRegistration, password_hash: str, salt: str) -> UserRow:
        async with self._database.session() as session:
            row = UserRow(
                name=payload.name,
                email=payload.email.lower(),
                password_hash=password_hash,
                salt=salt,
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                raise DuplicateEmailError(payload.email) from exc
            return row

    async def get_user_by_email(self, email: str) -> UserRow | None:
        async with self._database.session() as session:
            result = await session.execute(select(UserRow).where(UserRow.email == email.lower()))
            return result.scalar_one_or_none()

    async def get_user(self, user_id: int) -> UserRow | None:
        async with self._database.session() as session:
            return await session.get(UserRow, user_id)

    async def create_restaurant(self, payload: RestaurantCreate) -> RestaurantRow:
        async with self._database.session() as session:
            row = RestaurantRow(**payload.model_dump())
            session.add(row)
            await session.commit()
            return row

    async def list_restaurants(self) -> list[RestaurantRow]:
        async with self._database.session() as session:
            result = await session.execute(select(RestaurantRow).order_by(RestaurantRow.id))
            return list(result.scalars().all())

    async def get_restaurant(self, restaurant_id: int) -> RestaurantRow | None:
        async with self._database.session() as session:
            return await session.get(RestaurantRow, restaurant_id)

    async def add_menu_item(self, restaurant_id: int, payload: MenuItemCreate) -> MenuItemRow:
        async with self._database.session() as session:
            row = MenuItemRow(restaurant_id=restaurant_id, **payload.model_dump())
            session.add(row)
            await session.commit()
            return row

    async def list_menu_items(self, restaurant_id: int) -> list[MenuItemRow]:
        async with self._database.session() as session:
            result = await session.execute(
                select(MenuItemRow).where(MenuItemRow.restaurant_id == restaurant_id).order_by(MenuItemRow.id)
            )
            return list(result.scalars().all())

    async def get_menu_item(self, menu_item_id: int) -> MenuItemRow | None:
        async with self._database.session() as session:
            return await session.get(MenuItemRow, menu_item_id)

    async def add_cart_item(self, user_id: int, payload: CartItemRequest) -> None:
        async with self._database.session() as session:
            result = await session.execute(
                select(CartRow).where(
                    CartRow.user_id == user_id,
                    CartRow.menu_item_id == payload.menu_item_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = CartRow(
                    user_id=user_id,
                    restaurant_id=payload.restaurant_id,
                    menu_item_id=payload.menu_item_id,
                    quantity=payload.quantity,
                )
                session.add(row)
            else:
                row.restaurant_id = payload.restaurant_id
                row.quantity = payload.quantity
            await session.commit()

    async def get_cart(self, user_id: int) -> list[tuple[CartRow, MenuItemRow]]:
        async with self._database.session() as session:
            result = await session.execute(
                select(CartRow, MenuItemRow)
                .join(MenuItemRow, CartRow.menu_item_id == MenuItemRow.id)
                .where(CartRow.user_id == user_id)
                .order_by(CartRow.id)
            )
            return [(cart, item) for cart, item in result.all()]

    async def create_order(
        self,
        user_id: int,
        restaurant_id: int,
        items: list[CartItem],
        total_amount: float,
    ) -> OrderRow:
        async with self._database.session() as session:
            order = OrderRow(
                user_id=user_id,
                restaurant_id=restaurant_id,
                total_amount=total_amount,
                status=OrderStatus.PLACED.value,
                payment_status=PaymentStatus.PENDING.value,
                created_at=_now(),
            )
            session.add(order)
            await session.flush()
            for item in items:
                session.add(
                    OrderItemRow(
                        order_id=order.id,
                        menu_item_id=item.menu_item_id,
                        name=item.name,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                    )
                )
            await session.execute(delete(CartRow).where(CartRow.user_id == user_id))
            await session.commit()
            return order

    async def get_order(self, order_id: int) -> OrderRow | None:
        async with self._database.session() as session:
            return await session.get(OrderRow, order_id)

    async def list_order_items(self, order_id: int) -> list[OrderItemRow]:
        async with self._database.session() as session:
            result = await session.execute(
                select(OrderItemRow).where(OrderItemRow.order_id == order_id).order_by(OrderItemRow.id)
            )
            return list(result.scalars().all())

    async def mark_paid(self, order_id: int, method: str, amount: float) -> None:
        async with self._database.session() as session:
            existing = await session.execute(select(PaymentRow).where(PaymentRow.order_id == order_id))
            if existing.scalar_one_or_none() is not None:
                raise DuplicatePaymentError(order_id)
            session.add(
                PaymentRow(
                    order_id=order_id,
                    method=method,
                    amount=amount,
                    status=PaymentStatus.PAID.value,
                    created_at=_now(),
                )
            )
            order = await session.get(OrderRow, order_id)
            if order is not None:
                order.payment_status = PaymentStatus.PAID.value
            try:
                await session.commit()
            except IntegrityError as exc:
                raise DuplicatePaymentError(order_id) from exc

    async def update_delivery_status(
        self, order_id: int, status: OrderStatus, note: str | None = None
    ) -> DeliveryEventRow:
        async with self._database.session() as session:
            order = await session.get(OrderRow, order_id)
            if order is not None:
                order.status = status.value
            event = DeliveryEventRow(order_id=order_id, status=status.value, note=note, created_at=_now())
            session.add(event)
            await session.commit()
            return event

    async def latest_delivery_status(self, order_id: int) -> DeliveryEventRow | None:
        async with self._database.session() as session:
            result = await session.execute(
                select(DeliveryEventRow)
                .where(DeliveryEventRow.order_id == order_id)
                .order_by(DeliveryEventRow.id.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()
