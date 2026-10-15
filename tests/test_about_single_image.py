"""About hero, story and custom-dress blocks carry exactly one photo."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.about.hero import AboutHero, AboutHeroImage
from app.schemas.about.dress import DressWrite
from app.schemas.about.hero import AboutHeroWrite
from app.schemas.about.single_image import MISSING_ALT, MISSING_PHOTO
from app.schemas.about.story import StoryWrite

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
)
LAMP = "/images/products/lamp/lamp-1.jpg"
GOWN = "/images/products/baby-products/wedding-dress.jpeg"


def _form(body: dict, upload_key: str | None = None) -> list:
    parts: list = [("payload", (None, json.dumps(body)))]
    if upload_key:
        parts.append((upload_key, ("photo.jpg", JPEG, "image/jpeg")))
    return parts


def _hero(**overrides: object) -> dict:
    body: dict = {"title": "Hero", "image": {"src": LAMP, "alt": "Lamp"}}
    body.update(overrides)
    return body


def _story(**overrides: object) -> dict:
    body: dict = {
        "title": "Story",
        "paragraphs": [{"text": "Text"}],
        "is_active": False,
        "image": {"src": LAMP, "alt": "Lamp"},
    }
    body.update(overrides)
    return body


def _dress(**overrides: object) -> dict:
    body: dict = {"title": "Dress", "is_active": False, "image": {"src": GOWN, "alt": "Gown"}}
    body.update(overrides)
    return body


@pytest.mark.parametrize("model", [AboutHeroWrite, StoryWrite, DressWrite])
def test_legacy_images_list_folds_into_the_single_image(
    model: type[AboutHeroWrite] | type[StoryWrite] | type[DressWrite],
) -> None:
    parsed = model.model_validate(
        {"title": "T", "images": [{"src": LAMP, "alt": "first"}, {"src": GOWN, "alt": "second"}]}
    )
    assert parsed.image is not None
    assert (parsed.image.src, parsed.image.alt) == (LAMP, "first")
    assert parsed.images == []


async def test_public_payloads_expose_one_image_and_a_one_item_mirror(client: AsyncClient) -> None:
    hero = (await client.get("/api/v1/pages/about/hero")).json()
    stories = (await client.get("/api/v1/pages/about/stories")).json()["items"]
    dresses = (await client.get("/api/v1/pages/about/dresses")).json()["items"]
    for item in (hero, *stories, *dresses):
        assert item["image"] is not None
        assert item["images"] == [item["image"]]


@pytest.mark.parametrize(
    ("method", "path", "factory"),
    [
        ("PUT", "/api/v1/admin/pages/about/hero", _hero),
        ("POST", "/api/v1/admin/pages/about/stories", _story),
        ("POST", "/api/v1/admin/pages/about/dresses", _dress),
    ],
)
async def test_photo_and_alt_text_are_required(
    client: AsyncClient,
    auth_headers: dict[str, str],
    method: str,
    path: str,
    factory: Callable[..., dict],
) -> None:
    no_photo = await client.request(
        method, path, headers=auth_headers, files=_form(factory(image=None))
    )
    assert no_photo.status_code == 422, no_photo.text
    assert no_photo.json()["error"]["message"] == MISSING_PHOTO

    blank_src = await client.request(
        method, path, headers=auth_headers, files=_form(factory(image={"src": " ", "alt": "x"}))
    )
    assert blank_src.json()["error"]["message"] == MISSING_PHOTO

    no_alt = await client.request(
        method, path, headers=auth_headers, files=_form(factory(image={"src": LAMP, "alt": " "}))
    )
    assert no_alt.status_code == 422
    assert no_alt.json()["error"]["message"] == MISSING_ALT


@pytest.mark.parametrize("upload_key", ["image", "image_0"])
async def test_upload_replaces_the_photo_under_either_field_name(
    client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    upload_key: str,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "media_root", tmp_path)
    created = await client.post(
        "/api/v1/admin/pages/about/dresses",
        headers=auth_headers,
        files=_form(_dress(image={"src": "", "alt": "Uploaded gown"}), upload_key),
    )
    assert created.status_code == 201, created.text
    dress = created.json()
    assert dress["image"]["src"].startswith("/media/about/")
    assert dress["image"]["alt"] == "Uploaded gown"
    assert len(dress["images"]) == 1

    swapped = await client.patch(
        f"/api/v1/admin/pages/about/dresses/{dress['id']}",
        headers=auth_headers,
        files=_form(_dress(image={"src": GOWN, "alt": "Seed gown"})),
    )
    assert swapped.status_code == 200, swapped.text
    assert swapped.json()["image"] == {**dress["image"], "src": GOWN, "alt": "Seed gown"}
    stored = tmp_path / "about" / dress["image"]["src"].removeprefix("/media/about/")
    assert not stored.exists()


async def test_database_rejects_a_second_photo(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.get("/api/v1/pages/about/hero")  # seeds the hero and its photo
    hero = await db_session.scalar(select(AboutHero))
    assert hero is not None
    db_session.add(AboutHeroImage(hero_id=hero.id, src=GOWN, alt="extra", sort_order=1))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
