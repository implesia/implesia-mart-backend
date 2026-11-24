import re
import time
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    UnprocessableError,
)
from app.models.audit_event import AuditAction
from app.models.role import Role
from app.models.role_permission import RolePermission
from app.models.user import STAFF_ROLES, User, UserRole
from app.schemas.user import (
    AccessLevel,
    ModuleDefinition,
    RoleCreate,
    RoleDefinition,
    RoleDeleteImpact,
    RoleModuleAccess,
    RolePermissionUpdateItem,
    RoleRead,
    RolesMatrixResponse,
    RoleUpdate,
)
from app.services import audit_service, refresh_token_service

RequiredAccess = Literal["read", "write", "full"]


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    key: str
    label: str
    description: str


MODULE_DEFINITIONS: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        key="dashboard",
        label="Dashboard & Overview",
        description="KPI summary cards, store health, and activity snapshot",
    ),
    ModuleSpec(
        key="reports",
        label="Reports & Analytics",
        description="Sales, profit & loss, inventory, supplier, and Excel exports",
    ),
    ModuleSpec(
        key="orders",
        label="Orders & Fulfillment",
        description="Order list, status updates, packing, printing, and courier dispatch",
    ),
    ModuleSpec(
        key="products",
        label="Products & Catalog",
        description="Products, variants, categories, badges, media, and SEO",
    ),
    ModuleSpec(
        key="inventory",
        label="Inventory & Suppliers",
        description="Suppliers, purchases, stock movements, and batch imports",
    ),
    ModuleSpec(
        key="reviews",
        label="Customer Reviews",
        description="Review analytics, moderation, publish/hide, and edits",
    ),
    ModuleSpec(
        key="inquiries",
        label="Customer Inquiries",
        description="Contact form submissions, custom dress inquiries, and status notes",
    ),
    ModuleSpec(
        key="cart",
        label="Active Carts",
        description="Inspect active customer and guest shopping carts",
    ),
    ModuleSpec(
        key="coupons_pricing",
        label="Coupons, Pricing & Delivery",
        description="Promo codes, global pricing rules, and delivery zone charges",
    ),
    ModuleSpec(
        key="cms",
        label="CMS & Storefront",
        description="Home sections, banners, blogs, static pages, header/footer, and SEO",
    ),
    ModuleSpec(
        key="rbac",
        label="Users & Access Control",
        description="Staff accounts, role assignments, and dynamic permission matrix",
    ),
    ModuleSpec(
        key="audit_deletes",
        label="Audit Logs & Safe Deletes",
        description="Security audit trail and impact-checked delete/merge actions",
    ),
)

VALID_MODULE_KEYS: frozenset[str] = frozenset(m.key for m in MODULE_DEFINITIONS)
MODULE_BY_KEY: dict[str, ModuleSpec] = {m.key: m for m in MODULE_DEFINITIONS}

VALID_ACCESS_LEVELS: frozenset[str] = frozenset({"none", "read_only", "read_write", "full"})
ACCESS_RANK: dict[str, int] = {
    "none": 0,
    "read_only": 1,
    "read_write": 2,
    "full": 3,
}
REQUIRED_RANK: dict[RequiredAccess, int] = {
    "read": 1,
    "write": 2,
    "full": 3,
}

# Hardcoded immutable invariants: superadmin always full, customer always none.
LOCKED_ROLES: frozenset[str] = frozenset({UserRole.SUPERADMIN.value, UserRole.CUSTOMER.value})
SYSTEM_EDITABLE_ROLES: frozenset[str] = frozenset({UserRole.EDITOR.value, UserRole.VIEWER.value})
RESERVED_SLUGS: frozenset[str] = frozenset({"all", "staff", "admin", "system", "guest"})
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,49}$")

SYSTEM_ROLE_SEEDS: tuple[dict[str, object], ...] = (
    {
        "slug": UserRole.SUPERADMIN.value,
        "label": "Superadmin",
        "description": (
            "Full system owner with unrestricted access to all admin modules, "
            "staff accounts, RBAC matrix, audit logs, and impact-checked deletes."
        ),
        "category": "staff",
        "admin_access": True,
        "is_system": True,
    },
    {
        "slug": UserRole.EDITOR.value,
        "label": "Editor",
        "description": (
            "Operational staff role with customizable module permissions for "
            "orders, catalog, inventory, reviews, coupons, and CMS."
        ),
        "category": "staff",
        "admin_access": True,
        "is_system": True,
    },
    {
        "slug": UserRole.VIEWER.value,
        "label": "Viewer",
        "description": (
            "Observer/analyst staff role. Defaults to read-only across store "
            "modules and can be fine-tuned per module by Superadmin."
        ),
        "category": "staff",
        "admin_access": True,
        "is_system": True,
    },
    {
        "slug": UserRole.CUSTOMER.value,
        "label": "Customer",
        "description": (
            "Storefront shopper account. Permanently blocked from /admin and "
            "all staff APIs; limited to personal storefront orders and profile."
        ),
        "category": "storefront",
        "admin_access": False,
        "is_system": True,
    },
)

