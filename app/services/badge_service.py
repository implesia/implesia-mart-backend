"""Product badges: the admin-managed list, and which badges each product shows.

`products.badge` (the old single New / Best Seller / Limited value) is kept as a derived
column: catalog ranking, the "new" view and the `badge` filter still read it. It follows the
built-in badges a product carries, so those features keep working unchanged.
"""

import re
import uuid
from collections.abc import Iterable, Sequence

from slugify import slugify
from sqlalchemy import delete, func, select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.audit_event import AuditAction
from app.models.badge import SYSTEM_BADGES, Badge, BadgeTone, ProductBadgeLink
from app.models.product import Product, ProductBadge
from app.models.user import User
from app.schemas.badge import (
    MAX_PER_PRODUCT,
    BadgeAdminList,
    BadgeAdminRead,
    BadgeDeleteImpact,
    BadgeDeleteRequest,
    BadgeDeleteResult,
    BadgeMergeTarget,
    BadgeRef,
    BadgeSampleProduct,
    BadgeUpdate,
    BadgeWrite,
    PublicBadge,
)
from app.services import audit_service

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SLUG_MAX = 48
# Highest first: the same order the catalog ranks them in.
_LEGACY_PRIORITY: tuple[str, ...] = tuple(SYSTEM_BADGES)
_LEGACY_SLUG = {name: slug for slug, name in SYSTEM_BADGES.items()}


def _base_slug(name: str) -> str:
    raw = slugify(name, max_length=_SLUG_MAX - 4, lowercase=True)
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    return raw if raw and _SLUG.fullmatch(raw) else "badge"


async def _allocate_slug(db: AsyncSession, name: str) -> str:
    base = _base_slug(name)
    candidate = base
    for number in range(2, 100):
        taken = await db.scalar(select(Badge.id).where(Badge.slug == candidate).limit(1))
        if taken is None:
            return candidate
        candidate = f"{base}-{number}"
    return f"badge-{uuid.uuid4().hex[:10]}"


async def _name_taken(db: AsyncSession, name: str, *, exclude: uuid.UUID | None = None) -> bool:
    stmt = select(Badge.id).where(func.lower(Badge.name) == name.lower())
    if exclude is not None:
        stmt = stmt.where(Badge.id != exclude)
    return await db.scalar(stmt.limit(1)) is not None


def ref(badge: Badge) -> BadgeRef:
    return BadgeRef(
        id=badge.id,
        name=badge.name,
        slug=badge.slug,
        tone=BadgeTone(badge.tone),
        is_active=badge.is_active,
    )


def public(badges: Iterable[Badge]) -> list[PublicBadge]:
    return [
        PublicBadge(name=badge.name, slug=badge.slug, tone=BadgeTone(badge.tone))
        for badge in badges
        if badge.is_active
    ]


def _admin(badge: Badge, product_count: int) -> BadgeAdminRead:
    return BadgeAdminRead(
        **ref(badge).model_dump(),
        is_system=badge.is_system,
        product_count=product_count,
        created_at=badge.created_at,
        updated_at=badge.updated_at,
    )


async def _usage(
    db: AsyncSession, badge_ids: Sequence[uuid.UUID] | None = None
) -> dict[uuid.UUID, int]:
    stmt = select(ProductBadgeLink.badge_id, func.count()).group_by(ProductBadgeLink.badge_id)
    if badge_ids is not None:
        stmt = stmt.where(ProductBadgeLink.badge_id.in_(badge_ids))
    return {badge_id: int(count) for badge_id, count in (await db.execute(stmt)).all()}


# ------------------------------------------------------------------ admin CRUD


async def admin_list(db: AsyncSession) -> BadgeAdminList:
    rows = (
        await db.scalars(
            select(Badge).order_by(Badge.is_system.desc(), Badge.created_at, Badge.name, Badge.id)
        )
    ).all()
    usage = await _usage(db)
    return BadgeAdminList(items=[_admin(row, usage.get(row.id, 0)) for row in rows])


async def get(db: AsyncSession, badge_id: uuid.UUID) -> Badge:
    badge = await db.get(Badge, badge_id)
    if badge is None:
        raise NotFoundError("Badge not found")
    return badge


