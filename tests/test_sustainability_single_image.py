"""Sustainability sections carry one OPTIONAL photo (migration 0072).

Covers create/update with and without a photo for every section that has one, alt text
being required only when a photo is present, legacy ``images`` input, the ``image`` upload
key, the 0/1 ``images`` mirror and the one-photo DB constraint. About stays required.
"""

import json
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sustainability.hero import SustainabilityHero, SustainabilityHeroImage
from app.schemas.sustainability.optional_image import MISSING_ALT
from app.schemas.sustainability.origin import OriginWrite

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
)
LAMP = "/images/products/lamp/lamp-1.jpg"

BODIES: dict[str, dict] = {
    "hero": {"title": "QA hero"},
    "origin": {"title": "QA origin"},
    "quality": {"title": "QA quality", "steps": [], "badges": []},
    "durability": {"title": "QA durability", "bullets": []},
}


def _form(body: dict, upload_key: str | None = None) -> list:
    parts: list = [("payload", (None, json.dumps(body)))]
    if upload_key:
        parts.append((upload_key, ("photo.jpg", JPEG, "image/jpeg")))
    return parts


def _url(section: str, admin: bool = True) -> str:
    prefix = "/api/v1/admin/pages" if admin else "/api/v1/pages"
    return f"{prefix}/sustainability/{section}"


def _src(body: dict) -> str:
    image = body.get("image")
    return image["src"] if image else ""


@pytest.mark.parametrize("section", list(BODIES))
async def test_section_saves_without_a_photo(
    client: AsyncClient, auth_headers: dict[str, str], section: str
) -> None:
    # No `image` key at all, then an explicit null: both mean "no photo".
    for body in (BODIES[section], {**BODIES[section], "image": None}):
        saved = await client.put(_url(section), headers=auth_headers, files=_form(body))
        assert saved.status_code == 200, saved.text
        assert _src(saved.json()) == ""
        assert saved.json()["images"] == []
    public = await client.get(_url(section, admin=False))
    assert public.status_code == 200
    assert _src(public.json()) == ""
    assert public.json()["images"] == []
    assert public.json()["title"] == BODIES[section]["title"]


@pytest.mark.parametrize("section", list(BODIES))
async def test_section_saves_with_a_photo_and_requires_alt(
    client: AsyncClient, auth_headers: dict[str, str], section: str
) -> None:
    no_alt = await client.put(
        _url(section),
        headers=auth_headers,
        files=_form({**BODIES[section], "image": {"src": LAMP, "alt": "  "}}),
    )
    assert no_alt.status_code == 422
    assert no_alt.json()["error"]["message"] == MISSING_ALT

    # Alt text alone, with no photo, is not an error: there is simply no photo.
    alt_only = await client.put(
        _url(section),
        headers=auth_headers,
        files=_form({**BODIES[section], "image": {"src": "", "alt": "orphan"}}),
    )
    assert alt_only.status_code == 200, alt_only.text
    assert alt_only.json()["images"] == []

    saved = await client.put(
        _url(section),
        headers=auth_headers,
        files=_form({**BODIES[section], "image": {"src": LAMP, "alt": "Lamp"}}),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["image"]["src"] == LAMP
    assert saved.json()["image"]["alt"] == "Lamp"
    assert [item["src"] for item in saved.json()["images"]] == [LAMP]
    public = await client.get(_url(section, admin=False))
    assert _src(public.json()) == LAMP


@pytest.mark.parametrize("section", list(BODIES))
@pytest.mark.parametrize("key", ["image", "image_0"])
async def test_upload_then_remove_deletes_the_media(
    client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    key: str,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "media_root", tmp_path)
    upload_no_alt = await client.put(
        _url(section),
        headers=auth_headers,
        files=_form({**BODIES[section], "image": {"src": "", "alt": ""}}, key),
    )
    assert upload_no_alt.status_code == 422
    assert upload_no_alt.json()["error"]["message"] == MISSING_ALT
    folder = tmp_path / "sustainability"
    assert not folder.exists() or not any(folder.iterdir())  # failed upload cleaned up

    uploaded = await client.put(
        _url(section),
        headers=auth_headers,
        files=_form({**BODIES[section], "image": {"src": "", "alt": "Upload"}}, key),
    )
    assert uploaded.status_code == 200, uploaded.text
    src = uploaded.json()["image"]["src"]
    assert src.startswith("/media/sustainability/")
    stored = tmp_path / src.removeprefix("/media/")
    assert stored.is_file()

    removed = await client.put(_url(section), headers=auth_headers, files=_form(BODIES[section]))
    assert removed.status_code == 200, removed.text
    assert removed.json()["images"] == []
    assert not stored.exists()


def test_legacy_list_keeps_first_active_photo() -> None:
    model = OriginWrite.model_validate(
        {
            "title": "t",
            "images": [
                {"src": "/a.jpg", "alt": "A", "is_active": False},
                {"src": "/b.jpg", "alt": "B"},
                {"src": "/c.jpg", "alt": "C"},
            ],
        }
    )
    assert model.image is not None
    assert model.image.src == "/b.jpg"
    assert model.images == []
    hidden_only = OriginWrite.model_validate(
        {"title": "t", "images": [{"src": "/a.jpg", "alt": "A", "is_active": False}]}
    )
    assert hidden_only.image is None


async def test_legacy_two_photo_hero_payload_still_saves(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.put(
        _url("hero"),
        headers=auth_headers,
        files=_form(
            {
                "title": "Old admin",
                "images": [{"src": LAMP, "alt": "Left"}, {"src": "/x.jpg", "alt": "Right"}],
            }
        ),
    )
    assert saved.status_code == 200, saved.text
    assert [item["src"] for item in saved.json()["images"]] == [LAMP]


async def test_database_rejects_a_second_hero_photo(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.get(_url("hero", admin=False))  # seeds the hero and its photo
    hero = await db_session.scalar(select(SustainabilityHero))
    assert hero is not None
    db_session.add(SustainabilityHeroImage(hero_id=hero.id, src=LAMP, alt="x", sort_order=1))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_about_hero_still_requires_a_photo(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.put(
        "/api/v1/admin/pages/about/hero",
        headers=auth_headers,
        files=_form({"title": "About", "image": None}),
    )
    assert response.status_code == 422
