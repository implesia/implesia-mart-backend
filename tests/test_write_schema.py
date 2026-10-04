import importlib
import pkgutil

import pytest
from httpx import AsyncClient
from pydantic import BaseModel, ValidationError

from app.schemas.common import WriteModel
from app.schemas.contact.form import FormWrite

_PACKAGES = (
    "app.schemas.home",
    "app.schemas.about",
    "app.schemas.sustainability",
    "app.schemas.shipping",
    "app.schemas.privacy",
    "app.schemas.faqs",
    "app.schemas.contact",
    "app.schemas.blogs",
)


def _write_models() -> list[type[BaseModel]]:
    found: list[type[BaseModel]] = []
    for package_name in _PACKAGES:
        package = importlib.import_module(package_name)
        for module_info in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f"{package_name}.{module_info.name}")
            for obj in vars(module).values():
                if not isinstance(obj, type) or not issubclass(obj, BaseModel):
                    continue
                if obj.__module__ != module.__name__:
                    continue
                name = obj.__name__
                if name.endswith(("Write", "Update", "Reorder")) or name == "BannerSlideMove":
                    found.append(obj)
    return found


def test_cms_write_schemas_reject_unknown_fields() -> None:
    models = _write_models()
    assert len(models) == 133
    for model in models:
        assert issubclass(model, WriteModel)
        assert model.model_config.get("extra") == "forbid"


def test_nested_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        FormWrite.model_validate(
            {
                "title": "Write",
                "fields": {
                    "name": {
                        "label": "Name",
                        "placeholder": "Your name",
                        "unknown_field": "something",
                    }
                },
            }
        )


async def test_unknown_admin_field_returns_422(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/admin/home/trust",
        headers=auth_headers,
        json={"label": "Care", "unknown_field": "something"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
