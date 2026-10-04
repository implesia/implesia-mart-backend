import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.models.user import UserRole
from app.schemas.user import UserCreate
from app.services import login_alert, user_service
from tests.conftest import TEST_PASSWORD


@pytest.fixture(autouse=True)
def _quiet_window() -> None:
    login_alert.clear()


def test_admin_email_alerts_once_per_window(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, dict[str, object]]] = []

    def capture(event: str, **kwargs: object) -> None:
        events.append((event, kwargs))

    monkeypatch.setattr(login_alert.logger, "error", capture)
    email = settings.first_superuser_email
    for _ in range(login_alert.ADMIN_THRESHOLD - 1):
        assert login_alert.record_failure(email, None) == []
    assert login_alert.record_failure(email, None) == ["admin"]
    assert login_alert.record_failure(email, None) == []

    assert len(events) == 1
    event, fields = events[0]
    assert event == "failed_login_alert"
    assert fields["kind"] == "admin"
    assert fields["email"] == email.lower()
    assert fields["failures"] == login_alert.ADMIN_THRESHOLD
    assert "password" not in fields


def test_any_account_alerts_on_a_wider_spike(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(login_alert.logger, "error", lambda event, **_kwargs: events.append(event))
    monkeypatch.setattr(login_alert, "SPIKE_THRESHOLD", 3)
    for _ in range(2):
        assert login_alert.record_failure("shopper@implesia.com", UserRole.EDITOR) == []
    assert login_alert.record_failure("shopper@implesia.com", UserRole.EDITOR) == ["spike"]
    assert events == ["failed_login_alert"]


def test_superadmin_role_counts_as_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        login_alert.logger,
        "error",
        lambda _event, **kwargs: events.append(kwargs),
    )
    monkeypatch.setattr(login_alert, "ADMIN_THRESHOLD", 1)
    raised = login_alert.record_failure("other@implesia.com", UserRole.SUPERADMIN)
    assert raised == ["admin"]
    assert events[0]["kind"] == "admin"
    assert events[0]["email"] == "other@implesia.com"


async def test_failed_login_is_counted_and_success_is_not(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, UserRole | None]] = []

    async def record(email: str, role: UserRole | None) -> None:
        seen.append((email, role))

    monkeypatch.setattr(user_service.login_alert, "note_failure", record)
    editor = await user_service.create_user(
        db_session,
        UserCreate(
            email="editor@implesia.com",
            full_name="Editor",
            password=TEST_PASSWORD,
            role=UserRole.EDITOR,
        ),
    )
    await user_service.authenticate(db_session, editor.email, TEST_PASSWORD)
    assert seen == []

    with pytest.raises(AuthenticationError):
        await user_service.authenticate(db_session, "missing@implesia.com", "not-the-password")
    assert seen == [("missing@implesia.com", None)]
