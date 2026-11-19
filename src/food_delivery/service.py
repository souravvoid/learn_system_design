"""Application service for the food delivery flows."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from src.food_delivery.delivery import DeliveryTracker
from src.food_delivery.models import (
    CartItem,
    CartItemRequest,
    CartView,
    DeliveryStatus,
    MenuItem,
    MenuItemCreate,
    Order,
    OrderItem,
    PaymentRequest,
    PaymentResponse,
    PaymentStatus,
    Restaurant,
    RestaurantCreate,
    RestaurantRow,
    User,
    UserLogin,
    UserRegistration,
)
from src.food_delivery.repository import (
    DuplicateEmailError,
    DuplicatePaymentError,
    FoodRepository,
    distance_km,
)
from src.shared.database import Database

PBKDF2_ITERATIONS = 100_000


class InvalidCredentialsError(Exception):
    pass


class UnknownUserError(Exception):
    pass


class UnknownRestaurantError(Exception):
    pass


class UnknownMenuItemError(Exception):
    pass


class EmptyCartError(Exception):
    pass


class MixedRestaurantCartError(Exception):
    pass


class OrderNotFoundError(Exception):
    pass


class FoodDeliveryService:
    def __init__(self, database: Database, tracker: DeliveryTracker) -> None:
        self._repository = FoodRepository(database)
        self._tracker = tracker

    async def register_user(self, payload: UserRegistration) -> User:
        salt = secrets.token_bytes(16)
        password_hash = hashlib.pbkdf2_hmac(
            "sha256", payload.password.encode(), salt, PBKDF2_ITERATIONS
        ).hex()
        row = await self._repository.create_user(payload, password_hash, salt.hex())
        return User(id=row.id, name=row.name, email=row.email)

    async def login(self, payload: UserLogin) -> User:
        row = await self._repository.get_user_by_email(payload.email)
        if row is None:
            raise InvalidCredentialsError(payload.email)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", payload.password.encode(), bytes.fromhex(row.salt), PBKDF2_ITERATIONS
        ).hex()
        if not hmac.compare_digest(candidate, row.password_hash):
            raise InvalidCredentialsError(payload.email)
        return User(id=row.id, name=row.name, email=row.email)

    async def create_restaurant(self, payload: RestaurantCreate) -> Restaurant:
        row = await self._repository.create_restaurant(payload)
        return Restaurant(
            id=row.id, name=row.name, latitude=row.latitude, longitude=row.longitude
        )

    async def list_nearby_restaurants(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_km: float | None = None,
    ) -> list[Restaurant]:
        rows = await self._repository.list_restaurants()
        if latitude is None or longitude is None or radius_km is None:
            return [self._to_restaurant(row) for row in rows]
        return [
            self._to_restaurant(row)
            for row in rows
            if distance_km(latitude, longitude, row.latitude, row.longitude) <= radius_km
        ]

    async def add_menu_item(self, restaurant_id: int, payload: MenuItemCreate) -> MenuItem:
        if await self._repository.get_restaurant(restaurant_id) is None:
            raise UnknownRestaurantError(restaurant_id)
        row = await self._repository.add_menu_item(restaurant_id, payload)
        return MenuItem(
            id=row.id, restaurant_id=row.restaurant_id, name=row.name, price=row.price
        )

    async def get_menu(self, restaurant_id: int) -> list[MenuItem]:
        if await self._repository.get_restaurant(restaurant_id) is None:
            raise UnknownRestaurantError(restaurant_id)
        rows = await self._repository.list_menu_items(restaurant_id)
        return [
            MenuItem(id=row.id, restaurant_id=row.restaurant_id, name=row.name, price=row.price)
            for row in rows
        ]

    async def add_to_cart(self, user_id: int, payload: CartItemRequest) -> CartView:
        if await self._repository.get_user(user_id) is None:
            raise UnknownUserError(user_id)
        if await self._repository.get_restaurant(payload.restaurant_id) is None:
            raise UnknownRestaurantError(payload.restaurant_id)
        item = await self._repository.get_menu_item(payload.menu_item_id)
        if item is None or item.restaurant_id != payload.restaurant_id:
            raise UnknownMenuItemError(payload.menu_item_id)
        await self._repository.add_cart_item(user_id, payload)
        return await self.get_cart(user_id)

    async def get_cart(self, user_id: int) -> CartView:
        rows = await self._repository.get_cart(user_id)
        items = [
            CartItem(
                menu_item_id=item.id,
                name=item.name,
                quantity=cart.quantity,
                unit_price=item.price,
            )
            for cart, item in rows
        ]
        return CartView(
            user_id=user_id,
            items=items,
            total_amount=round(sum(item.unit_price * item.quantity for item in items), 2),
        )

    async def place_order(self, user_id: int) -> Order:
        cart = await self.get_cart(user_id)
        if not cart.items:
            raise EmptyCartError(user_id)
        restaurant_ids = {row.restaurant_id for row, _ in await self._repository.get_cart(user_id)}
        if len(restaurant_ids) != 1:
            raise MixedRestaurantCartError(user_id)

        order = await self._repository.create_order(
            user_id=user_id,
            restaurant_id=restaurant_ids.pop(),
            items=cart.items,
            total_amount=cart.total_amount,
        )
        return await self.get_order(order.id)

    async def get_order(self, order_id: int) -> Order:
        row = await self._repository.get_order(order_id)
        if row is None:
            raise OrderNotFoundError(order_id)
        items = await self._repository.list_order_items(order_id)
        return Order(
            id=row.id,
            user_id=row.user_id,
            restaurant_id=row.restaurant_id,
            status=row.status,
            payment_status=row.payment_status,
            total_amount=row.total_amount,
            created_at=row.created_at,
            items=[
                OrderItem(
                    menu_item_id=item.menu_item_id,
                    name=item.name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                )
                for item in items
            ],
        )

    async def pay(self, order_id: int, payload: PaymentRequest) -> PaymentResponse:
        order = await self.get_order(order_id)
        if order.payment_status == PaymentStatus.PAID.value:
            raise DuplicatePaymentError(order_id)
        await self._repository.mark_paid(order_id, payload.method, order.total_amount)
        await self._tracker.start(order_id)
        return PaymentResponse(
            order_id=order_id, status=PaymentStatus.PAID, amount=order.total_amount
        )

    async def delivery_status(self, order_id: int) -> DeliveryStatus | None:
        return await self._tracker.current_status(order_id)

    @staticmethod
    def _to_restaurant(row: RestaurantRow) -> Restaurant:
        return Restaurant(
            id=row.id, name=row.name, latitude=row.latitude, longitude=row.longitude
        )