async def admin_read(db: AsyncSession, badge: Badge) -> BadgeAdminRead:
    usage = await _usage(db, [badge.id])
    return _admin(badge, usage.get(badge.id, 0))


async def create(db: AsyncSession, payload: BadgeWrite) -> Badge:
    if await _name_taken(db, payload.name):
        raise ConflictError("A badge with this name already exists")
    badge = Badge(
        name=payload.name,
        slug=await _allocate_slug(db, payload.name),
        tone=payload.tone.value,
        is_active=payload.is_active,
        is_system=False,
    )
    db.add(badge)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("A badge with this name already exists") from exc
    await db.refresh(badge)
    return badge


async def update(db: AsyncSession, badge: Badge, payload: BadgeUpdate) -> Badge:
    # The slug never changes: it is the badge's stable id for the storefront and filters.
    if payload.name is not None and payload.name != badge.name:
        if await _name_taken(db, payload.name, exclude=badge.id):
            raise ConflictError("A badge with this name already exists")
        badge.name = payload.name
    if payload.tone is not None:
        badge.tone = payload.tone.value
    if payload.is_active is not None:
        badge.is_active = payload.is_active
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("A badge with this name already exists") from exc
    await db.refresh(badge)
    return badge


async def delete_impact(db: AsyncSession, badge_id: uuid.UUID) -> BadgeDeleteImpact:
    badge = await get(db, badge_id)
    linked_count = (await _usage(db, [badge.id])).get(badge.id, 0)
    sample_rows = (
        await db.execute(
            select(Product.id, Product.title)
            .join(ProductBadgeLink, ProductBadgeLink.product_id == Product.id)
            .where(ProductBadgeLink.badge_id == badge.id)
            .order_by(Product.title.asc(), Product.id.asc())
            .limit(10)
        )
    ).all()
    target_rows = (
        await db.execute(
            select(Badge.id, Badge.name, Badge.slug)
            .where(Badge.id != badge.id)
            .order_by(Badge.is_system.desc(), Badge.name.asc(), Badge.id.asc())
        )
    ).all()
    return BadgeDeleteImpact(
        badge_name=badge.name,
        is_system=badge.is_system,
        linked_products_count=linked_count,
        sample_products=[BadgeSampleProduct(id=row[0], title=str(row[1])) for row in sample_rows],
        available_merge_targets=[
            BadgeMergeTarget(id=row[0], name=str(row[1]), slug=str(row[2])) for row in target_rows
        ],
    )


async def delete_badge(
    db: AsyncSession,
    badge: Badge,
    *,
    payload: BadgeDeleteRequest | None = None,
    actor: User | None = None,
) -> BadgeDeleteResult:
    """Delete a custom badge by unlinking it or merging its products into another badge."""
    if badge.is_system:
        raise ConflictError("Built-in badges cannot be deleted. Switch the badge off instead.")
    req = payload or BadgeDeleteRequest()
    affected_ids = list(
        (
            await db.scalars(
                select(ProductBadgeLink.product_id).where(ProductBadgeLink.badge_id == badge.id)
            )
        ).all()
    )
    target_id: uuid.UUID | None = None
    target_name: str | None = None

    if req.mode == "merge":
        if req.target_badge_id is None:
            raise UnprocessableError("target_badge_id is required when mode is merge")
        if req.target_badge_id == badge.id:
            raise UnprocessableError("Cannot merge a badge into itself")
        target = await db.get(Badge, req.target_badge_id)
        if target is None:
            raise NotFoundError("Target badge not found")
        target_id = target.id
        target_name = target.name
        if affected_ids:
            already_has = set(
                (
                    await db.scalars(
                        select(ProductBadgeLink.product_id).where(
                            ProductBadgeLink.badge_id == target.id,
                            ProductBadgeLink.product_id.in_(affected_ids),
                        )
                    )
                ).all()
            )
            if already_has:
                await db.execute(
                    delete(ProductBadgeLink).where(
                        ProductBadgeLink.badge_id == badge.id,
                        ProductBadgeLink.product_id.in_(already_has),
                    )
                )
            to_move = [pid for pid in affected_ids if pid not in already_has]
            if to_move:
                await db.execute(
                    sa_update(ProductBadgeLink)
                    .where(
                        ProductBadgeLink.badge_id == badge.id,
                        ProductBadgeLink.product_id.in_(to_move),
                    )
                    .values(badge_id=target.id)
                )
    else:
        if affected_ids:
            await db.execute(delete(ProductBadgeLink).where(ProductBadgeLink.badge_id == badge.id))

    if affected_ids:
        await db.flush()
        grouped = await for_products(db, affected_ids)
        for pid in affected_ids:
            await db.execute(
                sa_update(Product)
                .where(Product.id == pid)
                .values(badge=legacy_value(grouped.get(pid, [])))
            )

    badge_id = badge.id
    badge_name = badge.name
    await db.delete(badge)
    await audit_service.record(
        db,
        actor_id=actor.id if actor is not None else None,
        action=AuditAction.BADGE_DELETED.value,
        target_type="badge",
        target_id=badge_id,
        metadata={
            "badge_name": badge_name,
            "mode": req.mode,
            "affected_products_count": len(affected_ids),
            "target_badge_id": str(target_id) if target_id else None,
            "target_badge_name": target_name,
        },
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            "Could not delete badge because its links changed concurrently."
        ) from exc
    return BadgeDeleteResult(
        message="Badge deleted",
        deleted_badge_id=badge_id,
        deleted_badge_name=badge_name,
        mode=req.mode,
        affected_products_count=len(affected_ids),
        target_badge_id=target_id,
    )


