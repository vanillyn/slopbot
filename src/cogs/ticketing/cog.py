from __future__ import annotations

import re
from typing import TYPE_CHECKING

import discord
from discord import app_commands, ui
from discord.ext import commands

from src.cogs.ticketing.db import (
    close_ticket,
    create_panel,
    create_ticket,
    get_open_ticket_for,
    get_panel,
    get_ticket_by_channel,
    set_panel_message,
)
from src.utils.ui import BaseLayout, BaseModal
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("ticketing")


def _panel_layout(title: str, description: str, panel_id: int) -> BaseLayout:
    layout = BaseLayout()
    layout.add_container(ui.TextDisplay(f"# {title}\n{description}"), accent_color=0x5865F2)
    layout.add_item(ui.ActionRow(OpenTicketButton(panel_id)))
    return layout


class TicketReasonModal(BaseModal):
    reason = ui.TextInput(
        label="Reason for support",
        placeholder="Describe your issue or question",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=512,
    )

    def __init__(self, panel_id: int, user: discord.User) -> None:
        super().__init__(title="Ticket reason", custom_id=f"ticket_reason_modal:{panel_id}:{user.id}")
        self.panel_id = panel_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        bot = interaction.client
        panel = await get_panel(bot.db, self.panel_id)  # type: ignore[attr-defined]
        if panel is None:
            await interaction.response.send_message("this panel no longer exists", ephemeral=True)
            return

        existing = await get_open_ticket_for(bot.db, interaction.guild.id, interaction.user.id)  # type: ignore[attr-defined]
        if existing is not None:
            await interaction.response.send_message(
                f"you already have an open ticket: <#{existing['channel_id']}>", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        category = guild.get_channel(int(panel["category_id"])) if panel["category_id"] else None  # type: ignore[arg-type]
        overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        staff_role_id = int(panel["staff_role_id"]) if panel["staff_role_id"] else 0  # type: ignore[arg-type]
        if staff_role_id:
            role = guild.get_role(staff_role_id)
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        display_name = interaction.user.name or str(interaction.user.id)
        channel_name = f"ticket-{display_name}".lower()
        if len(channel_name) > 90:
            channel_name = channel_name[:90]

        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category if isinstance(category, discord.CategoryChannel) else None,
                overwrites=overwrites,
                reason=f"ticket opened by {interaction.user}",
            )
        except discord.HTTPException as e:
            await interaction.followup.send(f"couldn't create the ticket channel: {e}", ephemeral=True)
            return

        await create_ticket(
            bot.db,
            guild.id,
            channel.id,
            interaction.user.id,
            self.panel_id,
            self.reason.value.strip(),
        )  # type: ignore[attr-defined]

        layout = BaseLayout()
        layout.add_container(
            ui.TextDisplay(
                f"# ticket opened\n{interaction.user.mention} — a member of staff will be with you shortly.\n\n**Reason:** {self.reason.value.strip() or 'no reason provided'}"
            ),
            accent_color=0x57F287,
        )
        layout.add_item(ui.ActionRow(CloseTicketButton()))
        await channel.send(view=layout)
        await interaction.followup.send(f"ticket created: {channel.mention}", ephemeral=True)
        log.info("ticket opened by %s in %s", interaction.user.id, channel.id)


class OpenTicketButton(ui.DynamicItem[ui.Button[ui.View]], template=r"ticket:open:(\d+)"):
    def __init__(self, panel_id: int) -> None:
        item: ui.Button[ui.View] = ui.Button(
            label="open ticket",
            style=discord.ButtonStyle.primary,
            custom_id=f"ticket:open:{panel_id}",
        )
        super().__init__(item)
        self.panel_id = panel_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: ui.Button[ui.View], match: re.Match[str]
    ) -> "OpenTicketButton":
        return cls(int(match.group(1)))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        modal = TicketReasonModal(self.panel_id, interaction.user)
        await interaction.response.send_modal(modal)


class CloseTicketButton(ui.DynamicItem[ui.Button[ui.View]], template=r"ticket:close"):
    def __init__(self) -> None:
        item: ui.Button[ui.View] = ui.Button(
            label="close ticket", style=discord.ButtonStyle.danger, custom_id="ticket:close"
        )
        super().__init__(item)

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: ui.Button[ui.View], match: re.Match[str]
    ) -> "CloseTicketButton":
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = interaction.client
        if interaction.guild is None or interaction.channel is None:
            return
        ticket = await get_ticket_by_channel(bot.db, interaction.channel.id)  # type: ignore[attr-defined]
        if ticket is None:
            await interaction.response.send_message("this isn't a ticket channel", ephemeral=True)
            return
        await close_ticket(bot.db, interaction.channel.id)  # type: ignore[attr-defined]
        await interaction.response.send_message("closing this ticket in 5 seconds...")
        if isinstance(interaction.channel, discord.TextChannel):
            await interaction.channel.delete(delay=5, reason="ticket closed")


class TicketingCog(commands.Cog, name="ticketing"):
    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        bot.add_dynamic_items(OpenTicketButton, CloseTicketButton)

    ticket = app_commands.Group(
        name="ticket", description="ticketing system", default_permissions=discord.Permissions(manage_guild=True)
    )

    @ticket.command(name="panel", description="post a ticket panel in a channel")
    @app_commands.describe(
        channel="channel to post the panel in",
        category="category new ticket channels are created under",
        staff_role="role given access to every ticket",
        title="panel title",
        description="panel description",
    )
    async def panel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        category: discord.CategoryChannel | None = None,
        staff_role: discord.Role | None = None,
        title: str = "support",
        description: str = "click below to open a ticket",
    ) -> None:
        if interaction.guild is None:
            return
        panel_id = await create_panel(
            self.bot.db,
            interaction.guild.id,
            channel.id,
            category.id if category else 0,
            staff_role.id if staff_role else 0,
            title,
            description,
        )
        layout = _panel_layout(title, description, panel_id)
        msg = await channel.send(view=layout)
        await set_panel_message(self.bot.db, panel_id, msg.id)
        await interaction.response.send_message(f"panel posted in {channel.mention}", ephemeral=True)

    @ticket.command(name="close", description="close the current ticket")
    async def close(self, interaction: discord.Interaction) -> None:
        if interaction.channel is None:
            return
        ticket = await get_ticket_by_channel(self.bot.db, interaction.channel.id)
        if ticket is None:
            await interaction.response.send_message("this isn't a ticket channel", ephemeral=True)
            return
        await close_ticket(self.bot.db, interaction.channel.id)
        await interaction.response.send_message("closing this ticket in 5 seconds...")
        if isinstance(interaction.channel, discord.TextChannel):
            await interaction.channel.delete(delay=5, reason="ticket closed")

    @ticket.command(name="add", description="add a member to the current ticket")
    @app_commands.describe(member="member to add")
    async def add(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            return
        ticket = await get_ticket_by_channel(self.bot.db, interaction.channel.id)
        if ticket is None:
            await interaction.response.send_message("this isn't a ticket channel", ephemeral=True)
            return
        await interaction.channel.set_permissions(member, view_channel=True, send_messages=True)
        await interaction.response.send_message(f"added {member.mention} to the ticket")


async def setup(bot: "Bot") -> None:
    await bot.add_cog(TicketingCog(bot))
