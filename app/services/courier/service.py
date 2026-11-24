"""Run courier checks in parallel and read or replace the phone cache."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.courier_check import CourierCheckResult
from app.schemas.customer_report import (
    CourierCheck,
    CourierProviderResult,
    CourierTotals,
    RiskLevel,
)
from app.services.courier.adapters import providers
from app.services.courier.provider import (
    CourierHistoryProvider,
    ProviderResult,
    ProviderStatus,
    as_count,
    as_dict,
    failed,
    not_configured,
    success_ratio,
)

logger = get_logger("courier_check")


def open_client(timeout: float) -> httpx.AsyncClient:
    """One short-lived client. Redirects are off so a key is not forwarded."""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=False,
    )


def risk_level(rate: float | None) -> RiskLevel:
    """Map a 0–1 success rate. Equal to a threshold stays in the better band."""
    if rate is None:
        return "unknown"
    if rate < settings.courier_check_risk_high_below:
        return "high"
    if rate < settings.courier_check_risk_medium_below:
        return "medium"
    return "low"


async def read_courier_check(db: AsyncSession, phone: str) -> CourierCheck:
    rows = await _rows(db, phone)
    return _assemble(rows)


async def refresh_courier_check(db: AsyncSession, phone: str) -> CourierCheck:
    """Live check when the master flag is on. Otherwise the same view as a read."""
    if not settings.courier_check_enabled:
        logger.info("courier_check_skipped", reason="disabled")
        return await read_courier_check(db, phone)

    results = await asyncio.gather(*(_run(provider, phone) for provider in providers()))
    await _save(db, phone, results)
    logger.info(
        "courier_check_finished",
        providers=[item.provider for item in results],
        statuses=[item.status for item in results],
    )
    return await read_courier_check(db, phone)


async def _run(provider: CourierHistoryProvider, phone: str) -> ProviderResult:
    if not provider.configured():
        return not_configured(provider.name)
    timeout = float(settings.courier_check_timeout_seconds)
    try:
        async with open_client(timeout) as client:
            return await asyncio.wait_for(provider.check(phone, client), timeout)
    except TimeoutError:
        return failed(provider.name, "Timed out")
    except httpx.TimeoutException:
        return failed(provider.name, "Timed out")
    except httpx.HTTPError:
        return failed(provider.name, "Network error")
    except Exception as exc:
        logger.warning(
            "courier_check_failed",
            provider=provider.name,
            error_type=type(exc).__name__,
        )
        return failed(provider.name, "Courier check failed")


async def _rows(db: AsyncSession, phone: str) -> dict[str, CourierCheckResult]:
    found = (
        await db.scalars(select(CourierCheckResult).where(CourierCheckResult.phone == phone))
    ).all()
    return {row.provider: row for row in found}


async def _save(db: AsyncSession, phone: str, results: list[ProviderResult]) -> None:
    now = datetime.now(UTC)
    try:
        await _write(db, phone, results, now)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        await _write(db, phone, results, now)
        await db.commit()


async def _write(
    db: AsyncSession,
    phone: str,
    results: list[ProviderResult],
    checked_at: datetime,
) -> None:
    for result in results:
        if result.status == "not_configured":
            continue
        await _apply(db, phone, result, checked_at)


async def _apply(
    db: AsyncSession,
    phone: str,
    result: ProviderResult,
    checked_at: datetime,
) -> None:
    existing = await db.scalar(
        select(CourierCheckResult).where(
            CourierCheckResult.phone == phone,
            CourierCheckResult.provider == result.provider,
        )
    )
    payload = result.as_payload()
    if existing is None:
        db.add(
            CourierCheckResult(
                phone=phone,
                provider=result.provider,
                payload=payload,
                checked_at=checked_at,
            )
        )
        return
    existing.payload = payload
    existing.checked_at = checked_at


def _assemble(rows: dict[str, CourierCheckResult]) -> CourierCheck:
    items: list[CourierProviderResult] = []
    checked_times: list[datetime] = []
    missing = False
    configured_any = False
    for provider in providers():
        if not provider.configured():
            items.append(CourierProviderResult(provider=provider.name, status="not_configured"))
            continue
        configured_any = True
        row = rows.get(provider.name)
        if row is None:
            missing = True
            items.append(
                CourierProviderResult(
                    provider=provider.name,
                    status="error",
                    error_message="No cached result",
                )
            )
            continue
        checked_times.append(_aware(row.checked_at))
        items.append(_from_row(provider.name, row.payload))

    checked_at = min(checked_times) if checked_times else None
    stale = False
    if configured_any:
        limit = timedelta(hours=settings.courier_check_cache_hours)
        old = checked_at is None or datetime.now(UTC) - checked_at > limit
        stale = missing or old or checked_at is None
    totals = _totals(items)
    return CourierCheck(
        enabled=settings.courier_check_enabled,
        checked_at=checked_at,
        stale=stale,
        totals=totals,
        risk_level=risk_level(totals.success_rate),
        providers=items,
    )


def _from_row(name: str, payload: object) -> CourierProviderResult:
    body = as_dict(payload)
    status = body.get("status") if body else None
    if status == "ok":
        stored: ProviderStatus = "ok"
    elif status == "error":
        stored = "error"
    elif status == "unverified":
        stored = "unverified"
    else:
        return CourierProviderResult(
            provider=name,
            status="error",
            error_message="Cached result is unreadable",
        )
    assert body is not None
    delivered = as_count(body.get("delivered"))
    failed_count = as_count(body.get("returned_or_cancelled"))
    total = as_count(body.get("total_parcels"))
    message = body.get("error_message")
    error_message = message[:200] if isinstance(message, str) and message.strip() else None
    rate = None
    if delivered is not None and failed_count is not None:
        rate = success_ratio(delivered, failed_count)
    return CourierProviderResult(
        provider=name,
        status=stored,
        total_parcels=total,
        delivered=delivered,
        returned_or_cancelled=failed_count,
        success_rate=rate,
        error_message=error_message,
    )


def _totals(items: list[CourierProviderResult]) -> CourierTotals:
    total = 0
    delivered = 0
    failed_count = 0
    used = False
    for item in items:
        if item.status not in {"ok", "unverified"}:
            continue
        if (
            item.total_parcels is None
            or item.delivered is None
            or item.returned_or_cancelled is None
        ):
            continue
        used = True
        total += item.total_parcels
        delivered += item.delivered
        failed_count += item.returned_or_cancelled
    if not used:
        return CourierTotals()
    return CourierTotals(
        total_parcels=total,
        delivered=delivered,
        returned_or_cancelled=failed_count,
        success_rate=success_ratio(delivered, failed_count),
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
