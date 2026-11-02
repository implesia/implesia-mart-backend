import json
import traceback
import uuid
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.deps import DbSession, RequireEditor, no_store, require_editor
from app.core.config import settings
from app.core.exceptions import ConflictError, UnprocessableError, payload_errors
from app.core.logging import get_logger
from app.rate_limit import limiter
from app.schemas.badge import MAX_PER_PRODUCT
from app.schemas.product import (
    MAX_VARIANTS,
    AdminProductList,
    AdminProductQuery,
    AdminProductRead,
    ProductCreate,
    ProductUpdate,
)
from app.services import category_service, product_service

router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])

_PAYLOAD_LIMIT = 200_000


def _model(
    raw: str, model: type[ProductCreate] | type[ProductUpdate]
) -> ProductCreate | ProductUpdate:
    if len(raw.encode("utf-8")) > _PAYLOAD_LIMIT:
        raise UnprocessableError("Product details are too large")
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        raise UnprocessableError("Request payload is invalid", payload_errors(exc)) from exc


def _alts(raw: str) -> list[str]:
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UnprocessableError("image_alts must be a JSON list") from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise UnprocessableError("image_alts must be a JSON list of strings")
    if len(parsed) > 12:
        raise UnprocessableError("A product can have at most 12 images")
    return parsed


@router.get("", response_model=AdminProductList)
async def list_products(
    db: DbSession,
    query: Annotated[AdminProductQuery, Depends()],
) -> AdminProductList:
    return await product_service.list_admin(db, query)


# --- Create-only error contract -------------------------------------------------------------
# POST /admin/products answers every problem as
#   {"errors": [{"field": <form field key>, "message": <Bengali>, "fix": <Bengali>}]}
# with 400 (invalid input), 409 (duplicate) or 500 (unexpected). Field keys match the admin
# product form. Other endpoints keep the shared {"error": {...}} envelope.

FieldError = dict[str, str]

_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
_SERVER_ERROR: FieldError = {
    "field": "form",
    "message": "সার্ভারে একটা অপ্রত্যাশিত সমস্যা হয়েছে, প্রোডাক্টটি সেভ হয়নি।",
    "fix": "একটু পরে আবার চেষ্টা করুন। বারবার হলে টেকনিক্যাল টিমকে জানান।",
}
_logger = get_logger("admin_products")


def _bn(value: int) -> str:
    return f"{value:,}".translate(_BN_DIGITS)


def _err(field: str, message: str, fix: str) -> FieldError:
    return {"field": field, "message": message, "fix": fix}


def _errors_response(code: int, errors: list[FieldError]) -> JSONResponse:
    unique: list[FieldError] = []
    for item in errors:
        if item not in unique:
            unique.append(item)
    return JSONResponse(status_code=code, content={"errors": unique})


# Schema keys -> admin form field keys.
_FIELD_KEYS: Mapping[str, str] = {
    "title": "title",
    "subtitle": "subtitle",
    "category": "category",
    "category_id": "category",
    "price": "price",
    "compare_at_price": "compareAtPrice",
    "quantity": "quantity",
    "status": "status",
    "badge": "badges",
    "badge_ids": "badges",
    "image_src": "images",
    "featured": "publishing",
    "published": "publishing",
    "slug": "slug",
    "min_order_quantity": "orderLimits",
    "max_order_quantity": "orderLimits",
    "variants": "variants",
}
_IMAGE_CONTENT = {"gallery", "image_alt", "quality_image_src", "quality_image_alt"}


def _field_of(loc: tuple[Any, ...]) -> str:
    if not loc:
        return "form"
    head = str(loc[0])
    if head == "content":
        return "images" if len(loc) > 1 and str(loc[1]) in _IMAGE_CONTENT else "content"
    return _FIELD_KEYS.get(head, "form")


