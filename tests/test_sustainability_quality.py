import json

from httpx import AsyncClient

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
)
PHOTO = "/images/products/lamp/lamp-3.jpg"
TITLE = "কোয়ালিটি নিশ্চয়তা প্রক্রিয়া"
STEPS = [
    "গ্যাজেট চালিয়ে ও ড্রেসের ফিনিশিং দেখে পরীক্ষা",
    "নিরাপদে প্যাক করে পাঠানো",
    "হাতে পেয়ে দেখে তারপর পেমেন্ট (COD)",
]


def _parts(
    body: dict, image_0: tuple[str, bytes, str] | None = None
) -> list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]]:
    parts: list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]] = [
        ("payload", (None, json.dumps(body)))
    ]
    if image_0 is not None:
        parts.append(("image_0", image_0))
    return parts


def _seed_body(**overrides: object) -> dict:
    body = {
        "title": TITLE,
        "body": "Seed body",
        "image": {"src": PHOTO, "alt": "সানসেট ল্যাম্প — কোয়ালিটি টেস্টেড প্রোডাক্ট"},
        "steps": [{"text": text, "is_active": True} for text in STEPS],
        "badges": [
            {"icon": "check_circle", "label": "চেক করে পাঠাই", "is_active": True},
            {"icon": "payments", "label": "ক্যাশ অন ডেলিভারি", "is_active": True},
        ],
    }
    body.update(overrides)
    return body


async def test_public_sustainability_quality_seeds_the_block(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/sustainability/quality")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == TITLE
    assert body["image"]["src"] == PHOTO
    assert [step["text"] for step in body["steps"]] == STEPS
    assert [badge["label"] for badge in body["badges"]] == ["চেক করে পাঠাই", "ক্যাশ অন ডেলিভারি"]
    assert body["badges"][0]["icon"] == "check_circle"
    assert "is_active" not in body["steps"][0]
    assert "is_active" not in body["badges"][0]


async def test_sustainability_quality_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/sustainability/quality")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "sustain-quality-viewer@implesia.com",
            "full_name": "Sustain Quality Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "sustain-quality-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.put(
        "/api/v1/admin/pages/sustainability/quality",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        files=_parts(_seed_body(title="Nope")),
    )
    assert denied.status_code == 403


async def test_editor_can_hide_upload_and_restore_quality(
    client: AsyncClient, auth_headers: dict[str, str], tmp_path, monkeypatch
) -> None:
    from app.core.config import settings
    from app.services.sustainability import quality_service

    monkeypatch.setattr(settings, "media_root", tmp_path)
    monkeypatch.setattr(quality_service, "MAX_STEPS", 3)
    blocked = await client.put(
        "/api/v1/admin/pages/sustainability/quality",
        headers=auth_headers,
        files=_parts(_seed_body(steps=[*[{"text": text} for text in STEPS], {"text": "Extra"}])),
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "You can add up to 12 steps"
    monkeypatch.setattr(quality_service, "MAX_STEPS", 12)

    blank = await client.put(
        "/api/v1/admin/pages/sustainability/quality",
        headers=auth_headers,
        files=_parts(_seed_body(title="   ")),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    missing_photo = await client.put(
        "/api/v1/admin/pages/sustainability/quality",
        headers=auth_headers,
        files=_parts(_seed_body(image={"src": "", "alt": ""})),
    )
    assert missing_photo.status_code == 422
    assert missing_photo.json()["error"]["message"] == "Cover photo is required."

    staged = await client.put(
        "/api/v1/admin/pages/sustainability/quality",
        headers=auth_headers,
        files=_parts(_seed_body(image={"src": "blob:quality", "alt": "Left"})),
    )
    assert staged.status_code == 422
    assert staged.json()["error"]["message"] == "Send the image file with the quality"

    empty_step = await client.put(
        "/api/v1/admin/pages/sustainability/quality",
        headers=auth_headers,
        files=_parts(_seed_body(steps=[{"text": "   "}])),
    )
    assert empty_step.status_code == 422
    assert empty_step.json()["error"]["message"] == "Write each step, or remove the empty one."

    empty_badge = await client.put(
        "/api/v1/admin/pages/sustainability/quality",
        headers=auth_headers,
        files=_parts(_seed_body(badges=[{"icon": "  ", "label": "   "}])),
    )
    assert empty_badge.status_code == 422
    assert empty_badge.json()["error"]["message"] == "Write each badge, or remove the empty one."

    hidden = await client.put(
        "/api/v1/admin/pages/sustainability/quality",
        headers=auth_headers,
        files=_parts(
            _seed_body(
                steps=[
                    {"text": STEPS[0], "is_active": True},
                    {"text": STEPS[1], "is_active": False},
                    {"text": STEPS[2], "is_active": True},
                ]
            )
        ),
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["steps"][1]["is_active"] is False
    public = await client.get("/api/v1/pages/sustainability/quality")
    assert [step["text"] for step in public.json()["steps"]] == [STEPS[0], STEPS[2]]

    uploaded = await client.put(
        "/api/v1/admin/pages/sustainability/quality",
        headers=auth_headers,
        files=_parts(
            _seed_body(image={"src": "", "alt": "Upload"}),
            ("quality.jpg", JPEG, "image/jpeg"),
        ),
    )
    assert uploaded.status_code == 200, uploaded.text
    stored = uploaded.json()["image"]["src"]
    assert stored.startswith("/media/sustainability/")
    assert (tmp_path / stored.removeprefix("/media/")).is_file()

    restored = await client.put(
        "/api/v1/admin/pages/sustainability/quality",
        headers=auth_headers,
        files=_parts(_seed_body()),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["image"]["src"] == PHOTO
    assert [step["text"] for step in restored.json()["steps"]] == STEPS
    assert not (tmp_path / stored.removeprefix("/media/")).exists()
