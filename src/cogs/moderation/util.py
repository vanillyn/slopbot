from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

import discord
from discord import app_commands

from src.permissions import has_permission

T = TypeVar("T")


class HierarchyError(app_commands.AppCommandError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def check_hierarchy(target: discord.Member, moderator: discord.Member) -> None:
    if target.id == moderator.id:
        raise HierarchyError("you can't target yourself")
    if target.id == moderator.guild.owner_id:
        raise HierarchyError("can't target the server owner")
    if moderator.id != moderator.guild.owner_id and target.top_role >= moderator.top_role:
        raise HierarchyError("target has an equal or higher role than you")
    if not target.guild.me.top_role > target.top_role:
        raise HierarchyError("i don't have a high enough role to do that")


def require_permission(
    node: str,
) -> Callable[
    [Callable[..., Coroutine[Any, Any, T]]], Callable[..., Coroutine[Any, Any, T]]
]:
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        if interaction.user.guild_permissions.administrator:
            return True
        bot = interaction.client
        db = getattr(bot, "db", None)
        if db is None:
            return False
        return await has_permission(db, interaction.user, node)

    return app_commands.check(predicate)