_LABELS = {
    "title": "প্রোডাক্টের নাম",
    "subtitle": "সাবটাইটেল",
    "category": "ক্যাটাগরি",
    "price": "দাম",
    "compareAtPrice": "আগের দাম (compare-at)",
    "quantity": "স্টকের পরিমাণ",
    "status": "স্টক স্ট্যাটাস",
    "badges": "ব্যাজ",
    "images": "ছবি",
    "publishing": "পাবলিশ সেটিং",
    "slug": "স্লাগ",
    "orderLimits": "অর্ডারের সীমা",
    "variants": "ভ্যারিয়েন্ট",
    "content": "প্রোডাক্টের বিস্তারিত",
    "form": "ফর্মের তথ্য",
}

# Messages raised by model validators, the schema, or the product/badge/variant/image services.
_KNOWN: Mapping[str, FieldError] = {
    "Product name is required": _err(
        "title", "প্রোডাক্টের নাম দিতে হবে", "একটা নাম লিখুন, যেমন “কটন টি-শার্ট”"
    ),
    # Price and category are required only to publish; a draft needs just the name.
    "Price is required": _err("price", "দাম দিতে হবে", "০ বা তার বেশি একটা পূর্ণ সংখ্যা লিখুন (টাকায়)"),
    "Compare-at price must be at least the selling price": _err(
        "compareAtPrice",
        "আগের দাম বিক্রির দামের চেয়ে কম হতে পারে না",
        "বিক্রির দামের সমান বা বেশি একটা দাম লিখুন, অথবা ঘরটা খালি রাখুন",
    ),
    "Choose a category": _err("category", "ক্যাটাগরি বাছাই করতে হবে", "তালিকা থেকে একটা ক্যাটাগরি বাছাই করুন"),
    "Category not found": _err(
        "category",
        "বাছাই করা ক্যাটাগরিটা আর নেই",
        "পেজটা রিফ্রেশ করে আবার একটা ক্যাটাগরি বাছাই করুন",
    ),
    "Category must be a slug such as gadgets": _err(
        "category", "ক্যাটাগরি সঠিক নয়", "তালিকা থেকে একটা ক্যাটাগরি বাছাই করুন"
    ),
    "Maximum order quantity must be at least the minimum": _err(
        "orderLimits",
        "সর্বোচ্চ অর্ডার সর্বনিম্ন অর্ডারের চেয়ে কম হতে পারে না",
        "সর্বোচ্চ সংখ্যাটা সর্বনিম্নের সমান বা বেশি দিন, অথবা খালি রাখুন",
    ),
    "Slug must use lowercase letters, numbers, and hyphens": _err(
        "slug", "স্লাগ সঠিক নয়", "শুধু ছোট হাতের ইংরেজি অক্ষর, সংখ্যা আর হাইফেন (-) ব্যবহার করুন"
    ),
    "Add a product image": _err("images", "প্রোডাক্টের ছবি দিতে হবে", "অন্তত একটা ছবি আপলোড করুন"),
    "A product can have at most 12 images": _err(
        "images", "ছবি অনেক বেশি হয়ে গেছে", "সর্বোচ্চ ১২টা ছবি রাখুন, বাড়তিগুলো সরিয়ে দিন"
    ),
    "Image must be a JPEG, PNG, WEBP, or GIF": _err(
        "images", "এই ধরনের ছবি নেওয়া যায় না", "JPEG, PNG, WEBP বা GIF ছবি আপলোড করুন"
    ),
    "Image is too large": _err(
        "images",
        "ছবির সাইজ অনেক বড়",
        f"{_bn(settings.max_image_bytes // (1024 * 1024))} MB-এর ছোট ছবি আপলোড করুন",
    ),
    "Video must be an MP4 or WEBM file": _err(
        "images", "এই ধরনের ভিডিও নেওয়া যায় না", "MP4 বা WEBM ভিডিও আপলোড করুন"
    ),
    "Video is too large": _err(
        "images",
        "ভিডিওর সাইজ অনেক বড়",
        f"{_bn(settings.max_video_bytes // (1024 * 1024))} MB-এর ছোট ভিডিও আপলোড করুন",
    ),
    "Video is empty": _err("images", "ভিডিও ফাইলটা খালি", "অন্য একটা ভিডিও বাছাই করে আবার আপলোড করুন"),
    "YouTube link is not valid": _err(
        "images",
        "YouTube লিংকটা সঠিক নয়",
        "youtube.com/watch?v=..., youtu.be/... বা shorts লিংক দিন",
    ),
    "Image is empty": _err("images", "ছবির ফাইলটা খালি", "অন্য একটা ছবি বাছাই করে আবার আপলোড করুন"),
    "Image text is invalid": _err(
        "images", "ছবির বিবরণ (alt text) সঠিক নয়", "ছবির বিবরণ ছোট আর সাধারণ লেখায় দিন"
    ),
    "Image address is not allowed": _err(
        "images", "ছবির ঠিকানাটা গ্রহণযোগ্য নয়", "ছবিটা সরাসরি আপলোড করুন"
    ),
    "Image address is too long": _err("images", "ছবির ঠিকানাটা অনেক বড়", "ছবিটা সরাসরি আপলোড করুন"),
    "Image address must be a site path or an https URL": _err(
        "images", "ছবির ঠিকানাটা সঠিক নয়", "ছবিটা সরাসরি আপলোড করুন, অথবা https লিংক দিন"
    ),
    "image_alts must be a JSON list": _err(
        "images", "ছবির বিবরণের তালিকা সঠিক নয়", "পেজটা রিফ্রেশ করে ছবিগুলো আবার যোগ করুন"
    ),
    "image_alts must be a JSON list of strings": _err(
        "images", "ছবির বিবরণের তালিকা সঠিক নয়", "পেজটা রিফ্রেশ করে ছবিগুলো আবার যোগ করুন"
    ),
    "Product details are too large": _err(
        "content", "প্রোডাক্টের বিস্তারিত লেখা অনেক বড়", "বিবরণ, FAQ বা স্পেসিফিকেশন একটু ছোট করুন"
    ),
    "Request payload is invalid": _err("form", "ফর্মের তথ্য পড়া যায়নি", "পেজটা রিফ্রেশ করে আবার চেষ্টা করুন"),
    f"A product can have at most {MAX_PER_PRODUCT} badges": _err(
        "badges",
        "ব্যাজ অনেক বেশি হয়ে গেছে",
        f"সর্বোচ্চ {_bn(MAX_PER_PRODUCT)}টা ব্যাজ রাখুন",
    ),
    "One or more badges no longer exist": _err(
        "badges",
        "একটা বা একাধিক ব্যাজ আর নেই",
        "ব্যাজের তালিকা থেকে সেগুলো সরিয়ে আবার বাছাই করুন",
    ),
    "Option names must be different": _err(
        "content", "দুটো অপশনের নাম একই", "প্রতিটা অপশনের (যেমন সাইজ, রং) আলাদা নাম দিন"
    ),
    "Color must be a hex color like #111827": _err(
        "content", "রঙের কোড সঠিক নয়", "#111827-এর মতো হেক্স কোড দিন"
    ),
    "Each variant needs one value for every option": _err(
        "variants", "প্রতিটা ভ্যারিয়েন্টে সব অপশনের মান দিতে হবে", "খালি থাকা অপশনগুলো বাছাই করুন"
    ),
    "Add option values (such as sizes or weights) before variants": _err(
        "variants",
        "ভ্যারিয়েন্টের আগে অপশনের মান দিতে হবে",
        "অপশন অংশে সাইজ বা ওজনের মতো মান যোগ করুন",
    ),
    "Two variants have the same option combination": _err(
        "variants", "দুটো ভ্যারিয়েন্ট একই রকম", "একই অপশন-জোড়ার একটা ভ্যারিয়েন্ট সরিয়ে দিন"
    ),
    "Two variants have the same SKU": _err(
        "variants", "দুটো ভ্যারিয়েন্টের SKU একই", "প্রতিটা ভ্যারিয়েন্টকে আলাদা SKU দিন"
    ),
    "A variant was listed twice": _err(
        "variants", "একটা ভ্যারিয়েন্ট দুবার আছে", "পুনরাবৃত্ত ভ্যারিয়েন্টটা সরিয়ে দিন"
    ),
    "Option ids are not valid": _err(
        "variants", "ভ্যারিয়েন্টের অপশন সঠিক নয়", "ভ্যারিয়েন্টগুলো আবার তৈরি করুন"
    ),
    "SKU cannot contain | or =": _err(
        "variants", "SKU-তে | বা = চিহ্ন থাকতে পারে না", "চিহ্নগুলো বাদ দিয়ে SKU লিখুন"
    ),
}

