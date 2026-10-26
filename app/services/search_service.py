"""Public global search over published products and active blog articles.

Visibility is the same as the public lists: a product must be published and sit in a visible
category; a blog article must be active. Nothing else is selectable, so drafts, hidden
categories and admin-only fields cannot leak through this endpoint.
"""

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.models.blogs.posts import BlogPost
from app.models.product import Product
from app.schemas.common import page_count
from app.schemas.product import CatalogQuery
from app.schemas.search import (
    BlogHit,
    BlogHits,
    ProductHits,
    SearchQuery,
    SearchResults,
)
from app.services import category_service, product_service, search_text


async def _products(
    db: AsyncSession, tokens: list[str], phrase: str, query: SearchQuery
) -> ProductHits:
    if not tokens:
        return ProductHits(items=[], total=0, page=query.page, pages=0)
    index = await category_service.load_index(db)
    conditions = product_service._public_filters(CatalogQuery(q=phrase), index=index)
    total = await product_service._count(db, conditions)
    stmt = (
        product_service._apply(select(Product), conditions)
        .options(defer(Product.content))
        .order_by(
            desc(search_text.product_rank(tokens, phrase)),
            desc(Product.featured),
            desc(Product.created_at),
            Product.id,
        )
        .offset(query.offset)
        .limit(query.page_size)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return ProductHits(
        items=[product_service.public_card(row, index) for row in rows],
        total=total,
        page=query.page,
        pages=page_count(total, query.page_size),
    )


def _hit(post: BlogPost) -> BlogHit:
    return BlogHit(
        id=str(post.id),
        slug=post.slug,
        title=post.title,
        excerpt=post.excerpt,
        cover_image=post.cover_image,
        cover_alt=post.cover_alt,
        author=post.author,
        published_at=post.published_at,
        read_time=post.read_time,
        tags=list(post.tags or []),
    )


async def _blogs(db: AsyncSession, tokens: list[str], phrase: str, query: SearchQuery) -> BlogHits:
    if not tokens:
        return BlogHits(items=[], total=0, page=query.page, pages=0)
    condition = search_text.blog_condition(tokens)
    total = int(await db.scalar(select(func.count()).select_from(BlogPost).where(condition)) or 0)
    stmt = (
        select(BlogPost)
        .where(condition)
        .order_by(
            desc(search_text.blog_rank(tokens, phrase)),
            BlogPost.sort_order,
            desc(BlogPost.created_at),
            BlogPost.id,
        )
        .offset(query.offset)
        .limit(query.page_size)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return BlogHits(
        items=[_hit(row) for row in rows],
        total=total,
        page=query.page,
        pages=page_count(total, query.page_size),
    )


async def search(db: AsyncSession, query: SearchQuery) -> SearchResults:
    phrase = search_text.normalize_query(query.q).lower()
    tokens = search_text.tokenize(phrase)
    empty_products = ProductHits(items=[], total=0, page=query.page, pages=0)
    empty_blogs = BlogHits(items=[], total=0, page=query.page, pages=0)
    products = empty_products
    blogs = empty_blogs
    if query.type in ("all", "products"):
        products = await _products(db, tokens, phrase, query)
    if query.type in ("all", "blogs"):
        blogs = await _blogs(db, tokens, phrase, query)
    return SearchResults(
        query=phrase,
        type=query.type,
        page_size=query.page_size,
        products=products,
        blogs=blogs,
    )