DEFAULT_ROLE_PERMISSIONS: dict[str, dict[str, AccessLevel]] = {
    UserRole.EDITOR.value: {
        "dashboard": "read_only",
        "reports": "read_only",
        "orders": "read_write",
        "products": "read_write",
        "inventory": "read_write",
        "reviews": "read_write",
        "inquiries": "read_write",
        "cart": "read_only",
        "coupons_pricing": "read_write",
        "cms": "read_write",
        "rbac": "none",
        "audit_deletes": "none",
    },
    UserRole.VIEWER.value: {
        "dashboard": "read_only",
        "reports": "read_only",
        "orders": "read_only",
        "products": "read_only",
        "inventory": "read_only",
        "reviews": "read_only",
        "inquiries": "read_only",
        "cart": "read_only",
        "coupons_pricing": "read_only",
        "cms": "read_only",
        "rbac": "none",
        "audit_deletes": "none",
    },
}

_ACCESS_SUMMARY: dict[str, str] = {
    "full": "Full access including create, edit, and sensitive/delete actions",
    "read_write": "Can view, create, and update records in this module",
    "read_only": "Read-only access; create, edit, and delete actions disabled",
    "none": "No admin access (403 Forbidden)",
}

_CACHE_TTL_SECONDS = 30.0
_cache: dict[str, tuple[float, dict[str, str]]] = {}
_admin_access_cache: dict[str, tuple[float, bool]] = {}


def invalidate_permission_cache(role: str | None = None) -> None:
    """Clear cached role permission & admin-access maps immediately."""
    if role is None:
        _cache.clear()
        _admin_access_cache.clear()
    else:
        _cache.pop(role, None)
        _admin_access_cache.pop(role, None)


def _normalize_role(role: UserRole | str) -> str:
    return role.value if isinstance(role, UserRole) else str(role).strip().lower()