_CONFLICTS: Mapping[str, FieldError] = {
    "A product with this slug already exists": _err(
        "title",
        "এই নামের (একই slug) একটা প্রোডাক্ট আগে থেকেই আছে",
        "নামটা একটু বদলে দিন, যেমন রং বা সাইজ যোগ করুন",
    ),
    "A variant SKU or option combination is already in use": _err(
        "variants",
        "এই SKU বা অপশন-জোড়া আগে থেকেই ব্যবহার হচ্ছে",
        "প্রতিটা ভ্যারিয়েন্টকে আলাদা SKU দিন",
    ),
    "A variant SKU is already used by another product": _err(
        "variants",
        "এই SKU অন্য একটা প্রোডাক্টে ব্যবহার হচ্ছে",
        "ভ্যারিয়েন্টের জন্য নতুন, আলাদা SKU দিন",
    ),
}


def _known(message: str) -> FieldError | None:
    if message in _KNOWN:
        return _KNOWN[message]
    if message.startswith("Choose a valid ") and message.endswith(" for each variant"):
        return _err("variants", "ভ্যারিয়েন্টের অপশন সঠিক নয়", "প্রতিটা ভ্যারিয়েন্টে তালিকা থেকে মান বাছাই করুন")
    if message.startswith("Must be at most ") and message.endswith(" characters"):
        limit = message.removeprefix("Must be at most ").removesuffix(" characters")
        if limit.isdigit():
            return _err("", "লেখাটা অনেক বড়", f"{_bn(int(limit))} অক্ষরের মধ্যে রাখুন")
    return None


