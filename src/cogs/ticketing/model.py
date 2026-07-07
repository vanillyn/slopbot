from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.data.db import Database


def ticket_table_columns() -> tuple[str, ...]:
    return (
        "id",
        "guild_id",
        "channel_id",
        "opener_id",
        "panel_id",
        "reason",
        "status",
        "created_at",
        "closed_at",
    )
