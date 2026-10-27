"""Phase 8 cross-cutting checks: link schemes, viewer write access, foreign-key indexes."""

import importlib
import re
from pathlib import Path

import pytest
from httpx import AsyncClient
from pydantic import BaseModel, ValidationError
from sqlalchemy import PrimaryKeyConstraint, UniqueConstraint

import app.models  # noqa: F401  (registers every table on the metadata)
import app.schemas as schemas_pkg
from app.db.base import Base
from app.main import app as fastapi_app
from app.schemas.common import WriteModel

_PARAM = "00000000-0000-4000-8000-000000000001"
_BAD_LINKS = (
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    " javascript:alert(1)",
    "java\tscript:alert(1)",
    "java\nscript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD4=",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "blob:https://x/1",
)


def _all_write_models() -> list[type[WriteModel]]:
    # Walk the files, not pkgutil: some schema folders (blogs, contact, faqs, privacy,
    # shipping) have no __init__.py and walk_packages silently skips them.
    root = Path(schemas_pkg.__path__[0])
    found: dict[str, type[WriteModel]] = {}
    for path in sorted(root.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        dotted = "app.schemas." + ".".join(path.relative_to(root).with_suffix("").parts)
        module = importlib.import_module(dotted)
        for obj in vars(module).values():
            if isinstance(obj, type) and issubclass(obj, WriteModel) and obj is not WriteModel:
                found[f"{obj.__module__}.{obj.__name__}"] = obj
    return list(found.values())


def _href_fields(model: type[BaseModel]) -> list[str]:
    return [n for n in model.model_fields if n == "href" or n.endswith("_href")]


def test_every_admin_href_field_rejects_script_schemes() -> None:
    covered = 0
    for model in _all_write_models():
        if model.href_checked_by_service:
            continue  # its service rejects the link with a section-specific message
        for field in _href_fields(model):
            for bad in _BAD_LINKS:
                with pytest.raises(ValidationError) as caught:
                    model.model_validate({field: bad})
                locs = {err["loc"] for err in caught.value.errors()}
                assert (field,) in locs, (model.__name__, field, bad)
            covered += 1
    assert covered >= 20, covered


def test_service_checked_schemas_are_the_known_set() -> None:
    # Each of these has a service-level `_safe_href` and its own endpoint test
    # (test_*_support / faq_help / shipping_faq / contact_details / contact_hero / blog_cta)
    # that posts a javascript: link and expects the specific message.
    exempt = sorted(m.__name__ for m in _all_write_models() if m.href_checked_by_service)
    assert exempt == sorted(
        [
            "ChannelWrite",
            "CtaWrite",
            "FaqWrite",
            "HeroLinkWrite",
            "HelpWrite",
            "LinkWrite",
            "SocialWrite",
            "SupportWrite",
            "SupportWrite",
        ]
    ), exempt


def test_ordinary_links_are_not_blocked_by_the_guard() -> None:
    class Probe(WriteModel):
        href: str = ""
        more_href: str = ""

    for ok in ("", "/products", "https://example.com/a?b=c", "mailto:a@b.co", "tel:+8801700000000"):
        assert Probe(href=ok, more_href=ok).href == ok


def test_a_non_link_field_is_left_alone() -> None:
    class Probe(WriteModel):
        title: str = ""

    assert Probe(title="data: a note about file: names").title.startswith("data:")


async def _viewer_headers(client: AsyncClient, auth_headers: dict[str, str]) -> dict[str, str]:
    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "qa-viewer@implesia.com",
            "full_name": "QA Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code in (200, 201), created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "qa-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_a_viewer_cannot_write_through_any_admin_route(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    viewer = await _viewer_headers(client, auth_headers)
    writes: list[tuple[str, str]] = []
    for path, operations in fastapi_app.openapi()["paths"].items():
        if not path.startswith(("/api/v1/admin", "/api/v1/users")):
            continue
        for method in operations:
            if method in {"post", "put", "patch", "delete"}:
                writes.append((method.upper(), re.sub(r"\{[^}]+\}", _PARAM, path)))
    assert len(writes) >= 40
    for method, path in writes:
        response = await client.request(method, path, headers=viewer)
        assert response.status_code == 403, (method, path, response.status_code)


def test_every_foreign_key_column_leads_an_index() -> None:
    missing: list[str] = []
    for table in Base.metadata.tables.values():
        leading: set[str] = set()
        for index in table.indexes:
            columns = list(index.columns)
            if columns:
                leading.add(columns[0].name)
        for constraint in table.constraints:
            if isinstance(constraint, (PrimaryKeyConstraint, UniqueConstraint)):
                leading.add(next(iter(constraint.columns)).name)
        for column in table.columns:
            if column.foreign_keys and column.name not in leading:
                missing.append(f"{table.name}.{column.name}")
    assert not missing, missing