def _numeric(field: str, kind: str, ctx: Mapping[str, Any]) -> FieldError | None:
    label = _LABELS.get(field, "সংখ্যাটা")
    integer_fix = "শুধু পূর্ণ সংখ্যা লিখুন, যেমন ৫০০"
    if field in {"price", "compareAtPrice"}:
        integer_fix = "টাকার পরিমাণ পূর্ণ সংখ্যায় লিখুন, যেমন ৫০০"
    if kind in {"int_parsing", "int_type", "int_from_float", "float_parsing"}:
        return _err(field, f"{label} সংখ্যায় দিতে হবে", integer_fix)
    if kind == "greater_than_equal":
        floor = int(ctx.get("ge", 0))
        return _err(
            field, f"{label} {_bn(floor)}-এর কম হতে পারে না", f"{_bn(floor)} বা তার বেশি একটা সংখ্যা লিখুন"
        )
    if kind == "less_than_equal":
        top = int(ctx.get("le", 0))
        return _err(field, f"{label} অনেক বেশি", f"{_bn(top)}-এর মধ্যে একটা সংখ্যা লিখুন")
    return None


_REQUIRED: Mapping[str, FieldError] = {
    "title": _KNOWN["Product name is required"],
    "price": _KNOWN["Price is required"],
}


