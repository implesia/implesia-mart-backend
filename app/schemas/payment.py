from typing import Literal

from pydantic import BaseModel

StorePaymentMethod = Literal["cod", "bangla_qr"]
OfflinePaymentMethod = Literal["cash", "bkash", "nagad", "card", "due"]
AnyPaymentMethod = Literal["cod", "bangla_qr", "cash", "bkash", "nagad", "card", "due"]
# Checkout still accepts only the storefront methods.
PaymentMethod = StorePaymentMethod
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
