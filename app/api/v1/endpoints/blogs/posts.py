import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.blogs.posts import (
    PostAdmin,
    PostPublic,
    PostReorder,
    PostsAdmin,
    PostsPublic,
    PostWrite,
)
from app.schemas.common import Message
from app.services.blogs import posts_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=PostsPublic)
async def list_blog_posts(db: DbSession) -> PostsPublic:
    return await posts_service.public_list(db)


@public_router.get("/{slug}", response_model=PostPublic)
async def read_blog_post(db: DbSession, slug: str) -> PostPublic:
    return await posts_service.public_by_slug(db, slug)


@admin_router.get("", response_model=PostsAdmin)
async def list_admin_blog_posts(db: DbSession) -> PostsAdmin:
    return await posts_service.admin_list(db)


@admin_router.post("", response_model=PostAdmin, status_code=status.HTTP_201_CREATED)
async def create_blog_post(db: DbSession, payload: PostWrite) -> PostAdmin:
    return await posts_service.create_post(db, payload)


@admin_router.put("/order", response_model=PostsAdmin)
async def reorder_blog_posts(db: DbSession, payload: PostReorder) -> PostsAdmin:
    return await posts_service.reorder(db, payload)


@admin_router.patch("/{post_id}", response_model=PostAdmin)
async def update_blog_post(db: DbSession, post_id: uuid.UUID, payload: PostWrite) -> PostAdmin:
    post = await posts_service.get_post(db, post_id)
    return await posts_service.update_post(db, post, payload)


@admin_router.delete("/{post_id}", response_model=Message)
async def delete_blog_post(db: DbSession, post_id: uuid.UUID) -> Message:
    post = await posts_service.get_post(db, post_id)
    await posts_service.delete_post(db, post)
    return Message(message="Article removed")
