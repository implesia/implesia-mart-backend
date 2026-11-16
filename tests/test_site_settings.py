"""Storefront default SEO settings. Empty fields stay null so the frontend can fall back."""

from httpx import AsyncClient, Response

PUBLIC = "/api/v1/site/settings"
ADMIN = "/api/v1/admin/site/settings"
_KEYS = {"seo_title", "seo_description", "seo_title_template"}


def _fields(response: Response) -> set[str]:
    return {str(item["loc"][-1]) for item in response.json()["error"]["details"]}


async def test_public_settings_start_empty(client: AsyncClient) -> None:
    response = await client.get(PUBLIC)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "seo_title": None,
        "seo_description": None,
        "seo_title_template": None,
    }
    assert set(response.json()) == _KEYS
    assert response.headers["cache-control"] == "public, max-age=60"


async def test_admin_settings_require_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.get(ADMIN)).status_code == 401
    assert (await client.patch(ADMIN, json={"seo_title": "Home"})).status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "seo-viewer@implesia.com",
            "full_name": "SEO Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "seo-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    viewer = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get(ADMIN, headers=viewer)).status_code == 403
    denied = await client.patch(ADMIN, headers=viewer, json={"seo_title": "Home"})
    assert denied.status_code == 403

    admin = await client.get(ADMIN, headers=auth_headers)
    assert admin.status_code == 200
    assert admin.headers["cache-control"] == "no-store"
    assert admin.json()["seo_title"] is None


async def test_editor_saves_seo_and_the_public_read_follows(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.patch(
        ADMIN,
        headers=auth_headers,
        json={
            "seo_title": "  ইমপ্লেসিয়া   মার্ট ",
            "seo_description": "  Home   goods, delivered. ",
            "seo_title_template": "  %s   |   Implesia Mart ",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.headers["cache-control"] == "no-store"
    assert saved.json() == {
        "seo_title": "ইমপ্লেসিয়া মার্ট",
        "seo_description": "Home goods, delivered.",
        "seo_title_template": "%s | Implesia Mart",
    }

    public = await client.get(PUBLIC)
    assert public.json() == saved.json()
    assert public.headers["cache-control"] == "public, max-age=60"

    kept = await client.patch(
        ADMIN, headers=auth_headers, json={"seo_description": "A shorter line."}
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["seo_title"] == "ইমপ্লেসিয়া মার্ট"
    assert kept.json()["seo_description"] == "A shorter line."
    assert kept.json()["seo_title_template"] == "%s | Implesia Mart"

    cleared = await client.patch(
        ADMIN,
        headers=auth_headers,
        json={"seo_title": "", "seo_title_template": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json() == {
        "seo_title": None,
        "seo_description": "A shorter line.",
        "seo_title_template": None,
    }
    assert (await client.get(PUBLIC)).json()["seo_title"] is None


async def test_lengths_and_template_shape_are_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    ok = await client.patch(
        ADMIN, headers=auth_headers, json={"seo_title": "Keep me", "seo_description": "Stay"}
    )
    assert ok.status_code == 200, ok.text

    too_long = {
        "seo_title": "x" * 71,
        "seo_description": "y" * 171,
        "seo_title_template": "%s " + ("z" * 80),
    }
    for field, value in too_long.items():
        bad = await client.patch(ADMIN, headers=auth_headers, json={field: value})
        assert bad.status_code == 422, (field, bad.text)
        assert bad.json()["error"]["code"] == "validation_error"
        assert _fields(bad) == {field}

    for template in ("Implesia Mart", "%s | %s", "%s | 100%", "%d | Implesia"):
        bad = await client.patch(ADMIN, headers=auth_headers, json={"seo_title_template": template})
        assert bad.status_code == 422, (template, bad.text)
        assert _fields(bad) == {"seo_title_template"}

    exact = await client.patch(
        ADMIN,
        headers=auth_headers,
        json={
            "seo_title": "t" * 70,
            "seo_description": "d" * 170,
            "seo_title_template": "%s | " + ("b" * 75),
        },
    )
    assert exact.status_code == 200, exact.text
    assert len(exact.json()["seo_title"]) == 70
    assert len(exact.json()["seo_description"]) == 170
    assert len(exact.json()["seo_title_template"]) == 80

    unknown = await client.patch(
        ADMIN, headers=auth_headers, json={"seo_title": "Nope", "published": True}
    )
    assert unknown.status_code == 422, unknown.text
    current = await client.get(ADMIN, headers=auth_headers)
    assert current.json()["seo_title"] == "t" * 70
    assert current.json()["seo_description"] == "d" * 170