def _from_validation(exc: ValidationError) -> list[FieldError]:
    errors: list[FieldError] = []
    for raw in exc.errors(include_url=False, include_input=False):
        loc = tuple(raw.get("loc", ()))
        kind = str(raw.get("type", ""))
        ctx = raw.get("ctx") or {}
        field = _field_of(loc)
        label = _LABELS.get(field, "তথ্যটা")
        message = str(raw.get("msg", "")).removeprefix("Value error, ")
        known = _known(message)
        if known is not None:
            errors.append(known if known["field"] else {**known, "field": field})
            continue
        if kind == "json_invalid":
            errors.append(_KNOWN["Request payload is invalid"])
        elif kind == "missing":
            errors.append(
                _REQUIRED.get(field) or _err(field, f"{label} দিতে হবে", "ঘরটা পূরণ করে আবার চেষ্টা করুন")
            )
        elif (numeric := _numeric(field, kind, ctx)) is not None:
            errors.append(numeric)
        elif kind in {"too_long", "string_too_long"} and field == "variants":
            errors.append(
                _err(field, "ভ্যারিয়েন্ট অনেক বেশি", f"সর্বোচ্চ {_bn(MAX_VARIANTS)}টা ভ্যারিয়েন্ট রাখুন")
            )
        elif kind in {"too_long", "string_too_long"} and field == "badges":
            errors.append(_KNOWN[f"A product can have at most {MAX_PER_PRODUCT} badges"])
        elif kind in {"too_long", "string_too_long"}:
            errors.append(_err(field, f"{label} অনেক বড়", "লেখা বা তালিকাটা একটু ছোট করুন"))
        elif kind in {"uuid_parsing", "uuid_type"}:
            errors.append(_err(field, f"{label} সঠিক নয়", "পেজটা রিফ্রেশ করে তালিকা থেকে আবার বাছাই করুন"))
        elif kind == "enum":
            errors.append(_err(field, f"{label} সঠিক নয়", "তালিকার একটা অপশন বাছাই করুন"))
        elif kind == "extra_forbidden":
            errors.append(
                _err("form", "ফর্মে অজানা একটা তথ্য পাঠানো হয়েছে", "পেজটা রিফ্রেশ করে আবার চেষ্টা করুন")
            )
        else:
            errors.append(_err(field, f"{label} সঠিক নয়", "তথ্যটা দেখে ঠিক করে আবার চেষ্টা করুন"))
    return errors


def _cross_field(payload: str) -> list[FieldError]:
    """The model-level checks are skipped when a field fails, so report what publishing needs."""
    try:
        raw = json.loads(payload)
    except ValueError:
        return []
    if not isinstance(raw, dict) or raw.get("published") is not True:
        return []  # A draft needs only its name.
    errors: list[FieldError] = []
    if "price" not in raw and not raw.get("variants"):
        errors.append(_KNOWN["Price is required"])
    if not raw.get("category_id") and not raw.get("category"):
        errors.append(_KNOWN["Choose a category"])
    return errors


def _from_app_error(exc: UnprocessableError | ConflictError, slug_sent: bool) -> FieldError:
    if isinstance(exc, ConflictError):
        found = _CONFLICTS.get(exc.message)
        if found is None:
            return _err("form", "একই রকম একটা প্রোডাক্ট আগে থেকেই আছে", "তথ্যগুলো বদলে আবার চেষ্টা করুন")
        if slug_sent and found["field"] == "title":
            return {**found, "field": "slug", "fix": "অন্য একটা স্লাগ দিন"}
        return found
    known = _known(exc.message)
    if known is not None:
        return known if known["field"] else {**known, "field": "form"}
    if exc.message.startswith("Choose a valid"):
        return _err("variants", "ভ্যারিয়েন্টের অপশন সঠিক নয়", "প্রতিটা ভ্যারিয়েন্টে তালিকা থেকে মান বাছাই করুন")
    return _err("form", "কিছু তথ্য সঠিক নয়", "ফর্মটা দেখে ঠিক করে আবার চেষ্টা করুন")


