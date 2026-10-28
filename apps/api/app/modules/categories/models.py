import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Authored, Base, UUIDPk


class Category(UUIDPk, Authored, Base):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("merged_into_id IS NULL OR merged_into_id <> id", name="not_merged_into_self"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
        Index(
            "uq_categories_group_system_key",
            "group_key",
            "system_key",
            unique=True,
            postgresql_where=text("system_key IS NOT NULL"),
        ),
        # Sibling names are unique (case-insensitive) among categories that have not been merged away.
        Index(
            "uq_categories_sibling_name",
            "group_key",
            text("coalesce(parent_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            text("lower(name)"),
            unique=True,
            postgresql_where=text("merged_into_id IS NULL"),
        ),
        Index("ix_categories_group_parent", "group_key", "parent_id"),
    )

    group_key: Mapped[str] = mapped_column(String(50))
    system_key: Mapped[str | None] = mapped_column(String(50))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    is_system: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(default=1)