def _slugify_role(raw: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")
    return cleaned[:50]


def has_module_access(
    permissions_map: dict[str, str],
    module_key: str,
    level: RequiredAccess,
) -> bool:
    granted = permissions_map.get(module_key, "none")
    return ACCESS_RANK.get(granted, 0) >= REQUIRED_RANK[level]


async def ensure_system_roles(db: AsyncSession) -> None:
    """Ensure the 4 system roles exist in the roles table (idempotent)."""
    existing = set((await db.scalars(select(Role.slug))).all())
    added = False
    for seed in SYSTEM_ROLE_SEEDS:
        slug = str(seed["slug"])
        if slug not in existing:
            db.add(
                Role(
                    slug=slug,
                    label=str(seed["label"]),
                    description=str(seed["description"]),
                    category=str(seed["category"]),
                    admin_access=bool(seed["admin_access"]),
                    is_system=bool(seed["is_system"]),
                )
            )
            added = True
    if added:
        await db.commit()


async def role_has_admin_access(db: AsyncSession, role: UserRole | str) -> bool:
    """True when the role is allowed to sign into /admin and call staff APIs."""
    role_key = _normalize_role(role)
    if role_key == UserRole.SUPERADMIN.value:
        return True
    if role_key == UserRole.CUSTOMER.value:
        return False

    now = time.monotonic()
    cached = _admin_access_cache.get(role_key)
    if cached is not None and cached[0] > now:
        return cached[1]

    row = await db.scalar(select(Role.admin_access).where(Role.slug == role_key))
    allowed = role_key in {r.value for r in STAFF_ROLES} if row is None else bool(row)

    _admin_access_cache[role_key] = (now + _CACHE_TTL_SECONDS, allowed)
    return allowed


async def get_admin_role_slugs(db: AsyncSession) -> set[str]:
    """Return all role slugs that currently grant admin panel access."""
    rows = (await db.scalars(select(Role.slug).where(Role.admin_access.is_(True)))).all()
    if not rows:
        return {r.value for r in STAFF_ROLES}
    return set(rows)


async def role_exists(db: AsyncSession, role: str) -> Role | None:
    slug = _normalize_role(role)
    return await db.scalar(select(Role).where(Role.slug == slug))


async def get_role_permissions_map(
    db: AsyncSession,
    role: UserRole | str,
) -> dict[str, str]:
    """Return effective {module_key: access_level} for the given role."""
    role_key = _normalize_role(role)

    # Immutable invariants — never consult DB or allow overrides.
    if role_key == UserRole.SUPERADMIN.value:
        return {spec.key: "full" for spec in MODULE_DEFINITIONS}
    if role_key == UserRole.CUSTOMER.value:
        return {spec.key: "none" for spec in MODULE_DEFINITIONS}

    now = time.monotonic()
    cached = _cache.get(role_key)
    if cached is not None and cached[0] > now:
        return dict(cached[1])

    defaults = DEFAULT_ROLE_PERMISSIONS.get(role_key, {})
    effective: dict[str, str] = {
        spec.key: defaults.get(spec.key, "none") for spec in MODULE_DEFINITIONS
    }

    rows = (
        await db.execute(
            select(RolePermission.module_key, RolePermission.access_level).where(
                RolePermission.role == role_key
            )
        )
    ).all()

    for module_key, access_level in rows:
        if module_key in VALID_MODULE_KEYS and access_level in VALID_ACCESS_LEVELS:
            effective[module_key] = access_level

    _cache[role_key] = (now + _CACHE_TTL_SECONDS, dict(effective))
    return effective


def _build_role_permissions_list(perms_map: dict[str, str]) -> list[RoleModuleAccess]:
    return [
        RoleModuleAccess(
            module_key=spec.key,
            module=spec.label,
            access=perms_map.get(spec.key, "none"),
            summary=_ACCESS_SUMMARY.get(perms_map.get(spec.key, "none"), ""),
        )
        for spec in MODULE_DEFINITIONS
    ]


def _role_sort_key(role: Role) -> tuple[int, str]:
    order = {
        UserRole.SUPERADMIN.value: (0, ""),
        UserRole.EDITOR.value: (1, ""),
        UserRole.VIEWER.value: (2, ""),
        UserRole.CUSTOMER.value: (4, ""),
    }
    return order.get(role.slug, (3, role.label.lower()))


async def _user_counts_by_role(db: AsyncSession) -> dict[str, int]:
    rows = (await db.execute(select(User.role, func.count(User.id)).group_by(User.role))).all()
    return {str(role): int(count) for role, count in rows}


def _to_role_read(role: Role, user_count: int) -> RoleRead:
    return RoleRead(
        id=role.id,
        slug=role.slug,
        label=role.label,
        description=role.description,
        category=role.category,
        admin_access=role.admin_access,
        is_system=role.is_system,
        editable=role.slug not in LOCKED_ROLES and role.admin_access,
        user_count=user_count,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


async def list_roles(db: AsyncSession) -> list[RoleRead]:
    await ensure_system_roles(db)
    all_roles = list((await db.scalars(select(Role))).all())
    all_roles.sort(key=_role_sort_key)
    counts = await _user_counts_by_role(db)
    return [_to_role_read(r, counts.get(r.slug, 0)) for r in all_roles]


async def get_dynamic_roles_matrix(db: AsyncSession) -> RolesMatrixResponse:
    await ensure_system_roles(db)
    all_roles = list((await db.scalars(select(Role))).all())
    all_roles.sort(key=_role_sort_key)
    counts = await _user_counts_by_role(db)

    roles: list[RoleDefinition] = []
    for role in all_roles:
        perms = await get_role_permissions_map(db, role.slug)
        roles.append(
            RoleDefinition(
                role=role.slug,
                label=role.label,
                category=role.category,
                admin_access=role.admin_access,
                is_system=role.is_system,
                editable=role.slug not in LOCKED_ROLES and role.admin_access,
                user_count=counts.get(role.slug, 0),
                description=role.description,
                permissions=_build_role_permissions_list(perms),
            )
        )

    module_defs = [
        ModuleDefinition(key=spec.key, label=spec.label, description=spec.description)
        for spec in MODULE_DEFINITIONS
    ]

    return RolesMatrixResponse(
        roles=roles,
        modules=[spec.label for spec in MODULE_DEFINITIONS],
        module_definitions=module_defs,
    )


async def update_role_permissions(
    db: AsyncSession,
    updates: list[RolePermissionUpdateItem],
    *,
    actor: User,
) -> RolesMatrixResponse:
    if not updates:
        raise UnprocessableError("At least one permission update is required")

    await ensure_system_roles(db)
    all_roles = {r.slug: r for r in (await db.scalars(select(Role))).all()}

    changes_log: list[dict[str, str]] = []
    touched_roles: set[str] = set()

    for item in updates:
        role_key = _normalize_role(item.role)
        module_key = item.module_key.strip()
        access_level = item.access_level

        if role_key in LOCKED_ROLES:
            raise PermissionDeniedError(
                f"Role '{role_key}' is system-protected and its permissions cannot be modified"
            )
        role_obj = all_roles.get(role_key)
        if role_obj is None or not role_obj.admin_access:
            raise UnprocessableError(f"Unknown or non-editable role: {role_key}")
        if module_key not in VALID_MODULE_KEYS:
            raise UnprocessableError(f"Unknown module key: {module_key}")
        if access_level not in VALID_ACCESS_LEVELS:
            raise UnprocessableError(f"Invalid access level: {access_level}")

        existing = await db.scalar(
            select(RolePermission).where(
                RolePermission.role == role_key,
                RolePermission.module_key == module_key,
            )
        )
        previous_level = (
            existing.access_level
            if existing is not None
            else DEFAULT_ROLE_PERMISSIONS.get(role_key, {}).get(module_key, "none")
        )

        if existing is None:
            db.add(
                RolePermission(
                    role=role_key,
                    module_key=module_key,
                    access_level=access_level,
                    updated_by=actor.id,
                )
            )
        else:
            existing.access_level = access_level
            existing.updated_by = actor.id

        touched_roles.add(role_key)
        if previous_level != access_level:
            changes_log.append(
                {
                    "role": role_key,
                    "module_key": module_key,
                    "from": previous_level,
                    "to": access_level,
                }
            )

    if changes_log:
        await audit_service.record(
            db,
            actor_id=actor.id,
            action=AuditAction.ROLE_PERMISSIONS_UPDATED,
            target_type="rbac",
            target_id="roles-matrix",
            metadata={"changes": changes_log},
        )

    await db.commit()
    for role_key in touched_roles:
        invalidate_permission_cache(role_key)

    return await get_dynamic_roles_matrix(db)


async def reset_role_permissions(
    db: AsyncSession,
    *,
    actor: User,
) -> RolesMatrixResponse:
    await ensure_system_roles(db)
    await db.execute(
        delete(RolePermission).where(RolePermission.role.in_(tuple(SYSTEM_EDITABLE_ROLES)))
    )
    for role_key, module_map in DEFAULT_ROLE_PERMISSIONS.items():
        for module_key, access_level in module_map.items():
            db.add(
                RolePermission(
                    role=role_key,
                    module_key=module_key,
                    access_level=access_level,
                    updated_by=actor.id,
                )
            )

    await audit_service.record(
        db,
        actor_id=actor.id,
        action=AuditAction.ROLE_PERMISSIONS_UPDATED,
        target_type="rbac",
        target_id="roles-matrix",
        metadata={"action": "reset_to_defaults", "roles": sorted(SYSTEM_EDITABLE_ROLES)},
    )
    await db.commit()
    invalidate_permission_cache()
    return await get_dynamic_roles_matrix(db)


async def create_role(
    db: AsyncSession,
    payload: RoleCreate,
    *,
    actor: User,
) -> RoleRead:
    await ensure_system_roles(db)
    label = payload.label.strip()
    if len(label) < 2:
        raise UnprocessableError("Role name must be at least 2 characters")

    slug = _slugify_role(payload.slug if payload.slug else label)
    if not _SLUG_RE.match(slug) or slug in RESERVED_SLUGS:
        raise UnprocessableError(
            "Role slug must start with a letter and use 2–50 lowercase letters, "
            "digits, or underscores"
        )

    existing = await db.scalar(select(Role).where(Role.slug == slug))
    if existing is not None:
        raise ConflictError(f"A role with slug '{slug}' already exists")

    seed_perms: dict[str, str] = {spec.key: "none" for spec in MODULE_DEFINITIONS}
    if payload.clone_from_role:
        source_slug = _normalize_role(payload.clone_from_role)
        source_role = await db.scalar(select(Role).where(Role.slug == source_slug))
        if source_role is None:
            raise UnprocessableError(f"Clone source role '{source_slug}' not found")
        source_map = await get_role_permissions_map(db, source_slug)
        for spec in MODULE_DEFINITIONS:
            seed_perms[spec.key] = source_map.get(spec.key, "none")

    role = Role(
        slug=slug,
        label=label,
        description=payload.description.strip(),
        category="staff",
        admin_access=True,
        is_system=False,
    )
    db.add(role)
    await db.flush()

    for spec in MODULE_DEFINITIONS:
        db.add(
            RolePermission(
                role=slug,
                module_key=spec.key,
                access_level=seed_perms[spec.key],
                updated_by=actor.id,
            )
        )

    await audit_service.record(
        db,
        actor_id=actor.id,
        action=AuditAction.ROLE_CREATED,
        target_type="role",
        target_id=slug,
        metadata={
            "label": label,
            "cloned_from": payload.clone_from_role or None,
        },
    )
    await db.commit()
    await db.refresh(role)
    invalidate_permission_cache()
    return _to_role_read(role, 0)


async def update_role(
    db: AsyncSession,
    slug: str,
    payload: RoleUpdate,
    *,
    actor: User,
) -> RoleRead:
    await ensure_system_roles(db)
    norm_slug = _normalize_role(slug)
    role = await db.scalar(select(Role).where(Role.slug == norm_slug))
    if role is None:
        raise NotFoundError(f"Role '{norm_slug}' not found")
    if role.is_system:
        raise PermissionDeniedError(f"System role '{norm_slug}' cannot be modified")

    changes: dict[str, str] = {}
    if payload.label is not None:
        new_label = payload.label.strip()
        if len(new_label) < 2:
            raise UnprocessableError("Role name must be at least 2 characters")
        if new_label != role.label:
            changes["label"] = new_label
            role.label = new_label
    if payload.description is not None:
        new_desc = payload.description.strip()
        if new_desc != role.description:
            changes["description"] = new_desc
            role.description = new_desc

    if changes:
        await audit_service.record(
            db,
            actor_id=actor.id,
            action=AuditAction.ROLE_UPDATED,
            target_type="role",
            target_id=role.slug,
            metadata=changes,
        )
    await db.commit()
    await db.refresh(role)
    invalidate_permission_cache(role.slug)

    user_count = int(
        (await db.scalar(select(func.count(User.id)).where(User.role == role.slug))) or 0
    )
    return _to_role_read(role, user_count)


async def get_role_delete_impact(db: AsyncSession, slug: str) -> RoleDeleteImpact:
    await ensure_system_roles(db)
    norm_slug = _normalize_role(slug)
    role = await db.scalar(select(Role).where(Role.slug == norm_slug))
    if role is None:
        raise NotFoundError(f"Role '{norm_slug}' not found")

    counts = await _user_counts_by_role(db)
    assigned_count = counts.get(role.slug, 0)
    all_roles = list((await db.scalars(select(Role).where(Role.slug != role.slug))).all())
    all_roles.sort(key=_role_sort_key)
    targets = [_to_role_read(r, counts.get(r.slug, 0)) for r in all_roles]

    return RoleDeleteImpact(
        slug=role.slug,
        label=role.label,
        is_system=role.is_system,
        can_delete=not role.is_system,
        assigned_users_count=assigned_count,
        reassignment_targets=targets,
    )


async def delete_role(
    db: AsyncSession,
    slug: str,
    *,
    reassign_to_role: str | None,
    actor: User,
) -> None:
    await ensure_system_roles(db)
    norm_slug = _normalize_role(slug)
    role = await db.scalar(select(Role).where(Role.slug == norm_slug))
    if role is None:
        raise NotFoundError(f"Role '{norm_slug}' not found")
    if role.is_system:
        raise PermissionDeniedError(f"System role '{norm_slug}' cannot be deleted")

    affected_user_ids = list(
        (await db.scalars(select(User.id).where(User.role == role.slug))).all()
    )
    target_slug: str | None = None
    if affected_user_ids:
        if not reassign_to_role or not reassign_to_role.strip():
            raise UnprocessableError(
                "This role has assigned users. Specify reassign_to_role before deleting."
            )
        target_slug = _normalize_role(reassign_to_role)
        if target_slug == role.slug:
            raise UnprocessableError("Cannot reassign users to the role being deleted")
        target_role = await db.scalar(select(Role).where(Role.slug == target_slug))
        if target_role is None:
            raise UnprocessableError(f"Target role '{target_slug}' does not exist")

        await db.execute(update(User).where(User.role == role.slug).values(role=target_slug))
        for uid in affected_user_ids:
            await refresh_token_service.revoke_user_sessions(db, uid)

    await db.execute(delete(RolePermission).where(RolePermission.role == role.slug))
    await db.delete(role)
    await audit_service.record(
        db,
        actor_id=actor.id,
        action=AuditAction.ROLE_DELETED,
        target_type="role",
        target_id=role.slug,
        metadata={
            "label": role.label,
            "reassigned_users": len(affected_user_ids),
            "reassign_to_role": target_slug,
        },
    )
    await db.commit()
    invalidate_permission_cache()
