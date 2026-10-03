import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BlogPost(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One blog article. Deleting its category clears the link and keeps the article."""

    __tablename__ = "blog_posts"

    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    excerpt: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("blog_category_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cover_image: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    cover_alt: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    author: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    author_role: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    published_at: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    read_time: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    related_product_slugs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocks: Mapped[list["BlogPostBlock"]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="BlogPostBlock.sort_order",
    )

    def __repr__(self) -> str:
        return f"<BlogPost {self.slug}>"


class BlogPostBlock(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One body block: paragraph, heading, list, or callout."""

    __tablename__ = "blog_post_blocks"

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blog_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    block_type: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    variant: Mapped[str] = mapped_column(String(20), nullable=False, default="tip")
    items: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    post: Mapped[BlogPost] = relationship(back_populates="blocks")

    def __repr__(self) -> str:
        return f"<BlogPostBlock {self.block_type}>"
