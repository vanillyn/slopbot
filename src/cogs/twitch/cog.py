from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.cogs.twitch.db import (
    add_streamer,
    get_streamer,
    get_streamer_by_username,
    remove_streamer,
    update_streamer,
)
from src.cogs.twitch.eventsub import EventSubWebSocket
from src.cogs.twitch.notifications import send_live_notification
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("twitch.cog")


async def build_config_embed(
    bot: "Bot", twitch_user_id: str, profile_pic: str, guild_id: int | None = None
) -> discord.Embed:
    streamer = await get_streamer(bot.db, twitch_user_id, guild_id)
    assert streamer is not None
    channel_val = (
        f"<#{streamer['discord_channel_id']}>" if int(streamer["discord_channel_id"]) else "not set"  # type: ignore[arg-type]
    )
    role_val = f"<@&{streamer['ping_role_id']}>" if int(streamer["ping_role_id"]) else "none"  # type: ignore[arg-type]
    embed = discord.Embed(
        title=f"configuring {streamer['twitch_username']}",
        color=discord.Color(int(streamer["accent_color"])),  # type: ignore[arg-type]
    )
    embed.set_thumbnail(url=profile_pic)
    embed.add_field(name="channel", value=channel_val, inline=True)
    embed.add_field(name="role", value=role_val, inline=True)
    embed.add_field(name="color", value=f"#{int(streamer['accent_color']):06x}", inline=True)  # type: ignore[arg-type]
    embed.add_field(name="message", value=f"`{streamer['custom_message']}`", inline=False)
    embed.add_field(name="footer", value=f"`{streamer['footer_message']}`", inline=False)
    return embed


async def _refresh_panel(
    bot: "Bot",
    twitch_user_id: str,
    profile_pic: str,
    message: discord.Message,
    guild_id: int | None = None,
) -> None:
    embed = await build_config_embed(bot, twitch_user_id, profile_pic, guild_id)
    view = ConfigView(bot, twitch_user_id, profile_pic, guild_id)
    await message.edit(embed=embed, view=view)


class EditMessageModal(discord.ui.Modal, title="edit message"):
    content = discord.ui.TextInput(label="custom message", placeholder="{user} is live", max_length=100)

    def __init__(
        self,
        bot: "Bot",
        twitch_user_id: str,
        current: str,
        profile_pic: str,
        config_message: discord.Message,
        guild_id: int | None = None,
    ) -> None:
        super().__init__()
        self.bot = bot
        self.twitch_user_id = twitch_user_id
        self.profile_pic = profile_pic
        self.config_message = config_message
        self.guild_id = guild_id
        self.content.default = current

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await update_streamer(
            self.bot.db,
            self.twitch_user_id,
            guild_id=self.guild_id,
            custom_message=self.content.value,
        )
        await interaction.response.defer(ephemeral=True)
        await _refresh_panel(self.bot, self.twitch_user_id, self.profile_pic, self.config_message, self.guild_id)


class EditFooterModal(discord.ui.Modal, title="edit footer"):
    content = discord.ui.TextInput(label="footer message", placeholder="{followers} followers", max_length=100)

    def __init__(
        self,
        bot: "Bot",
        twitch_user_id: str,
        current: str,
        profile_pic: str,
        config_message: discord.Message,
        guild_id: int | None = None,
    ) -> None:
        super().__init__()
        self.bot = bot
        self.twitch_user_id = twitch_user_id
        self.profile_pic = profile_pic
        self.config_message = config_message
        self.guild_id = guild_id
        self.content.default = current

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await update_streamer(
            self.bot.db,
            self.twitch_user_id,
            guild_id=self.guild_id,
            footer_message=self.content.value,
        )
        await interaction.response.defer(ephemeral=True)
        await _refresh_panel(self.bot, self.twitch_user_id, self.profile_pic, self.config_message, self.guild_id)


class EditColorModal(discord.ui.Modal, title="edit color"):
    content = discord.ui.TextInput(label="accent color (hex)", placeholder="#9b59b6", min_length=4, max_length=7)

    def __init__(
        self,
        bot: "Bot",
        twitch_user_id: str,
        current_color: int,
        profile_pic: str,
        config_message: discord.Message,
        guild_id: int | None = None,
    ) -> None:
        super().__init__()
        self.bot = bot
        self.twitch_user_id = twitch_user_id
        self.profile_pic = profile_pic
        self.config_message = config_message
        self.guild_id = guild_id
        self.content.default = f"#{current_color:06x}"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            color = int(self.content.value.lstrip("#"), 16)
        except ValueError:
            await interaction.response.send_message("invalid hex color", ephemeral=True)
            return
        await update_streamer(self.bot.db, self.twitch_user_id, guild_id=self.guild_id, accent_color=color)
        await interaction.response.defer(ephemeral=True)
        await _refresh_panel(self.bot, self.twitch_user_id, self.profile_pic, self.config_message, self.guild_id)


