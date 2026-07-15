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
from src.data.button_actions import available_actions, get_handler
from src.data.button_containers import (
    VALID_STYLES,
    add_item,
    delete_container,
    find_item_by_id,
    get_container,
    get_containers,
    remove_item,
)
from src.utils.logger import get_logger
from src.utils.ui import BaseLayout

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("messages")

_ACTIONS = ["none", "reaction_role"]

_STYLE_MAP = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}


def build_container_view(guild_id: int, container: dict) -> ui.ActionRow:
    """builds an ActionRow of ContainerButtons for a saved container.
    discord allows up to 5 buttons per row; containers beyond that would need
    multiple rows, which callers should handle if/when that's needed."""
    row: ui.ActionRow = ui.ActionRow()
    for raw_item in container["items"][:5]:
        if not isinstance(raw_item, dict) or "id" not in raw_item:
            continue
        style = _STYLE_MAP.get(raw_item.get("style", "secondary"), discord.ButtonStyle.secondary)
        row.add_item(
            ContainerButton(
                guild_id=guild_id,
                container_name=container["name"],
                item_id=raw_item["id"],
                label=raw_item.get("label", "click me"),
                style=style,
            )
        )
    return row


class ContainerButton(ui.DynamicItem[ui.Button[ui.View]], template=r"cm:c:(\d+):([0-9a-f]+)"):
    """persistent button backed by a button_containers row. the button's
    config (label/style/action/data) is looked up fresh from the db on every
    click by (guild_id, item_id), so editing a container via /buttons or the
    dashboard updates already-posted messages with no repost or bot restart
    needed.

    only item_id is encoded (not the container name) to keep custom_ids well
    under discord's 100-char limit regardless of how long a container name
    is — item_id is a short random per-guild token from new_item_id()."""

    def __init__(self, *, guild_id: int, container_name: str, item_id: str, label: str, style: discord.ButtonStyle) -> None:
        item: ui.Button[ui.View] = ui.Button(
            label=label, style=style, custom_id=f"cm:c:{guild_id}:{item_id}"
        )
        super().__init__(item)
        self.guild_id = guild_id
        self.container_name = container_name
        self.item_id = item_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: ui.Button[ui.View], match: re.Match[str]
    ) -> "ContainerButton":
        guild_id = int(match.group(1))
        item_id = match.group(2)
        return cls(
            guild_id=guild_id,
            container_name="",
            item_id=item_id,
            label=item.label or "click me",
            style=item.style,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = interaction.client
        config = await find_item_by_id(bot.db, self.guild_id, self.item_id)  # type: ignore[attr-defined]
        if config is None:
            await interaction.response.send_message(
                "this button no longer exists (its container may have been edited or deleted)",
                ephemeral=True,
            )
            return
        handler = get_handler(config.get("action", ""))
        if handler is None:
            await interaction.response.send_message("this button isn't configured correctly", ephemeral=True)
            return
        await handler(interaction, config.get("data", {}) or {})


class MessagesCog(commands.Cog, name="messages"):
    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        bot.add_dynamic_items(ContainerButton)

    messages = app_commands.Group(
        name="messages",
        description="admin-configurable messages (rules, help, etc)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    buttons = app_commands.Group(
        name="buttons",
        description="manage reusable button sets for messages",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # ---- /messages ----

    @messages.command(name="set", description="create or update a named message")
    @app_commands.describe(
        name="short name to refer to this message by (e.g. rules, help)",
        content="the message text (use \\n for a line break)",
        container="name of a saved button set to attach (see /buttons), for clickable buttons",
        action="what happens when someone reacts (none, reaction_role) — separate from buttons",
        role="role to grant, required for reaction_role",
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
        container: str | None = None,
        action: app_commands.Choice[str] | None = None,
        role: discord.Role | None = None,
        emoji: str | None = None,
    ) -> None:
        if interaction.guild is None:
            return
        content = content.replace("\\n", "\n")
        action_value = action.value if action else "none"
        if action_value == "reaction_role" and role is None:
            await interaction.response.send_message("`reaction_role` needs a role", ephemeral=True)
            return
        if action_value == "reaction_role" and not emoji:
            await interaction.response.send_message("`reaction_role` needs an emoji", ephemeral=True)
            return
        if container is not None:
            existing = await get_container(self.bot.db, interaction.guild.id, container)
            if existing is None:
                await interaction.response.send_message(
                    f"no button set named `{container}` — create one with `/buttons additem`", ephemeral=True
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
            container,
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

        if msg["container_name"]:
            container = await get_container(self.bot.db, interaction.guild.id, msg["container_name"])
            if container is None:
                await interaction.response.send_message(
                    f"message references button set `{msg['container_name']}` which no longer exists"
                    " — fix with `/messages set` or `/buttons create`",
                    ephemeral=True,
                )
                return
            if not container["items"]:
                await interaction.response.send_message(
                    f"button set `{msg['container_name']}` has no buttons yet — add one with `/buttons additem`",
                    ephemeral=True,
                )
                return
            layout.add_item(build_container_view(interaction.guild.id, container))

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
            extras = []
            if m["action"] != "none":
                extras.append(m["action"])
            if m["container_name"]:
                extras.append(f"buttons: {m['container_name']}")
            extra_str = f" ({', '.join(extras)})" if extras else ""
            lines.append(f"`{m['name']}`{extra_str}{posted}")
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

    # ---- /buttons ----

    @buttons.command(name="additem", description="add a button to a button set (creates the set if needed)")
    @app_commands.describe(
        container="name of the button set to add to (created if it doesn't exist)",
        label="text shown on the button",
        style="button color",
        action="what the button does when clicked",
        role="role to grant/toggle — required for the grant_role and give_role actions",
    )
    @app_commands.choices(
        style=[app_commands.Choice(name=s, value=s) for s in VALID_STYLES],
        action=[app_commands.Choice(name=a, value=a) for a in available_actions()],
    )
    async def additem_cmd(
        self,
        interaction: discord.Interaction,
        container: str,
        label: str,
        style: app_commands.Choice[str],
        action: app_commands.Choice[str],
        role: discord.Role | None = None,
    ) -> None:
        if interaction.guild is None:
            return
        data: dict = {}
        if action.value in ("grant_role", "give_role"):
            if role is None:
                await interaction.response.send_message(f"`{action.value}` needs a role", ephemeral=True)
                return
            data = {"role_id": role.id}
        item_id = await add_item(
            self.bot.db,
            interaction.guild.id,
            container,
            interaction.user.id,
            label=label,
            style=style.value,
            action=action.value,
            data=data,
        )
        await interaction.response.send_message(
            f"added button **{label}** (`{item_id}`) to `{container}` —"
            f" attach it to a message with `/messages set ... container:{container}`",
            ephemeral=True,
        )

    @buttons.command(name="list", description="list saved button sets, or the buttons in one")
    @app_commands.describe(container="optional: name of a button set to see its individual buttons")
    async def list_buttons_cmd(self, interaction: discord.Interaction, container: str | None = None) -> None:
        if interaction.guild is None:
            return
        if container is not None:
            found = await get_container(self.bot.db, interaction.guild.id, container)
            if found is None:
                await interaction.response.send_message(f"no button set named `{container}`", ephemeral=True)
                return
            if not found["items"]:
                await interaction.response.send_message(f"`{container}` has no buttons yet", ephemeral=True)
                return
            lines = [
                f"`{i.get('id')}` **{i.get('label')}** ({i.get('style')}) — {i.get('action')} {i.get('data')}"
                for i in found["items"]
            ]
            layout = BaseLayout()
            layout.add_container(discord.ui.TextDisplay("\n".join(lines)), accent_color=0x5865F2)
            await interaction.response.send_message(view=layout, ephemeral=True)
            return

        containers = await get_containers(self.bot.db, interaction.guild.id)
        if not containers:
            await interaction.response.send_message("no button sets yet — create one with `/buttons additem`", ephemeral=True)
            return
        lines = [f"`{c['name']}` — {len(c['items'])} button(s)" for c in containers]
        layout = BaseLayout()
        layout.add_container(discord.ui.TextDisplay("\n".join(lines)), accent_color=0x5865F2)
        await interaction.response.send_message(view=layout, ephemeral=True)

    @buttons.command(name="removeitem", description="remove a single button from a button set")
    @app_commands.describe(container="button set name", item_id="button id, from /buttons list container:<name>")
    async def removeitem_cmd(self, interaction: discord.Interaction, container: str, item_id: str) -> None:
        if interaction.guild is None:
            return
        removed = await remove_item(self.bot.db, interaction.guild.id, container, item_id)
        if not removed:
            await interaction.response.send_message(f"no button `{item_id}` in `{container}`", ephemeral=True)
            return
        await interaction.response.send_message(f"removed button `{item_id}` from `{container}`", ephemeral=True)

    @buttons.command(name="delete", description="delete an entire button set")
    @app_commands.describe(container="button set name to delete")
    async def delete_container_cmd(self, interaction: discord.Interaction, container: str) -> None:
        if interaction.guild is None:
            return
        await delete_container(self.bot.db, interaction.guild.id, container)
        await interaction.response.send_message(
            f"deleted button set `{container}` — any messages referencing it will show an error until updated",
            ephemeral=True,
        )

    # ---- reaction roles (unchanged mechanism, buttons are handled by ContainerButton) ----

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
