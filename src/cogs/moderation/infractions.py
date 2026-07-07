from __future__ import annotations

import time
from dataclasses import dataclass

from src.data.db import Database


@dataclass
class Infraction:
    id: int
    guild_id: int
    target_id: int
    target_name: str
    moderator_id: int
    infraction_type: str
    reason: str
    duration: int | None
    created_at: int

    @property
    def case_str(self) -> str:
        return f"#{self.id}"


async def add_infraction(
    db: Database,
    *,
    guild_id: int,
    target_id: int,
    target_name: str,
    moderator_id: int,
    infraction_type: str,
    reason: str,
    duration: int | None = None,
) -> Infraction:
    created_at = int(time.time())
    await db.execute(
        "insert into infractions"
        " (guild_id, target_id, target_name, moderator_id, infraction_type, reason, duration, created_at)"
        " values (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            guild_id,
            target_id,
            target_name,
            moderator_id,
            infraction_type,
            reason,
            duration,
            created_at,
        ),
    )
    row = await db.fetchone(
        "select id from infractions where guild_id = ? order by id desc limit 1",
        (guild_id,),
    )
    case_id = int(row[0]) if row else 0
    return Infraction(
        id=case_id,
        guild_id=guild_id,
        target_id=target_id,
        target_name=target_name,
        moderator_id=moderator_id,
        infraction_type=infraction_type,
        reason=reason,
        duration=duration,
        created_at=created_at,
    )


async def get_infractions(db: Database, guild_id: int, target_id: int) -> list[Infraction]:
    rows = await db.fetchall(
        "select id, guild_id, target_id, target_name, moderator_id, infraction_type,"
        " reason, duration, created_at from infractions"
        " where guild_id = ? and target_id = ? order by id desc",
        (guild_id, target_id),
    )
    return [Infraction(*row) for row in rows]
