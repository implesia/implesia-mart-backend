"""Query normalisation and the SQL predicates behind public search.

One place decides what a search term is and which columns it may match, so the public
catalog filter (`/products?q=`), the global search endpoint and the tests agree.

Matching is case-insensitive substring matching on whole words typed by the shopper: every
word must match somewhere (AND between words, OR between columns). That works the same for
Latin and Bangla text, which has no case and which PostgreSQL's built-in text-search
configurations cannot stem. Parameters are always bound; LIKE wildcards in the term are escaped.
"""

import re
import unicodedata
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, String, and_, case, exists, literal, or_, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.expression import FunctionElement

from app.models.blogs.posts import BlogPost, BlogPostBlock
from app.models.category import Category
from app.models.product import Product


class json_text(FunctionElement):  # noqa: N801  (SQL-function naming)
    """A JSON column as searchable text.

    PostgreSQL keeps a plain `json` value exactly as the driver wrote it, with Bangla letters
    escaped as `\\uXXXX`. Going through `jsonb` decodes them, so Bangla tags are matchable.
    """

    type = String()
    inherit_cache = True


@compiles(json_text)
def _json_text_default(element: json_text, compiler: Any, **kw: Any) -> str:
    return f"CAST({compiler.process(element.clauses, **kw)} AS VARCHAR)"


@compiles(json_text, "postgresql")
def _json_text_postgresql(element: json_text, compiler: Any, **kw: Any) -> str:
    return f"CAST(CAST({compiler.process(element.clauses, **kw)} AS JSONB) AS TEXT)"


MAX_QUERY_CHARS = 100
MAX_TOKENS = 6
MAX_TOKEN_CHARS = 60

_EDGE_PUNCTUATION = ".,;:!?\"'`()[]{}<>|\\/*+=~^-_#@&$%"
_SPACES = re.compile(r"\s+")

_Expr = ColumnElement[Any]


def normalize_query(raw: str | None) -> str:
    """NFC, no control characters, single spaces. Never changes letters or Bangla marks."""
    if not raw:
        return ""
    text = unicodedata.normalize("NFC", raw)
    # Control and format characters (except the joiners Bangla conjuncts need) become spaces.
    cleaned = "".join(
        " "
        if (unicodedata.category(ch) in {"Cc", "Cs", "Zl", "Zp"} or ch in "\u200b\ufeff")
        else ch
        for ch in text
    )
    return _SPACES.sub(" ", cleaned).strip()[:MAX_QUERY_CHARS].strip()


def tokenize(raw: str | None) -> list[str]:
    """Distinct lower-case words, punctuation trimmed from their edges, at most MAX_TOKENS."""
    tokens: list[str] = []
    for word in normalize_query(raw).split(" "):
        word = word.strip(_EDGE_PUNCTUATION).lower()[:MAX_TOKEN_CHARS]
        if word and word not in tokens:
            tokens.append(word)
        if len(tokens) == MAX_TOKENS:
            break
    return tokens


def _pattern(token: str) -> str:
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _like(column: Any, token: str) -> _Expr:
    return column.ilike(_pattern(token), escape="\\")


def _category_ids_matching(token: str) -> Select[Any]:
    return select(Category.id).where(_like(Category.name, token))


def _product_token(token: str) -> _Expr:
    return or_(
        _like(Product.title, token),
        _like(Product.subtitle, token),
        _like(Product.slug, token),
        Product.category_id.in_(_category_ids_matching(token)),
    )


def product_condition(tokens: Sequence[str]) -> _Expr:
    return and_(*[_product_token(token) for token in tokens])


def product_rank(tokens: Sequence[str], phrase: str) -> _Expr:
    """Higher is better: a title hit beats a subtitle hit beats a category or slug hit."""
    score: _Expr = literal(0)
    for token in tokens:
        score = (
            score
            + case((_like(Product.title, token), 4), else_=0)
            + case((_like(Product.subtitle, token), 2), else_=0)
            + case((Product.category_id.in_(_category_ids_matching(token)), 1), else_=0)
        )
    if phrase:
        score = score + case((_like(Product.title, phrase), 3), else_=0)
    return score


def _blog_token(token: str) -> _Expr:
    in_body = exists().where(
        BlogPostBlock.post_id == BlogPost.id,
        BlogPostBlock.is_active.is_(True),
        or_(_like(BlogPostBlock.text, token), _like(BlogPostBlock.title, token)),
    )
    return or_(
        _like(BlogPost.title, token),
        _like(BlogPost.excerpt, token),
        _like(BlogPost.author, token),
        _like(json_text(BlogPost.tags), token),
        in_body,
    )


def blog_condition(tokens: Sequence[str]) -> _Expr:
    return and_(BlogPost.is_active.is_(True), *[_blog_token(token) for token in tokens])


def blog_rank(tokens: Sequence[str], phrase: str) -> _Expr:
    score: _Expr = literal(0)
    for token in tokens:
        score = (
            score
            + case((_like(BlogPost.title, token), 4), else_=0)
            + case((_like(BlogPost.excerpt, token), 2), else_=0)
            + case((_like(json_text(BlogPost.tags), token), 1), else_=0)
        )
    if phrase:
        score = score + case((_like(BlogPost.title, phrase), 3), else_=0)
    return score
