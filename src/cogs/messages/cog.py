from __future__ import annotations

import re
from typing import TYPE_CHECKING

import discord
from discord import app_commands, ui
from discord.ext import commands

from src.cogs.messages.db import (
    delete_message,
    get_message,
    get_message_by_message_id,
    list_messages,
    set_posted,
    upsert_message,
)
from src.utils.logger import get_logger
from src.utils.ui import BaseLayout

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("messages")

_ACTIONS = ["none", "reaction_role", "button_role"]


class RoleButton(ui.DynamicItem[ui.Button[ui.View]], template=r"cm:role:(\d+)"):
    """persistent button on a custom message that toggles a role, keyed by
    the custom_messages row id encoded in the custom_id so it survives restarts."""

    def __init__(self, role_id: int) -> None:
        item: ui.Button[ui.View] = ui.Button(
            label="get role", style=discord.ButtonStyle.success, custom_id=f"cm:role:{role_id}"
        )
        super().__init__(item)
        self.role_id = role_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: ui.Button[ui.View], match: re.Match[str]
    ) -> "RoleButton":
        return cls(int(match.group(1)))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message("that role no longer exists", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"removed **{role.name}**", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"added **{role.name}**", ephemeral=True)


class MessagesCog(commands.Cog, name="messages"):
    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        bot.add_dynamic_items(RoleButton)

    messages = app_commands.Group(
        name="messages",
        description="admin-configurable messages (rules, help, etc)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @messages.command(name="set", description="create or update a named message")
    @app_commands.describe(
        name="short name to refer to this message by (e.g. rules, help)",
        content="the message text",
        action="what happens when someone reacts/clicks (none, reaction_role, button_role)",
        role="role to grant, required for reaction_role or button_role",
        emoji="emoji to react with, required for reaction_role",
    )
    @app_commands.choices(
        action=[app_commands.Choice(name=a, value=a) for a in _ACTIONS]
    )
    async def set_message(
        self,
        interaction: discord.Interaction,
        name: str,
        content: str,
        action: app_commands.Choice[str] | None = None,
        role: discord.Role | None = None,
        emoji: str | None = None,
    ) -> None:
        if interaction.guild is None:
            return
        action_value = action.value if action else "none"
        if action_value in ("reaction_role", "button_role") and role is None:
            await interaction.response.send_message(
                f"`{action_value}` needs a role", ephemeral=True
            )
            return
        if action_value == "reaction_role" and not emoji:
            await interaction.response.send_message(
                "`reaction_role` needs an emoji", ephemeral=True
            )
            return
        await upsert_message(
            self.bot.db,
            interaction.guild.id,
            name,
            content,
            action_value,
            role.id if role else 0,
            emoji or "",
            interaction.user.id,
        )
        await interaction.response.send_message(
            f"saved message `{name}` — use `/messages send name:{name}` to post it", ephemeral=True
        )

    @messages.command(name="send", description="post a saved message into a channel")
    @app_commands.describe(name="message name, from /messages list", channel="channel to post it in")
    async def send_message(
        self, interaction: discord.Interaction, name: str, channel: discord.TextChannel
    ) -> None:
        if interaction.guild is None:
            return
        msg = await get_message(self.bot.db, interaction.guild.id, name)
        if msg is None:
            await interaction.response.send_message(f"no message named `{name}`", ephemeral=True)
            return

        layout = BaseLayout()
        layout.add_container(discord.ui.TextDisplay(msg["content"]), accent_color=0x5865F2)
        if msg["action"] == "button_role":
            layout.add_item(ui.ActionRow(RoleButton(msg["action_role_id"])))

        try:
            posted = await channel.send(view=layout)
        except discord.HTTPException as e:
            await interaction.response.send_message(f"failed to post: {e}", ephemeral=True)
            return

        await set_posted(self.bot.db, interaction.guild.id, name, channel.id, posted.id)

        if msg["action"] == "reaction_role":
            try:
                await posted.add_reaction(msg["action_emoji"])
            except discord.HTTPException:
                await interaction.response.send_message(
                    f"posted, but couldn't react with `{msg['action_emoji']}` —"
                    " add it manually or check it's a valid emoji",
                    ephemeral=True,
                )
                return

        await interaction.response.send_message(f"posted `{name}` in {channel.mention}", ephemeral=True)

    @messages.command(name="list", description="list saved messages")
    async def list_cmd(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        msgs = await list_messages(self.bot.db, interaction.guild.id)
        if not msgs:
            await interaction.response.send_message("no saved messages yet", ephemeral=True)
            return
        lines = []
        for m in msgs:
            posted = f" — posted in <#{m['channel_id']}>" if m["message_id"] else " — not posted yet"
            lines.append(f"`{m['name']}` ({m['action']}){posted}")
        layout = BaseLayout()
        layout.add_container(discord.ui.TextDisplay("\n".join(lines)), accent_color=0x5865F2)
        await interaction.response.send_message(view=layout, ephemeral=True)

    @messages.command(name="remove", description="delete a saved message")
    @app_commands.describe(name="message name to delete")
    async def remove_cmd(self, interaction: discord.Interaction, name: str) -> None:
        if interaction.guild is None:
            return
        await delete_message(self.bot.db, interaction.guild.id, name)
        await interaction.response.send_message(f"deleted `{name}`", ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self._handle_reaction(payload, adding=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self._handle_reaction(payload, adding=False)

    async def _handle_reaction(self, payload: discord.RawReactionActionEvent, *, adding: bool) -> None:
        if payload.guild_id is None:
            return
        if self.bot.user is not None and payload.user_id == self.bot.user.id:
            return
        msg = await get_message_by_message_id(self.bot.db, payload.message_id)
        if msg is None or msg["action"] != "reaction_role":
            return
        if str(payload.emoji) != msg["action_emoji"]:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        role = guild.get_role(msg["action_role_id"])
        member = guild.get_member(payload.user_id)
        if role is None or member is None:
            return
        try:
            if adding:
                await member.add_roles(role, reason=f"reaction role via message '{msg['name']}'")
            else:
                await member.remove_roles(role, reason=f"reaction role via message '{msg['name']}'")
        except discord.HTTPException:
            pass


async def setup(bot: "Bot") -> None:
    await bot.add_cog(MessagesCog(bot))