# ------------------------------------------------------------------ product links


async def resolve(db: AsyncSession, badge_ids: Sequence[uuid.UUID]) -> list[Badge]:
    """The badges for these ids, de-duplicated, in the order given. Unknown ids are a 422."""
    ordered = list(dict.fromkeys(badge_ids))
    if len(ordered) > MAX_PER_PRODUCT:
        raise UnprocessableError(f"A product can have at most {MAX_PER_PRODUCT} badges")
    if not ordered:
        return []
    found = {row.id: row for row in (await db.scalars(select(Badge).where(Badge.id.in_(ordered))))}
    missing = [str(item) for item in ordered if item not in found]
    if missing:
        raise UnprocessableError("One or more badges no longer exist", {"badge_ids": missing})
    return [found[item] for item in ordered]


def legacy_value(badges: Iterable[Badge]) -> str | None:
    """The `products.badge` value these badges imply (highest-ranked built-in one)."""
    slugs = {badge.slug for badge in badges if badge.is_system}
    for slug in _LEGACY_PRIORITY:
        if slug in slugs:
            return ProductBadge(SYSTEM_BADGES[slug]).value
    return None


async def replace_links(db: AsyncSession, product_id: uuid.UUID, badges: Sequence[Badge]) -> None:
    await db.execute(delete(ProductBadgeLink).where(ProductBadgeLink.product_id == product_id))
    for index, badge in enumerate(badges):
        db.add(ProductBadgeLink(product_id=product_id, badge_id=badge.id, sort_order=index))


async def apply_legacy(db: AsyncSession, product_id: uuid.UUID, value: str | None) -> None:
    """An old client set only `badge`: swap the built-in link, keep the custom ones."""
    current = await for_products(db, [product_id])
    kept = [badge for badge in current.get(product_id, []) if not badge.is_system]
    if value is not None:
        system = await db.scalar(select(Badge).where(Badge.slug == _LEGACY_SLUG[value]))
        if system is not None:
            kept.insert(0, system)
    await replace_links(db, product_id, kept[:MAX_PER_PRODUCT])


async def for_products(
    db: AsyncSession, product_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[Badge]]:
    """Every product's badges in one query (no N+1), in the admin's chosen order."""
    ids = list(dict.fromkeys(product_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(ProductBadgeLink.product_id, Badge)
        .join(Badge, Badge.id == ProductBadgeLink.badge_id)
        .where(ProductBadgeLink.product_id.in_(ids))
        .order_by(ProductBadgeLink.product_id, ProductBadgeLink.sort_order, Badge.name)
    )
    grouped: dict[uuid.UUID, list[Badge]] = {}
    for product_id, badge in rows.all():
        grouped.setdefault(product_id, []).append(badge)
    return grouped


async def unlink_product(db: AsyncSession, product_id: uuid.UUID) -> None:
    await db.execute(delete(ProductBadgeLink).where(ProductBadgeLink.product_id == product_id))
