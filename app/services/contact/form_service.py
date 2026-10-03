from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.contact.form import ContactForm
from app.schemas.contact.form import (
    FormAdmin,
    FormField,
    FormFields,
    FormPublic,
    FormWrite,
)

SECTION_SLUG = "contact"
EMPTY = FormPublic(
    title="",
    subtitle="",
    cta="",
    hint="",
    fields=FormFields(
        name=FormField(label="", placeholder=""),
        phone=FormField(label="", placeholder=""),
        subject=FormField(label="", placeholder=""),
        message=FormField(label="", placeholder=""),
    ),
)


def _fields(row: ContactForm) -> FormFields:
    return FormFields(
        name=FormField(label=row.name_label, placeholder=row.name_placeholder),
        phone=FormField(label=row.phone_label, placeholder=row.phone_placeholder),
        subject=FormField(label=row.subject_label, placeholder=row.subject_placeholder),
        message=FormField(label=row.message_label, placeholder=row.message_placeholder),
    )


def present(row: ContactForm) -> FormAdmin:
    return FormAdmin(
        is_active=row.is_active,
        title=row.title,
        subtitle=row.subtitle,
        cta=row.cta,
        hint=row.hint,
        fields=_fields(row),
    )


def present_public(row: ContactForm) -> FormPublic:
    if not row.is_active or not row.title:
        return EMPTY
    shown = present(row)
    return FormPublic(
        title=shown.title,
        subtitle=shown.subtitle,
        cta=shown.cta,
        hint=shown.hint,
        fields=shown.fields,
    )


async def ensure_form(db: AsyncSession) -> ContactForm:
    row = await db.scalar(select(ContactForm).where(ContactForm.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = ContactForm(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> FormAdmin:
    return present(await ensure_form(db))


async def public_view(db: AsyncSession) -> FormPublic:
    return present_public(await ensure_form(db))


def _require_copy(payload: FormWrite) -> None:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    labels = (
        payload.fields.name.label,
        payload.fields.phone.label,
        payload.fields.subject.label,
        payload.fields.message.label,
    )
    if any(not label for label in labels):
        raise UnprocessableError("Each field needs a label.")
    if not payload.cta:
        raise UnprocessableError("Button label is required.")


async def update_form(db: AsyncSession, payload: FormWrite) -> FormAdmin:
    _require_copy(payload)
    row = await ensure_form(db)
    row.is_active = payload.is_active
    row.title = payload.title
    row.subtitle = payload.subtitle
    row.cta = payload.cta
    row.hint = payload.hint
    row.name_label = payload.fields.name.label
    row.name_placeholder = payload.fields.name.placeholder
    row.phone_label = payload.fields.phone.label
    row.phone_placeholder = payload.fields.phone.placeholder
    row.subject_label = payload.fields.subject.label
    row.subject_placeholder = payload.fields.subject.placeholder
    row.message_label = payload.fields.message.label
    row.message_placeholder = payload.fields.message.placeholder
    await db.commit()
    await db.refresh(row)
    return present(row)
