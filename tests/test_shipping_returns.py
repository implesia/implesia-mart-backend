from httpx import AsyncClient


def _body(
    *,
    active: bool = True,
    heading: str = "Returns and exchanges",
    rule: str = "The item must be unused.",
    title: str = "Gadgets",
) -> dict:
    return {
        "is_active": active,
        "icon": "assignment_return",
        "nav_label": "Returns",
        "heading": heading,
        "eligibility_title": "3-day easy return",
        "eligibility_body": "Defects can be returned within 3 days of delivery.",
        "rules": [{"text": rule, "is_active": True}],
        "notes": [
            {
                "icon": "devices",
                "title": title,
                "body": "Manufacturing defects are replaced.",
                "is_active": True,
            }
        ],
    }


async def test_public_shipping_returns_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/shipping/returns")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["heading"] == ""
    assert body["eligibility_title"] == ""
    assert body["rules"] == []
    assert body["notes"] == []
    assert "is_active" not in body
    assert "রিটার্ন ও এক্সচেঞ্জ" not in response.text
    assert "৩ দিনের ইজি রিটার্ন" not in response.text
    assert "প্রোডাক্ট অব্যবহৃত ও আসল অবস্থায় থাকতে হবে" not in response.text
    assert "যা রিটার্নযোগ্য নয়" not in response.text


async def test_shipping_returns_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/shipping/returns")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "shipping-return-viewer@implesia.com",
            "full_name": "Shipping Return Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "shipping-return-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/shipping/returns",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_keeps_return_item_ids(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/shipping/returns",
        headers=auth_headers,
        json=_body(heading="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Heading is required."

    missing = await client.patch(
        "/api/v1/admin/pages/shipping/returns",
        headers=auth_headers,
        json=_body(rule="   "),
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["message"] == (
        "Fill in every rule and note, or remove the empty ones."
    )

    saved = await client.patch(
        "/api/v1/admin/pages/shipping/returns",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    rule_id = saved.json()["rules"][0]["id"]
    assert saved.json()["heading"] == "Returns and exchanges"
    assert saved.json()["eligibility_title"] == "3-day easy return"

    public = await client.get("/api/v1/pages/shipping/returns")
    assert public.json()["heading"] == "Returns and exchanges"
    assert public.json()["rules"][0]["text"] == "The item must be unused."
    assert public.json()["notes"][0]["title"] == "Gadgets"
    assert "is_active" not in public.json()
    assert "is_active" not in public.json()["rules"][0]

    kept = await client.patch(
        "/api/v1/admin/pages/shipping/returns",
        headers=auth_headers,
        json={
            **_body(),
            "rules": [{**saved.json()["rules"][0], "text": "Unused and in original condition."}],
        },
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["rules"][0]["id"] == rule_id
    assert kept.json()["rules"][0]["text"] == "Unused and in original condition."

    hidden = await client.patch(
        "/api/v1/admin/pages/shipping/returns",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/shipping/returns")
    assert cleared.json()["heading"] == ""
    assert cleared.json()["rules"] == []
    assert cleared.json()["notes"] == []
