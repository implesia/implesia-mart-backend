import uuid
from datetime import UTC, datetime, timedelta

from app.models.audit_event import AuditAction, AuditEvent
from app.models.category import Category
from app.models.order import Order
from app.models.product import Product, StockStatus
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole

SEED_CATEGORY_ID = uuid.UUID("00000000-0000-0000-0000-00000000fa51")


def seed_category() -> Category:
    """The legacy `fashion` root every integration product belongs to (re-seeded per test)."""
    return Category(id=SEED_CATEGORY_ID, slug="fashion", name="Fashion", sort_order=0)


def product(
    *,
    price: int = 1000,
    quantity: int | None = 1,
    status: str = StockStatus.AVAILABLE.value,
) -> Product:
    return Product(
        slug=f"pg-{uuid.uuid4().hex[:12]}",
        title="Integration product",
        category="fashion",
        category_id=SEED_CATEGORY_ID,
        price=price,
        quantity=quantity,
        status=status,
        published=True,
        content={},
    )


def order() -> Order:
    return Order(
        number=f"IM-{uuid.uuid4().hex[:8].upper()}",
        source="direct",
        status="new",
        payment_method="cod",
        customer_name="Rina Akter",
        phone="01700000000",
        district="ঢাকা",
        area="গুলশান",
        address="House 12, Road 4",
        delivery_zone="inside",
        subtotal=1000,
        shipping=70,
        total=1070,
    )


def user(email: str | None = None) -> User:
    return User(
        email=email or f"pg-{uuid.uuid4().hex[:12]}@implesia.test",
        full_name="Integration User",
        password_hash="not-a-real-hash",
        role=UserRole.VIEWER,
    )


def refresh_token(user_id: uuid.UUID) -> RefreshToken:
    return RefreshToken(
        user_id=user_id,
        family_id=uuid.uuid4(),
        jti_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )


def audit_event(actor_id: uuid.UUID) -> AuditEvent:
    return AuditEvent(
        actor_user_id=actor_id,
        action=AuditAction.ROLE_CHANGED.value,
        target_type="user",
        target_id=str(actor_id),
        event_metadata={"from": "viewer", "to": "editor"},
    )
