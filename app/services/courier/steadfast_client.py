"""Hardened async Steadfast Merchant API v1 client (Phase 23).

Production safeguards:
- Input sanitizer & truncation: replaces ``{``, ``}``, ``;``, ``<``, ``>``, ``$`` (and control
  characters) with spaces; enforces exact Steadfast field length caps (`invoice` 100,
  `recipient_name` 100, `recipient_phone` 40, `recipient_address` 490, `note` 480).
- Redis-backed ``401`` circuit breaker: tracks consecutive HTTP 401 responses; after 3
  consecutive 401s trips a 10-minute circuit breaker and emits a critical log alert.
  NEVER retries ``401`` in a loop (avoids Steadfast's 60-minute ``429`` IP lockout).
- 60-second Redis caches / cooldowns for tracking, status, and parcel state reads.
- Inspects response bodies even on HTTP 200 (especially for ``/create_order/bulk-order/extended``
  which can return per-item validation failures inside an HTTP 200 payload).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.services.courier.provider import https_url, secret_text
from app.services.redis_client import redis_client

logger = get_logger(__name__)

_FORBIDDEN_CHARS_RE = re.compile(r"[{};<>$\r\n\t]+")
_MULTI_SPACE_RE = re.compile(r" {2,}")

MAX_INVOICE_LEN = 100
MAX_RECIPIENT_NAME_LEN = 100
MAX_RECIPIENT_PHONE_LEN = 40
MAX_RECIPIENT_ADDRESS_LEN = 490
MAX_NOTE_LEN = 480
MAX_ITEM_DESCRIPTION_LEN = 480
BULK_CHUNK_SIZE = 500

CIRCUIT_BREAKER_THRESHOLD = 3
CIRCUIT_BREAKER_OPEN_SECONDS = 600  # 10 minutes
CIRCUIT_FAILURE_WINDOW_SECONDS = 900  # 15 minutes
CACHE_TTL_SECONDS = 60

_CB_FAILURES_KEY = "sf:cb:failures"
_CB_OPEN_KEY = "sf:cb:open"
_TRACKING_CACHE_PREFIX = "sf:cache:track:"
_PARCEL_STATES_CACHE_KEY = "sf:cache:parcel_states"
_STATUS_CACHE_PREFIX = "sf:cache:status:"


class SteadfastError(AppError):
    status_code = 502
    code = "steadfast_error"


class SteadfastNotConfiguredError(SteadfastError):
    status_code = 503
    code = "steadfast_not_configured"


class SteadfastCircuitOpenError(SteadfastError):
    status_code = 503
    code = "steadfast_circuit_open"


class SteadfastAuthError(SteadfastError):
    status_code = 502
    code = "steadfast_auth_failed"


class SteadfastUpstreamError(SteadfastError):
    status_code = 502
    code = "steadfast_upstream_error"


def sanitize_steadfast_text(value: str | None, max_len: int) -> str:
    """Replace forbidden Steadfast characters ``{};<>$`` with spaces and enforce max_len."""
    if not value:
        return ""
    cleaned = _FORBIDDEN_CHARS_RE.sub(" ", str(value))
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned).strip()
    return cleaned[:max_len]


def sanitize_order_payload(order: dict[str, Any]) -> dict[str, Any]:
    """Sanitize and truncate all Steadfast order fields to exact documented limits."""
    cod = int(order.get("cod_amount", 0) or 0)
    if cod < 0:
        cod = 0
    payload: dict[str, Any] = {
        "invoice": sanitize_steadfast_text(str(order.get("invoice", "")), MAX_INVOICE_LEN),
        "recipient_name": sanitize_steadfast_text(
            str(order.get("recipient_name", "")), MAX_RECIPIENT_NAME_LEN
        ),
        "recipient_phone": sanitize_steadfast_text(
            str(order.get("recipient_phone", "")), MAX_RECIPIENT_PHONE_LEN
        ),
        "recipient_address": sanitize_steadfast_text(
            str(order.get("recipient_address", "")), MAX_RECIPIENT_ADDRESS_LEN
        ),
        "cod_amount": cod,
    }
    note = sanitize_steadfast_text(order.get("note"), MAX_NOTE_LEN)
    if note:
        payload["note"] = note
    item_desc = sanitize_steadfast_text(order.get("item_description"), MAX_ITEM_DESCRIPTION_LEN)
    if item_desc:
        payload["item_description"] = item_desc
    if order.get("alternative_phone"):
        payload["alternative_phone"] = sanitize_steadfast_text(
            str(order["alternative_phone"]), MAX_RECIPIENT_PHONE_LEN
        )
    if order.get("recipient_email"):
        payload["recipient_email"] = sanitize_steadfast_text(str(order["recipient_email"]), 100)
    if order.get("delivery_type") is not None:
        payload["delivery_type"] = int(order["delivery_type"])
    return payload


@dataclass(frozen=True, slots=True)
class CircuitBreakerState:
    is_open: bool
    retry_after_seconds: int
    consecutive_auth_failures: int


def default_http_client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


class SteadfastClient:
    """Hardened async client for Steadfast Merchant API v1."""

    def __init__(
        self,
        *,
        client_factory: Callable[[float], httpx.AsyncClient] | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._client_factory = client_factory
        self._timeout_seconds = timeout_seconds

    def _open_client(self) -> httpx.AsyncClient:
        factory = self._client_factory or default_http_client
        return factory(self._timeout_seconds)

    def configured(self) -> bool:
        return bool(
            secret_text(settings.steadfast_api_key)
            and secret_text(settings.steadfast_secret_key)
            and https_url(settings.steadfast_base_url)
        )

    def _credentials(self) -> tuple[str, dict[str, str]]:
        api_key = secret_text(settings.steadfast_api_key)
        secret_key = secret_text(settings.steadfast_secret_key)
        base = https_url(settings.steadfast_base_url)
        if not api_key or not secret_key or base is None:
            raise SteadfastNotConfiguredError(
                "Steadfast API credentials or HTTPS base URL are not configured"
            )
        headers = {
            "Api-Key": api_key,
            "Secret-Key": secret_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        return base, headers

    async def get_circuit_state(self) -> CircuitBreakerState:
        retry_after = await redis_client.ttl_remaining(_CB_OPEN_KEY)
        is_open = retry_after > 0 or (await redis_client.get_str(_CB_OPEN_KEY)) is not None
        raw_failures = await redis_client.get_str(_CB_FAILURES_KEY)
        failures = int(raw_failures) if raw_failures and raw_failures.isdigit() else 0
        return CircuitBreakerState(
            is_open=is_open,
            retry_after_seconds=retry_after,
            consecutive_auth_failures=failures,
        )

    async def _record_auth_failure(self, path: str) -> None:
        count = await redis_client.incr_with_ttl(
            _CB_FAILURES_KEY,
            ttl_seconds=CIRCUIT_FAILURE_WINDOW_SECONDS,
        )
        if count >= CIRCUIT_BREAKER_THRESHOLD:
            await redis_client.set_str(
                _CB_OPEN_KEY,
                "1",
                ttl_seconds=CIRCUIT_BREAKER_OPEN_SECONDS,
            )
            logger.critical(
                "steadfast_circuit_breaker_tripped",
                path=path,
                consecutive_401=count,
                cooldown_seconds=CIRCUIT_BREAKER_OPEN_SECONDS,
            )
        else:
            logger.warning(
                "steadfast_auth_failure",
                path=path,
                consecutive_401=count,
                threshold=CIRCUIT_BREAKER_THRESHOLD,
            )

    async def _reset_auth_failures(self) -> None:
        await redis_client.delete_key(_CB_FAILURES_KEY)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        cb = await self.get_circuit_state()
        if cb.is_open:
            raise SteadfastCircuitOpenError(
                "Steadfast API temporarily paused after repeated authentication failures. "
                f"Retry in {cb.retry_after_seconds}s after verifying credentials."
            )

        base, headers = self._credentials()
        url = f"{base}/{path.lstrip('/')}"

        try:
            async with self._open_client() as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                    params=params,
                )
        except httpx.TimeoutException as exc:
            raise SteadfastUpstreamError("Steadfast API request timed out") from exc
        except httpx.HTTPError as exc:
            raise SteadfastUpstreamError("Network error while contacting Steadfast API") from exc

        # NEVER retry HTTP 401 — record failure and trip circuit breaker after 3 consecutive 401s.
        if response.status_code == 401:
            await self._record_auth_failure(path)
            raise SteadfastAuthError("Steadfast API authentication failed (HTTP 401)")

        if response.status_code == 429:
            logger.warning("steadfast_rate_limited", path=path)
            raise SteadfastUpstreamError("Steadfast API rate limit exceeded (HTTP 429)")

        if response.status_code < 200 or response.status_code >= 300:
            detail_msg = f"Steadfast API returned HTTP {response.status_code}"
            try:
                err_body = response.json()
                if isinstance(err_body, dict):
                    msg = err_body.get("message") or err_body.get("error")
                    if isinstance(msg, str) and msg.strip():
                        detail_msg = (
                            f"Steadfast error ({response.status_code}): {msg.strip()[:200]}"
                        )
            except ValueError:
                pass
            raise SteadfastUpstreamError(detail_msg)

        await self._reset_auth_failures()

        try:
            return response.json()
        except ValueError as exc:
            raise SteadfastUpstreamError("Steadfast API returned invalid JSON") from exc

    async def ping(self) -> dict[str, Any]:
        cb = await self.get_circuit_state()
        if not self.configured():
            return {
                "configured": False,
                "ok": False,
                "balance": None,
                "circuit_open": cb.is_open,
                "circuit_retry_after_seconds": cb.retry_after_seconds,
                "consecutive_auth_failures": cb.consecutive_auth_failures,
                "error": "Steadfast credentials not configured",
            }
        if cb.is_open:
            return {
                "configured": True,
                "ok": False,
                "balance": None,
                "circuit_open": True,
                "circuit_retry_after_seconds": cb.retry_after_seconds,
                "consecutive_auth_failures": cb.consecutive_auth_failures,
                "error": "Circuit breaker open after repeated 401 authentication errors",
            }
        try:
            body = await self.get_balance()
            balance = body.get("current_balance") if isinstance(body, dict) else None
            cb_after = await self.get_circuit_state()
            return {
                "configured": True,
                "ok": True,
                "balance": float(balance) if isinstance(balance, (int, float)) else None,
                "circuit_open": cb_after.is_open,
                "circuit_retry_after_seconds": cb_after.retry_after_seconds,
                "consecutive_auth_failures": cb_after.consecutive_auth_failures,
                "error": None,
            }
        except SteadfastError as exc:
            cb_after = await self.get_circuit_state()
            return {
                "configured": True,
                "ok": False,
                "balance": None,
                "circuit_open": cb_after.is_open,
                "circuit_retry_after_seconds": cb_after.retry_after_seconds,
                "consecutive_auth_failures": cb_after.consecutive_auth_failures,
                "error": exc.message,
            }

    async def create_order(self, order: dict[str, Any]) -> dict[str, Any]:
        sanitized = sanitize_order_payload(order)
        body = await self._request("POST", "/create_order", json_body=sanitized)
        if not isinstance(body, dict):
            raise SteadfastUpstreamError("Unexpected response from Steadfast create_order")
        # Inspect response body even on HTTP 200 (Steadfast returns status=400/errors in JSON).
        body_status = body.get("status")
        if body_status is not None and str(body_status) not in {"200", "201", "success"}:
            err_msg = body.get("message") or body.get("errors") or "Order booking rejected"
            raise SteadfastUpstreamError(f"Steadfast rejected order: {err_msg}", details=body)
        if body.get("errors") and not body.get("consignment"):
            raise SteadfastUpstreamError("Steadfast validation error", details=body["errors"])
        return body

    async def bulk_create_orders_extended(
        self, orders: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Submit orders in chunks of <= 500 to `/create_order/bulk-order/extended`.

        Returns a flat list of per-item Steadfast result dicts (caller must inspect each item's
        ``status`` / ``errors`` even when HTTP status was 200).
        """
        results: list[dict[str, Any]] = []
        for idx in range(0, len(orders), BULK_CHUNK_SIZE):
            chunk = [sanitize_order_payload(o) for o in orders[idx : idx + BULK_CHUNK_SIZE]]
            body = await self._request(
                "POST",
                "/create_order/bulk-order/extended",
                json_body={"data": chunk},
            )
            if isinstance(body, list):
                results.extend(item for item in body if isinstance(item, dict))
            elif isinstance(body, dict):
                data = body.get("data")
                if isinstance(data, list):
                    results.extend(item for item in data if isinstance(item, dict))
                elif isinstance(body.get("consignments"), list):
                    results.extend(
                        item for item in body["consignments"] if isinstance(item, dict)
                    )
                else:
                    raise SteadfastUpstreamError(
                        "Unexpected response from Steadfast bulk-order/extended",
                        details=body,
                    )
            else:
                raise SteadfastUpstreamError(
                    "Unexpected response from Steadfast bulk-order/extended"
                )
        return results

    async def status_with_return_by_cid(
        self, consignment_id: str, *, use_cache: bool = True
    ) -> dict[str, Any]:
        cid = sanitize_steadfast_text(consignment_id, 64)
        cache_key = f"{_STATUS_CACHE_PREFIX}{cid}"
        if use_cache:
            cached = await redis_client.get_json(cache_key)
            if isinstance(cached, dict):
                return cached
        body = await self._request("GET", f"/status_with_return_by_cid/{cid}")
        if not isinstance(body, dict):
            raise SteadfastUpstreamError("Unexpected status_with_return_by_cid response")
        await redis_client.set_json(cache_key, body, ttl_seconds=CACHE_TTL_SECONDS)
        return body

    async def trackings_by_invoice(
        self, invoice: str, *, use_cache: bool = True
    ) -> tuple[list[dict[str, Any]], bool]:
        inv = sanitize_steadfast_text(invoice, MAX_INVOICE_LEN)
        cache_key = f"{_TRACKING_CACHE_PREFIX}{inv}"
        if use_cache:
            cached = await redis_client.get_json(cache_key)
            if isinstance(cached, list):
                return [item for item in cached if isinstance(item, dict)], True
        body = await self._request("GET", f"/trackings_by_invoice/{inv}")
        events = _extract_tracking_events(body)
        await redis_client.set_json(cache_key, events, ttl_seconds=CACHE_TTL_SECONDS)
        return events, False

    async def create_pickup_request(
        self,
        *,
        address: str,
        note: str = "",
        phone: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "address": sanitize_steadfast_text(address, MAX_RECIPIENT_ADDRESS_LEN),
        }
        clean_note = sanitize_steadfast_text(note, MAX_NOTE_LEN)
        if clean_note:
            payload["note"] = clean_note
        clean_phone = sanitize_steadfast_text(phone, MAX_RECIPIENT_PHONE_LEN)
        if clean_phone:
            payload["phone"] = clean_phone
        body = await self._request("POST", "/create_pickup_request", json_body=payload)
        return body if isinstance(body, dict) else {"data": body}

    async def list_return_requests(self) -> list[dict[str, Any]]:
        body = await self._request("GET", "/get_return_requests")
        if isinstance(body, list):
            return [item for item in body if isinstance(item, dict)]
        if isinstance(body, dict):
            for key in ("data", "return_requests", "requests"):
                if isinstance(body.get(key), list):
                    return [item for item in body[key] if isinstance(item, dict)]
        return []

    async def get_return_request(self, request_id: str) -> dict[str, Any]:
        rid = sanitize_steadfast_text(request_id, 64)
        body = await self._request("GET", f"/get_return_request/{rid}")
        return body if isinstance(body, dict) else {"data": body}

    async def create_return_request(
        self,
        *,
        consignment_id: str | None = None,
        invoice: str | None = None,
        tracking_code: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if consignment_id:
            payload["consignment_id"] = sanitize_steadfast_text(consignment_id, 64)
        if invoice:
            payload["invoice"] = sanitize_steadfast_text(invoice, MAX_INVOICE_LEN)
        if tracking_code:
            payload["tracking_code"] = sanitize_steadfast_text(tracking_code, 120)
        clean_reason = sanitize_steadfast_text(reason, MAX_NOTE_LEN)
        if clean_reason:
            payload["reason"] = clean_reason
        body = await self._request("POST", "/create_return_request", json_body=payload)
        return body if isinstance(body, dict) else {"data": body}

    async def get_balance(self) -> dict[str, Any]:
        body = await self._request("GET", "/get_balance")
        return body if isinstance(body, dict) else {"data": body}

    async def list_payments(self) -> list[dict[str, Any]]:
        body = await self._request("GET", "/payments")
        if isinstance(body, list):
            return [item for item in body if isinstance(item, dict)]
        if isinstance(body, dict):
            for key in ("data", "payments"):
                if isinstance(body.get(key), list):
                    return [item for item in body[key] if isinstance(item, dict)]
        return []

    async def get_payment_detail(self, payment_id: str) -> dict[str, Any]:
        pid = sanitize_steadfast_text(payment_id, 64)
        body = await self._request("GET", f"/payments/{pid}")
        return body if isinstance(body, dict) else {"data": body}

    async def get_parcel_states(self, *, use_cache: bool = True) -> tuple[dict[str, Any], bool]:
        if use_cache:
            cached = await redis_client.get_json(_PARCEL_STATES_CACHE_KEY)
            if isinstance(cached, dict):
                return cached, True
        body = await self._request("GET", "/parcel_states")
        result = body if isinstance(body, dict) else {"data": body}
        await redis_client.set_json(
            _PARCEL_STATES_CACHE_KEY, result, ttl_seconds=CACHE_TTL_SECONDS
        )
        return result, False

    async def get_parcels_in_state(self, state: str, *, page: int = 1) -> dict[str, Any]:
        clean_state = sanitize_steadfast_text(state, 64)
        body = await self._request("GET", f"/parcels_in_state/{clean_state}", params={"page": page})
        return body if isinstance(body, dict) else {"data": body}

    async def get_stats(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        body = await self._request("GET", "/stats", params=params or None)
        return body if isinstance(body, dict) else {"data": body}

    async def get_police_stations(self) -> list[dict[str, Any]]:
        body = await self._request("GET", "/police_stations")
        if isinstance(body, list):
            return [item for item in body if isinstance(item, dict)]
        if isinstance(body, dict):
            for key in ("data", "police_stations", "stations"):
                if isinstance(body.get(key), list):
                    return [item for item in body[key] if isinstance(item, dict)]
        return []

    async def get_fraud_score(self, phone: str) -> dict[str, Any]:
        clean_phone = sanitize_steadfast_text(phone, MAX_RECIPIENT_PHONE_LEN)
        body = await self._request("GET", f"/fraud_check/score/{clean_phone}")
        return body if isinstance(body, dict) else {"data": body}


def _extract_tracking_events(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if isinstance(body, dict):
        for key in ("trackings", "tracking_events", "events", "data"):
            val = body.get(key)
            if isinstance(val, list):
                return [item for item in val if isinstance(item, dict)]
            if isinstance(val, dict):
                for inner in ("trackings", "events", "history"):
                    if isinstance(val.get(inner), list):
                        return [item for item in val[inner] if isinstance(item, dict)]
    return []


steadfast_client = SteadfastClient()