def _where(exc: BaseException) -> str:
    """File, line and function of the failing frame. No values, so nothing sensitive is logged."""
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return ""
    last = frames[-1]
    return f"{last.filename.rsplit('/', 1)[-1]}:{last.lineno} in {last.name}"


@router.post(
    "",
    response_model=AdminProductRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "Invalid input: {errors: [{field, message, fix}]}"},
        409: {"description": "Duplicate product or SKU, same shape"},
        500: {"description": "Unexpected error, same shape with a generic message"},
    },
)
@limiter.limit(settings.rate_limit_product_writes)
async def create_product(
    request: Request,
    db: DbSession,
    payload: Annotated[str, Form()] = "",
    images: Annotated[list[UploadFile] | None, File()] = None,
    image_alts: Annotated[str, Form()] = "[]",
    quality_image: Annotated[UploadFile | None, File()] = None,
    quality_image_alt: Annotated[str, Form()] = "",
    videos: Annotated[list[UploadFile] | None, File()] = None,
    video_alts: Annotated[str, Form()] = "[]",
) -> AdminProductRead | JSONResponse:
    del request
    if not payload.strip():
        return _errors_response(400, [_KNOWN["Request payload is invalid"]])
    if len(payload.encode("utf-8")) > _PAYLOAD_LIMIT:
        return _errors_response(400, [_KNOWN["Product details are too large"]])
    try:
        data = ProductCreate.model_validate_json(payload)
    except ValidationError as exc:
        return _errors_response(400, _from_validation(exc) + _cross_field(payload))
    try:
        alts = _alts(image_alts)
        product = await product_service.create_product(
            db,
            data,
            images,
            alts,
            quality_image,
            quality_image_alt,
            videos=videos,
            video_alts=_alts(video_alts),
        )
        return await product_service.admin_read_full(
            db, product, await category_service.load_index(db)
        )
    except ConflictError as exc:
        return _errors_response(409, [_from_app_error(exc, data.slug is not None)])
    except UnprocessableError as exc:
        return _errors_response(400, [_from_app_error(exc, data.slug is not None)])
    except Exception as exc:
        await db.rollback()
        _logger.error("product_create_failed", error_type=type(exc).__name__, where=_where(exc))
        return _errors_response(500, [_SERVER_ERROR])


@router.get("/{product_id}", response_model=AdminProductRead)
async def read_product(db: DbSession, product_id: uuid.UUID) -> AdminProductRead:
    product = await product_service.get_by_id(db, product_id)
    return await product_service.admin_read_full(db, product, await category_service.load_index(db))


@router.patch("/{product_id}", response_model=AdminProductRead)
@limiter.limit(settings.rate_limit_product_writes)
async def update_product(
    request: Request,
    db: DbSession,
    actor: RequireEditor,
    product_id: uuid.UUID,
    payload: Annotated[str, Form()] = "{}",
    images: Annotated[list[UploadFile] | None, File()] = None,
    image_alts: Annotated[str, Form()] = "[]",
    quality_image: Annotated[UploadFile | None, File()] = None,
    quality_image_alt: Annotated[str, Form()] = "",
    videos: Annotated[list[UploadFile] | None, File()] = None,
    video_alts: Annotated[str, Form()] = "[]",
) -> AdminProductRead:
    del request
    data = _model(payload, ProductUpdate)
    assert isinstance(data, ProductUpdate)
    product = await product_service.get_by_id(db, product_id)
    updated = await product_service.update_product(
        db,
        product,
        data,
        images,
        _alts(image_alts),
        quality_image,
        quality_image_alt,
        actor=actor,
        videos=videos,
        video_alts=_alts(video_alts),
    )
    return await product_service.admin_read_full(db, updated, await category_service.load_index(db))


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(db: DbSession, product_id: uuid.UUID) -> None:
    product = await product_service.get_by_id(db, product_id)
    await product_service.delete_product(db, product)
