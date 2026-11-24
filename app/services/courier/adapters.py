"""Courier adapters.

Steadfast's count endpoint is the one published by Steadfast's own package.
Pathao, RedX, and the generic aggregator are config-driven and unverified:
their fraud-check URLs are not in a public API document.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.schemas.inquiry import normalize_phone
from app.services.courier.provider import (
    ProviderResult,
    as_count,
    as_dict,
    bearer,
    counted,
    failed,
    first_count,
    header_name,
    https_url,
    secret_text,
)

_DELIVERED_KEYS = (
    "total_delivered",
    "delivered",
    "deliveredParcels",
    "success",
    "successful_delivery",
    "successful_deliveries",
)
_FAILED_KEYS = (
    "total_cancelled",
    "returned_or_cancelled",
    "cancelled",
    "cancel",
    "total_cancel",
)
_TOTAL_KEYS = (
    "total_parcels",
    "totalParcels",
    "total",
    "total_delivery",
    "total_deliveries",
    "total_parcel",
)


class SteadfastProvider:
    """Verified against Steadfast's merchant API.

    `GET {STEADFAST_BASE_URL}/fraud_check/{phone}` with `Api-Key` and `Secret-Key`.
    The documented body is total_parcels, total_delivered, total_cancelled.
    """

    name = "steadfast"
    verified = True

    def configured(self) -> bool:
        return bool(
            secret_text(settings.steadfast_api_key)
            and secret_text(settings.steadfast_secret_key)
            and https_url(settings.steadfast_base_url)
        )

    async def check(self, phone: str, client: httpx.AsyncClient) -> ProviderResult:
        base = https_url(settings.steadfast_base_url)
        if base is None:
            return failed(self.name, "Steadfast base URL is not https")
        url = f"{base}/fraud_check/{phone}"
        try:
            response = await client.get(
                url,
                headers={
                    "Api-Key": secret_text(settings.steadfast_api_key),
                    "Secret-Key": secret_text(settings.steadfast_secret_key),
                    "Accept": "application/json",
                },
            )
        except httpx.TimeoutException:
            return failed(self.name, "Timed out")
        except httpx.HTTPError:
            return failed(self.name, "Network error")
        if response.status_code < 200 or response.status_code >= 300:
            return failed(self.name, f"Steadfast returned HTTP {response.status_code}")
        block = _steadfast_block(response)
        if block is None:
            return failed(self.name, "Unexpected response")
        total = as_count(block.get("total_parcels"))
        delivered = as_count(block.get("total_delivered"))
        cancelled = as_count(block.get("total_cancelled"))
        if total is None or delivered is None or cancelled is None:
            return failed(self.name, "Unexpected response")
        return counted(
            self.name,
            status="ok",
            total=total,
            delivered=delivered,
            failed_count=cancelled,
        )


class PathaoProvider:
    """Unverified. Pathao's published Hermes API has no fraud-check method.

    This calls the merchant panel: POST `{base}/api/v1/login`, then
    POST `{base}/api/v1/user/success` with the phone. A `show_count: false`
    body is a rating only, so the counts stay null instead of becoming zero.
    """

    name = "pathao"
    verified = False

    def configured(self) -> bool:
        return bool(
            settings.pathao_username.strip()
            and secret_text(settings.pathao_password)
            and https_url(settings.pathao_base_url)
            and header_name(settings.pathao_auth_header)
        )

    async def check(self, phone: str, client: httpx.AsyncClient) -> ProviderResult:
        base = https_url(settings.pathao_base_url)
        auth = header_name(settings.pathao_auth_header)
        if base is None or auth is None:
            return failed(self.name, "Pathao is not configured")
        try:
            login = await client.post(
                f"{base}/api/v1/login",
                json={
                    "username": settings.pathao_username.strip(),
                    "password": secret_text(settings.pathao_password),
                },
                headers={"Accept": "application/json"},
            )
        except httpx.TimeoutException:
            return failed(self.name, "Timed out")
        except httpx.HTTPError:
            return failed(self.name, "Network error")
        if login.status_code < 200 or login.status_code >= 300:
            return failed(self.name, "Pathao authentication failed")
        token = _pathao_token(login)
        if not token:
            return failed(self.name, "Pathao authentication failed")
        try:
            response = await client.post(
                f"{base}/api/v1/user/success",
                json={"phone": phone},
                headers={
                    auth: bearer(token),
                    "Accept": "application/json",
                },
            )
        except httpx.TimeoutException:
            return failed(self.name, "Timed out")
        except httpx.HTTPError:
            return failed(self.name, "Network error")
        if response.status_code < 200 or response.status_code >= 300:
            return failed(self.name, f"Pathao returned HTTP {response.status_code}")
        return _pathao_counts(response)


class RedxProvider:
    """Unverified. RedX's published OpenAPI has no fraud-check method.

    Phone and password, when both are set, log in at REDX_AUTH_URL and call
    `{REDX_BASE_URL}/api/redx_se/admin/parcel/customer-success-return-rate`.
    Otherwise REDX_API_TOKEN is sent in REDX_AUTH_HEADER. An HTTP 400 body
    with the known static 10 delivered-as-6 sample is an error.
    """

    name = "redx"
    verified = False

    def configured(self) -> bool:
        if https_url(settings.redx_base_url) is None:
            return False
        phone = settings.redx_phone.strip()
        password = secret_text(settings.redx_password)
        if phone or password:
            return bool(
                phone and password and normalize_phone(phone) and https_url(settings.redx_auth_url)
            )
        return bool(secret_text(settings.redx_api_token) and header_name(settings.redx_auth_header))

    async def check(self, phone: str, client: httpx.AsyncClient) -> ProviderResult:
        base = https_url(settings.redx_base_url)
        if base is None:
            return failed(self.name, "RedX base URL is not https")
        try:
            token = await self._token(client)
        except httpx.TimeoutException:
            return failed(self.name, "Timed out")
        except httpx.HTTPError:
            return failed(self.name, "Network error")
        if token is None:
            return failed(self.name, "RedX authentication failed")
        auth = header_name(settings.redx_auth_header) or "Authorization"
        header = "Authorization" if self._uses_login() else auth
        try:
            response = await client.get(
                f"{base}/api/redx_se/admin/parcel/customer-success-return-rate",
                params={"phoneNumber": f"88{phone}"},
                headers={header: bearer(token), "Accept": "application/json"},
            )
        except httpx.TimeoutException:
            return failed(self.name, "Timed out")
        except httpx.HTTPError:
            return failed(self.name, "Network error")
        return _redx_counts(response)

    def _uses_login(self) -> bool:
        return bool(settings.redx_phone.strip() and secret_text(settings.redx_password))

    async def _token(self, client: httpx.AsyncClient) -> str | None:
        if not self._uses_login():
            text = secret_text(settings.redx_api_token)
            return text or None
        login_phone = normalize_phone(settings.redx_phone)
        auth_url = https_url(settings.redx_auth_url)
        if login_phone is None or auth_url is None:
            return None
        response = await client.post(
            auth_url,
            json={"phone": f"88{login_phone}", "password": secret_text(settings.redx_password)},
            headers={"Accept": "application/json"},
        )
        if response.status_code < 200 or response.status_code >= 300:
            return None
        return _redx_token(response)


class GenericProvider:
    """Unverified aggregator. POST `{phone, phone_number}` to COURIER_CHECK_GENERIC_URL.

    `Authorization` sends `Bearer <key>`. Any other header name sends the key as-is,
    which matches aggregators that use an `api_key` header. Counts are read from
    `data.totalSummary` when that object is present, otherwise from `data` or the
    top-level object.
    """

    name = "generic"
    verified = False

    def configured(self) -> bool:
        return bool(
            https_url(settings.courier_check_generic_url)
            and secret_text(settings.courier_check_generic_api_key)
            and header_name(settings.courier_check_generic_auth_header)
        )

    async def check(self, phone: str, client: httpx.AsyncClient) -> ProviderResult:
        url = https_url(settings.courier_check_generic_url)
        auth = header_name(settings.courier_check_generic_auth_header)
        key = secret_text(settings.courier_check_generic_api_key)
        if url is None or auth is None or not key:
            return failed(self.name, "Generic courier check is not configured")
        value = bearer(key) if auth.lower() == "authorization" else key
        try:
            response = await client.post(
                url,
                json={"phone": phone, "phone_number": phone},
                headers={auth: value, "Accept": "application/json"},
            )
        except httpx.TimeoutException:
            return failed(self.name, "Timed out")
        except httpx.HTTPError:
            return failed(self.name, "Network error")
        if response.status_code < 200 or response.status_code >= 300:
            return failed(self.name, f"Generic provider returned HTTP {response.status_code}")
        block = _generic_block(response)
        if block is None:
            return failed(self.name, "Unexpected response")
        delivered = first_count(block, _DELIVERED_KEYS)
        failed_count = first_count(block, _FAILED_KEYS)
        total = first_count(block, _TOTAL_KEYS)
        if delivered is None or failed_count is None:
            return failed(self.name, "Unexpected response")
        if total is None:
            total = delivered + failed_count
        return counted(
            self.name,
            status="unverified",
            total=total,
            delivered=delivered,
            failed_count=failed_count,
        )


def providers() -> tuple[SteadfastProvider, PathaoProvider, RedxProvider, GenericProvider]:
    return (SteadfastProvider(), PathaoProvider(), RedxProvider(), GenericProvider())


def _json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        return as_dict(response.json())
    except ValueError:
        return None


def _steadfast_block(response: httpx.Response) -> dict[str, Any] | None:
    body = _json(response)
    if body is None:
        return None
    if "total_parcels" in body or "total_delivered" in body:
        return body
    return as_dict(body.get("data"))


def _pathao_token(response: httpx.Response) -> str:
    body = _json(response) or {}
    for key in ("access_token", "token"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    data = as_dict(body.get("data")) or {}
    for key in ("access_token", "token"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _pathao_counts(response: httpx.Response) -> ProviderResult:
    body = _json(response)
    if body is None:
        return failed("pathao", "Unexpected response")
    data = as_dict(body.get("data")) or body
    customer = as_dict(data.get("customer")) or {}
    if data.get("show_count") is False:
        return counted(
            "pathao",
            status="unverified",
            total=None,
            delivered=None,
            failed_count=None,
        )
    delivered = first_count(customer, _DELIVERED_KEYS)
    if delivered is None:
        delivered = first_count(data, _DELIVERED_KEYS)
    total = first_count(customer, _TOTAL_KEYS)
    if total is None:
        total = first_count(data, _TOTAL_KEYS)
    failed_count = first_count(customer, _FAILED_KEYS)
    if failed_count is None:
        failed_count = first_count(data, _FAILED_KEYS)
    if delivered is None and total is None:
        return counted(
            "pathao",
            status="unverified",
            total=None,
            delivered=None,
            failed_count=None,
        )
    if delivered is not None and failed_count is None and total is not None:
        failed_count = max(total - delivered, 0)
    if delivered is None or failed_count is None:
        return failed("pathao", "Unexpected response")
    if total is None:
        total = delivered + failed_count
    return counted(
        "pathao",
        status="unverified",
        total=total,
        delivered=delivered,
        failed_count=failed_count,
    )


def _redx_token(response: httpx.Response) -> str | None:
    body = _json(response) or {}
    data = as_dict(body.get("data")) or {}
    for source in (data, body):
        for key in ("accessToken", "access_token", "token"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _redx_counts(response: httpx.Response) -> ProviderResult:
    body = _json(response)
    if body is None:
        return failed("redx", "Unexpected response")
    data = as_dict(body.get("data")) or body
    total = as_count(data.get("totalParcels"))
    delivered = as_count(data.get("deliveredParcels"))
    status = response.status_code
    dummy = total == 10 and delivered == 6
    if status == 400 and dummy:
        return failed("redx", "RedX customer lookup is unavailable")
    accepted = status == 200 or (
        status == 400 and body.get("code") == 200 and body.get("isError") is False and not dummy
    )
    if not accepted:
        return failed("redx", f"RedX returned HTTP {status}")
    if total is None or delivered is None or delivered > total:
        return failed("redx", "Unexpected response")
    return counted(
        "redx",
        status="unverified",
        total=total,
        delivered=delivered,
        failed_count=total - delivered,
    )


def _generic_block(response: httpx.Response) -> dict[str, Any] | None:
    body = _json(response)
    if body is None:
        return None
    data = as_dict(body.get("data"))
    if data is not None:
        summary = as_dict(data.get("totalSummary")) or as_dict(data.get("total_summary"))
        if summary is not None:
            return summary
        return data
    return body
