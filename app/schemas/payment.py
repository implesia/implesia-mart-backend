from typing import Literal

from pydantic import BaseModel

PaymentMethod = Literal["cod", "bangla_qr"]
AdvancePercent = Literal[25, 50, 75, 100]
ADVANCE_PERCENTS: tuple[int, ...] = (25, 50, 75, 100)


class PaymentSettingsPublic(BaseModel):
    """What the storefront needs. `bangla_qr_src` is null when no QR is set."""

    bangla_qr_src: str | None
    bangla_qr_enabled: bool


class PaymentSettingsAdmin(PaymentSettingsPublic):
    pass


class AdvanceOption(BaseModel):
    """One Bangla QR choice: pay `advance` now, `due` in cash on delivery."""

    percent: AdvancePercent
    advance: int
    due: int