class ChannelSelectView(discord.ui.View):
    def __init__(
        self,
        bot: "Bot",
        twitch_user_id: str,
        profile_pic: str,
        config_message: discord.Message,
        guild_id: int | None = None,
    ) -> None:
        super().__init__(timeout=60)
        self.bot = bot
        self.twitch_user_id = twitch_user_id
        self.profile_pic = profile_pic
        self.config_message = config_message
        self.guild_id = guild_id

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="pick a channel")
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect) -> None:
        await update_streamer(
            self.bot.db,
            self.twitch_user_id,
            guild_id=self.guild_id,
            discord_channel_id=select.values[0].id,
        )
        await interaction.response.defer(ephemeral=True)
        await _refresh_panel(self.bot, self.twitch_user_id, self.profile_pic, self.config_message, self.guild_id)
        self.stop()


class RoleSelectView(discord.ui.View):
    def __init__(
        self,
        bot: "Bot",
        twitch_user_id: str,
        profile_pic: str,
        config_message: discord.Message,
        guild_id: int | None = None,
    ) -> None:
        super().__init__(timeout=60)
        self.bot = bot
        self.twitch_user_id = twitch_user_id
        self.profile_pic = profile_pic
        self.config_message = config_message
        self.guild_id = guild_id

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="pick a role")
    async def select_role(self, interaction: discord.Interaction, select: discord.ui.RoleSelect) -> None:
        await update_streamer(
            self.bot.db,
            self.twitch_user_id,
            guild_id=self.guild_id,
            ping_role_id=select.values[0].id,
        )
        await interaction.response.defer(ephemeral=True)
        await _refresh_panel(self.bot, self.twitch_user_id, self.profile_pic, self.config_message, self.guild_id)
        self.stop()

    @discord.ui.button(label="no role", style=discord.ButtonStyle.danger)
    async def no_role(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await update_streamer(self.bot.db, self.twitch_user_id, guild_id=self.guild_id, ping_role_id=0)
        await interaction.response.defer(ephemeral=True)
        await _refresh_panel(self.bot, self.twitch_user_id, self.profile_pic, self.config_message, self.guild_id)
        self.stop()


class ConfigView(discord.ui.View):
    def __init__(self, bot: "Bot", twitch_user_id: str, profile_pic: str, guild_id: int | None = None) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.twitch_user_id = twitch_user_id
        self.profile_pic = profile_pic
        self.guild_id = guild_id

    @discord.ui.button(label="set channel", style=discord.ButtonStyle.secondary, row=0)
    async def set_channel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        assert interaction.message is not None
        view = ChannelSelectView(self.bot, self.twitch_user_id, self.profile_pic, interaction.message, self.guild_id)
        await interaction.response.send_message(view=view, ephemeral=True)

    @discord.ui.button(label="set role", style=discord.ButtonStyle.secondary, row=0)
    async def set_role(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        assert interaction.message is not None
        view = RoleSelectView(self.bot, self.twitch_user_id, self.profile_pic, interaction.message, self.guild_id)
        await interaction.response.send_message(view=view, ephemeral=True)

    @discord.ui.button(label="edit message", style=discord.ButtonStyle.secondary, row=0)
    async def edit_message_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        assert interaction.message is not None
        streamer = await get_streamer(self.bot.db, self.twitch_user_id, self.guild_id)
        assert streamer is not None
        await interaction.response.send_modal(
            EditMessageModal(
                self.bot,
                self.twitch_user_id,
                str(streamer["custom_message"]),
                self.profile_pic,
                interaction.message,
                self.guild_id,
            )
        )

    @discord.ui.button(label="edit footer", style=discord.ButtonStyle.secondary, row=1)
    async def edit_footer_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        assert interaction.message is not None
        streamer = await get_streamer(self.bot.db, self.twitch_user_id, self.guild_id)
        assert streamer is not None
        await interaction.response.send_modal(
            EditFooterModal(
                self.bot,
                self.twitch_user_id,
                str(streamer["footer_message"]),
                self.profile_pic,
                interaction.message,
                self.guild_id,
            )
        )

    @discord.ui.button(label="edit color", style=discord.ButtonStyle.secondary, row=1)
    async def edit_color_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        assert interaction.message is not None
        streamer = await get_streamer(self.bot.db, self.twitch_user_id, self.guild_id)
        assert streamer is not None
        await interaction.response.send_modal(
            EditColorModal(
                self.bot,
                self.twitch_user_id,
                int(streamer["accent_color"]),  # type: ignore[arg-type]
                self.profile_pic,
                interaction.message,
                self.guild_id,
            )
        )

    @discord.ui.button(label="done", style=discord.ButtonStyle.success, row=1)
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(view=None)


class TwitchCog(commands.Cog, name="twitch"):
    """twitch live-notification tracking. subscriptions are delivered over
    EventSub's websocket transport (`eventsub.py`) — there is no public
    server or webhook secret to configure. see the README for setup."""

    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        self.eventsub = EventSubWebSocket(bot.twitch, self._on_stream_online)

    async def cog_load(self) -> None:
        await self.bot.twitch.start()
        await self.eventsub.start()

    async def cog_unload(self) -> None:
        await self.eventsub.stop()
        await self.bot.twitch.close()

    async def _on_stream_online(self, broadcaster_id: str) -> None:
        try:
            await send_live_notification(self.bot, broadcaster_id)
        except Exception:
            log.exception("failed to send live notification for %s", broadcaster_id)

    @commands.hybrid_command(name="setup", description="track a twitch streamer in this channel")
    @commands.has_permissions(manage_guild=True)
    async def setup_cmd(self, ctx: commands.Context, username: str) -> None:
        if ctx.guild is None:
            await ctx.send("this command only works in a server")
            return
        result = await self.bot.twitch.get_user_id(username)
        if result is None:
            await ctx.send(f"couldn't find twitch user '{username}'")
            return
        user_id, display_name = result
        if await get_streamer(self.bot.db, user_id, ctx.guild.id) is not None:
            await ctx.send(f"{display_name} is already being tracked")
            return
        await add_streamer(self.bot.db, user_id, display_name, ctx.channel.id, ctx.guild.id)
        sub_id = await self.eventsub.subscribe(user_id)
        if sub_id:
            await update_streamer(self.bot.db, user_id, guild_id=ctx.guild.id, subscription_id=sub_id)
        user_info = await self.bot.twitch.get_user_info(user_id)
        profile_pic = str(user_info["profile_image_url"]) if user_info else ""
        embed = await build_config_embed(self.bot, user_id, profile_pic, ctx.guild.id)
        view = ConfigView(self.bot, user_id, profile_pic, ctx.guild.id)
        await ctx.send(f"added **{display_name}** — configure below:", embed=embed, view=view)

    @commands.hybrid_command(name="edit", description="edit a tracked streamer's config")
    @commands.has_permissions(manage_guild=True)
    async def edit_cmd(self, ctx: commands.Context, username: str) -> None:
        if ctx.guild is None:
            await ctx.send("this command only works in a server")
            return
        streamer = await get_streamer_by_username(self.bot.db, username, ctx.guild.id)
        if streamer is None:
            await ctx.send(f"no streamer named '{username}' found")
            return
        user_info = await self.bot.twitch.get_user_info(str(streamer["twitch_user_id"]))
        profile_pic = str(user_info["profile_image_url"]) if user_info else ""
        embed = await build_config_embed(self.bot, str(streamer["twitch_user_id"]), profile_pic, ctx.guild.id)
        view = ConfigView(self.bot, str(streamer["twitch_user_id"]), profile_pic, ctx.guild.id)
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="untrack", description="stop tracking a twitch streamer")
    @commands.has_permissions(manage_guild=True)
    async def remove_cmd(self, ctx: commands.Context, username: str) -> None:
        if ctx.guild is None:
            await ctx.send("this command only works in a server")
            return
        streamer = await get_streamer_by_username(self.bot.db, username, ctx.guild.id)
        if streamer is None:
            await ctx.send(f"no streamer named '{username}' found")
            return
        sub_id = str(streamer["subscription_id"])
        if sub_id:
            await self.bot.twitch.unsubscribe(sub_id)
        await remove_streamer(self.bot.db, str(streamer["twitch_user_id"]), ctx.guild.id)
        await ctx.send(f"removed **{streamer['twitch_username']}**")

    @commands.hybrid_command(name="testlive", description="send a test live notification")
    @commands.has_permissions(manage_guild=True)
    async def test_cmd(self, ctx: commands.Context, username: str) -> None:
        if ctx.guild is None:
            await ctx.send("this command only works in a server")
            return
        streamer = await get_streamer_by_username(self.bot.db, username, ctx.guild.id)
        if streamer is None:
            await ctx.send(f"no streamer named '{username}' found")
            return
        if not int(streamer["discord_channel_id"]):  # type: ignore[arg-type]
            await ctx.send("set a channel first with the edit command")
            return
        await send_live_notification(self.bot, str(streamer["twitch_user_id"]))
        await ctx.send("test sent", delete_after=5)


async def setup(bot: "Bot") -> None:
    await bot.add_cog(TwitchCog(bot))
