from __future__ import annotations

import asyncio
import random
import re
from datetime import timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands, ui
from discord.ext import commands

from src.data.config import GuildConfig
from src.cogs.moderation.logging import log_infraction
from src.cogs.moderation.infractions import add_infraction
from src.permissions import has_permission
from src.utils.ui import BaseLayout, ConfirmView
from src.cogs.moderation.util import check_hierarchy, require_permission

if TYPE_CHECKING:
    from src.bot import Bot

_MAX_TIMEOUT = timedelta(days=28)


def _parse_duration(s: str) -> timedelta | None:
    if not s or s.strip().lower() in ("forever", "permanent", "perm"):
        return None
    total = timedelta()
    for amt, unit in re.findall(r"(\d+)\s*([smhd])", s, re.IGNORECASE):
        n = int(amt)
        match unit.lower():
            case "s":
                total += timedelta(seconds=n)
            case "m":
                total += timedelta(minutes=n)
            case "h":
                total += timedelta(hours=n)
            case "d":
                total += timedelta(days=n)
    return total if total.total_seconds() > 0 else None


def _fmt_duration(td: timedelta | None) -> str:
    if td is None:
        return "permanent"
    secs = int(td.total_seconds())
    parts: list[str] = []
    for label, div in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if secs >= div:
            parts.append(f"{secs // div}{label}")
            secs %= div
    return " ".join(parts) or "0s"


def _pick(options: list[str], user: str) -> str:
    return random.choice(options).replace("{user}", user)


def _fmt_msg(template: str, user: discord.Member, reason: str) -> str:
    return (
        template.replace("{user}", str(user))
        .replace("{reason}", reason)
        .replace("{mention}", user.mention)
    )


async def _dm(target: discord.Member, templates: list[str], reason: str) -> None:
    try:
        await target.send(_fmt_msg(random.choice(templates), target, reason))
    except discord.HTTPException:
        pass


def _channel_msg(templates: list[str], user: discord.Member, reason: str) -> str:
    return _fmt_msg(random.choice(templates), user, reason)


def _layout(
    action: str,
    target: discord.Member | str,
    moderator: discord.Member,
    reason: str,
    case_str: str,
    *,
    duration: timedelta | None = None,
    extra: list[str] | None = None,
    color: int = 0xED4245,
) -> BaseLayout:
    target_str = str(target) if isinstance(target, str) else f"{target} (`{target.id}`)"
    lines = [
        f"**{action}** — case `{case_str}`",
        f"**target:** {target_str}",
        f"**moderator:** {moderator}",
        f"**reason:** {reason}",
    ]
    if duration is not None:
        lines.append(f"**duration:** {_fmt_duration(duration)}")
    if extra:
        lines.extend(extra)
    layout = BaseLayout()
    layout.add_container(ui.TextDisplay("\n".join(lines)), accent_color=color)
    return layout


async def _schedule_unban(guild: discord.Guild, user_id: int, after: timedelta) -> None:
    await asyncio.sleep(after.total_seconds())
    try:
        await guild.unban(discord.Object(id=user_id), reason="ban duration expired")
    except discord.HTTPException:
        pass


async def _schedule_slowmode_reset(
    channel: discord.TextChannel, after: timedelta
) -> None:
    await asyncio.sleep(after.total_seconds())
    try:
        await channel.edit(slowmode_delay=0, reason="slowmode duration expired")
    except discord.HTTPException:
        pass


async def _schedule_unmute(
    guild: discord.Guild, user_id: int, role_id: int, after: timedelta
) -> None:
    await asyncio.sleep(after.total_seconds())
    member = guild.get_member(user_id)
    if member is None:
        return
    role = guild.get_role(role_id)
    if role is None:
        return
    try:
        await member.remove_roles(role, reason="mute duration expired")
    except discord.HTTPException:
        pass


class ModerationActionsCog(commands.Cog, name="moderation"):
    def __init__(self, bot: "Bot") -> None:
        self.bot = bot

    @app_commands.command(name="warn", description="warn a member")
    @app_commands.describe(user="member to warn", reason="reason for the warning")
    @require_permission("moderation.warn")
    async def warn(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str | None = None,
    ) -> None:
        guild = interaction.guild
        moderator = interaction.user
        if guild is None or not isinstance(moderator, discord.Member):
            return
        check_hierarchy(user, moderator)

        cfg = await GuildConfig.load(self.bot.db, guild.id)
        actual_reason = reason or _pick(cfg.moderation.warn_default_reason, str(user))

        async def execute(ci: discord.Interaction) -> None:
            await ci.response.defer(ephemeral=True)
            infraction = await add_infraction(
                self.bot.db,
                guild_id=guild.id,
                target_id=user.id,
                target_name=str(user),
                moderator_id=moderator.id,
                infraction_type="warn",
                reason=actual_reason,
            )
            await log_infraction(self.bot.db, guild, infraction)
            await _dm(user, cfg.moderation.warn_dm, actual_reason)
            layout = BaseLayout()
            layout.add_container(
                ui.TextDisplay(
                    _channel_msg(cfg.moderation.warn_channel, user, actual_reason)
                ),
                accent_color=0xFEE75C,
            )
            await ci.followup.send(view=layout)

        if cfg.moderation.require_confirm:

            async def on_confirm(ci: discord.Interaction, confirmed: bool) -> None:
                if not confirmed:
                    await ci.response.send_message("cancelled", ephemeral=True)
                    return
                await execute(ci)

            await interaction.response.send_message(
                f"warn {user.mention}?", view=ConfirmView(on_confirm), ephemeral=True
            )
        else:
            await execute(interaction)

    @app_commands.command(name="kick", description="kick a member")
    @app_commands.describe(
        user="member to kick",
        reason="reason for the kick",
        quiet="skip logging and dm",
    )
    @require_permission("moderation.kick")
    async def kick(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str | None = None,
        quiet: bool = False,
    ) -> None:
        guild = interaction.guild
        moderator = interaction.user
        if guild is None or not isinstance(moderator, discord.Member):
            return
        check_hierarchy(user, moderator)

        cfg = await GuildConfig.load(self.bot.db, guild.id)
        actual_reason = reason or _pick(cfg.moderation.kick_default_reason, str(user))

        async def execute(ci: discord.Interaction) -> None:
            await ci.response.defer(ephemeral=True)
            if not quiet:
                await _dm(user, cfg.moderation.kick_dm, actual_reason)
            try:
                await user.kick(reason=actual_reason)
            except discord.HTTPException as e:
                await ci.followup.send(f"failed to kick: {e}", ephemeral=True)
                return
            infraction = await add_infraction(
                self.bot.db,
                guild_id=guild.id,
                target_id=user.id,
                target_name=str(user),
                moderator_id=moderator.id,
                infraction_type="kick",
                reason=actual_reason,
            )
            if not quiet:
                await log_infraction(self.bot.db, guild, infraction)
            layout = BaseLayout()
            layout.add_container(
                ui.TextDisplay(
                    _channel_msg(cfg.moderation.kick_channel, user, actual_reason)
                ),
                accent_color=0xFEE75C,
            )
            await ci.followup.send(view=layout, ephemeral=quiet)

        if cfg.moderation.require_confirm and not quiet:

            async def on_confirm(ci: discord.Interaction, confirmed: bool) -> None:
                if not confirmed:
                    await ci.response.send_message("cancelled", ephemeral=True)
                    return
                await execute(ci)

            await interaction.response.send_message(
                f"kick {user.mention}?", view=ConfirmView(on_confirm), ephemeral=True
            )
        else:
            await execute(interaction)

    @app_commands.command(name="ban", description="ban a member")
    @app_commands.describe(
        user="member to ban",
        reason="reason for the ban",
        duration="ban length (e.g. 7d, 24h, forever)",
        quiet="skip logging and dm",
        quick="use default reason and duration, skip confirmation",
        purge="delete recent messages from this user",
    )
    @require_permission("moderation.ban")
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str | None = None,
        duration: str | None = None,
        quiet: bool = False,
        quick: bool = False,
        purge: bool = False,
    ) -> None:
        guild = interaction.guild
        moderator = interaction.user
        if guild is None or not isinstance(moderator, discord.Member ):
            return
        check_hierarchy(user, moderator)

        cfg = await GuildConfig.load(self.bot.db, guild.id)
        if quick:
            actual_reason = _pick(cfg.moderation.ban_default_reason, str(user))
            actual_duration = _parse_duration(cfg.moderation.ban_default_duration)
        else:
            actual_reason = reason or _pick(
                cfg.moderation.ban_default_reason, str(user)
            )
            actual_duration = _parse_duration(duration) if duration else None

        

        async def execute(ci: discord.Interaction) -> None:
            await ci.response.defer(ephemeral=True)
            if not quiet:
                await _dm(user, cfg.moderation.ban_dm, actual_reason)
            try:
                await user.ban(
                    reason=actual_reason, delete_message_days=7 if purge else 0
                )
            except discord.HTTPException as e:
                await ci.followup.send(f"failed to ban: {e}", ephemeral=True)
                return
            if actual_duration is not None:
                asyncio.create_task(_schedule_unban(guild, user.id, actual_duration))
            infraction = await add_infraction(
                self.bot.db,
                guild_id=guild.id,
                target_id=user.id,
                target_name=str(user),
                moderator_id=moderator.id,
                infraction_type="ban",
                reason=actual_reason,
                duration=int(actual_duration.total_seconds())
                if actual_duration
                else None,
            )
            if not quiet:
                await log_infraction(self.bot.db, guild, infraction)
            layout = BaseLayout()
            layout.add_container(
                ui.TextDisplay(
                    _channel_msg(cfg.moderation.ban_channel, user, actual_reason)
                ),
                accent_color=0xED4245,
            )
            await ci.followup.send(view=layout, ephemeral=quiet)

        if cfg.moderation.require_confirm and not quick and not quiet:

            async def on_confirm(ci: discord.Interaction, confirmed: bool) -> None:
                if not confirmed:
                    await ci.response.send_message("cancelled", ephemeral=True)
                    return
                await execute(ci)

            await interaction.response.send_message(
                f"ban {user.mention}?", view=ConfirmView(on_confirm), ephemeral=True
            )
        else:
            await execute(interaction)

    @app_commands.command(name="mute", description="mute a member")
    @app_commands.describe(
        user="member to mute",
        reason="reason for the mute",
        duration="mute length (e.g. 1h, 7d)",
        quiet="skip logging and dm",
    )
    @require_permission("moderation.mute")
    async def mute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str | None = None,
        duration: str | None = None,
        quiet: bool = False,
    ) -> None:
        
        guild = interaction.guild
        moderator = interaction.user
        if guild is None or not isinstance(moderator, discord.Member):
            return
        check_hierarchy(user, moderator)
        cfg = await GuildConfig.load(self.bot.db, guild.id)
        if cfg.moderation.mute_role is None:
            await interaction.response.send_message(
                "no mute role configured — set `moderation.mute.role` first",
                ephemeral=True,
            )
            return
        mute_role = interaction.guild.get_role(cfg.moderation.mute_role)
        if mute_role is None:
            await interaction.response.send_message(
                "mute role not found — it may have been deleted", ephemeral=True
            )
            return
        actual_reason = reason or _pick(
            cfg.moderation.mute_default_reason, str(user)
        )
        raw_duration = duration or cfg.moderation.mute_default_duration
        actual_duration = (
            _parse_duration(raw_duration) if raw_duration else None
        )
        async def execute(ci: discord.Interaction) -> None:
            await ci.response.defer(ephemeral=True)
            try:
                await user.add_roles(mute_role, reason=actual_reason)
            except discord.HTTPException as e:
                await ci.followup.send(f"failed to mute: {e}", ephemeral=True)
                return
            if actual_duration is not None:
                asyncio.create_task(
                    _schedule_unmute(
                        guild, user.id, mute_role.id, actual_duration
                    )
                )
            infraction = await add_infraction(
                self.bot.db,
                guild_id=guild.id,
                target_id=user.id,
                target_name=str(user),
                moderator_id=moderator.id,
                infraction_type="mute",
                reason=actual_reason,
                duration=int(actual_duration.total_seconds())
                if actual_duration
                else None,
            )
            if not quiet:
                await _dm(user, cfg.moderation.mute_dm, actual_reason)
                await log_infraction(self.bot.db, guild, infraction)
            if cfg.moderation.mute_channel is not None:
                mute_ch = guild.get_channel(cfg.moderation.mute_channel)
                if isinstance(mute_ch, discord.TextChannel):
                    dur_str = _fmt_duration(actual_duration)
                    lines = [
                        f"{user.mention} you have been muted by a moderator.",
                        f"**reason:** {actual_reason}",
                        f"**duration:** {dur_str}",
                        "",
                        "if you have questions or want to discuss this, you can talk here.",
                        f"a moderator will be with you shortly — {moderator.mention}",
                    ]
                    mute_layout = BaseLayout()
                    mute_layout.add_container(
                        ui.TextDisplay("\n".join(lines)), accent_color=0xEB459E
                    )
                    await mute_ch.send(view=mute_layout)
            layout = BaseLayout()
            layout.add_container(
                ui.TextDisplay(
                    _channel_msg(
                        cfg.moderation.mute_channel_msg, user, actual_reason
                    )
                ),
                accent_color=0xEB459E,
            )
            await ci.followup.send(view=layout, ephemeral=quiet)
        if cfg.moderation.require_confirm and not quiet:
            async def on_confirm(
                ci: discord.Interaction, confirmed: bool
            ) -> None:
                if not confirmed:
                    await ci.response.send_message("cancelled", ephemeral=True)
                    return
                await execute(ci)
            await interaction.response.send_message(
                f"mute {user.mention}?",
                view=ConfirmView(on_confirm),
                ephemeral=True,
            )
        else:
            await execute(interaction)

    @app_commands.command(name="slowmode", description="set slowmode on a channel")
    @app_commands.describe(
        interval="seconds between messages (0 to disable)",
        duration="how long to keep slowmode (e.g. 30m, 1h)",
        reason="reason for the slowmode",
        channel="target channel (defaults to current)",
        quick="use defaults: 5s interval for 30 minutes",
    )
    @require_permission("moderation.slowmode")
    async def slowmode(
        self,
        interaction: discord.Interaction,
        interval: app_commands.Range[int, 0, 21600] = 5,
        duration: str | None = None,
        reason: str | None = None,
        channel: discord.TextChannel | None = None,
        quick: bool = False,
    ) -> None:

        guild = interaction.guild
        moderator = interaction.user
        if guild is None or not isinstance(moderator, discord.Member):
            return

        if channel is None:
            if not isinstance(interaction.channel, discord.TextChannel):
                await interaction.response.send_message(
                    "run this in a text channel or specify one", ephemeral=True
                )
                return
            channel = interaction.channel

        cfg = await GuildConfig.load(self.bot.db, guild.id)
        actual_interval = 5 if quick else interval
        actual_duration = (
            _parse_duration("30m")
            if quick
            else (_parse_duration(duration) if duration else None)
        )
        actual_reason = reason or _pick(
            cfg.moderation.slowmode_default_reason, str(moderator)
        )
        guild = interaction.guild
        moderator = interaction.user
        target_channel = channel

        async def execute(ci: discord.Interaction) -> None:
            await ci.response.defer(ephemeral=True)
            try:
                await target_channel.edit(
                    slowmode_delay=actual_interval, reason=actual_reason
                )
            except discord.HTTPException as e:
                await ci.followup.send(f"failed: {e}", ephemeral=True)
                return
            if actual_duration is not None:
                asyncio.create_task(
                    _schedule_slowmode_reset(target_channel, actual_duration)
                )
            infraction = await add_infraction(
                self.bot.db,
                guild_id=guild.id,
                target_id=target_channel.id,
                target_name=target_channel.name,
                moderator_id=moderator.id,
                infraction_type="slowmode",
                reason=actual_reason,
                duration=int(actual_duration.total_seconds())
                if actual_duration
                else None,
            )
            await log_infraction(self.bot.db, guild, infraction)
            await ci.followup.send(
                view=_layout(
                    "slowmode",
                    f"{target_channel.mention} (`{target_channel.id}`)",
                    moderator,
                    actual_reason,
                    infraction.case_str,
                    duration=actual_duration,
                    extra=[f"**interval:** {actual_interval}s"],
                    color=0x5865F2,
                )
            )

        if cfg.moderation.require_confirm and not quick:

            async def on_confirm(ci: discord.Interaction, confirmed: bool) -> None:
                if not confirmed:
                    await ci.response.send_message("cancelled", ephemeral=True)
                    return
                await execute(ci)

            await interaction.response.send_message(
                f"set {actual_interval}s slowmode on {target_channel.mention}?",
                view=ConfirmView(on_confirm),
                ephemeral=True,
            )
        else:
            await execute(interaction)

    @app_commands.command(
        name="purge", description="bulk delete messages from a channel"
    )
    @app_commands.describe(
        amount="number of messages to delete (max 100)",
        user="only delete messages from this user",
    )
    @require_permission("moderation.purge")
    async def purge(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 100],
        user: discord.Member | None = None,
    ) -> None:
        guild = interaction.guild
        moderator = interaction.user
        if guild is None or not isinstance(moderator, discord.Member):
            return
        if not await has_permission(self.bot.db, moderator, "moderation.purge"):
            await interaction.response.send_message(
                "missing permissions", ephemeral=True
            )
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "run this in a text channel", ephemeral=True
            )
            return

        channel = interaction.channel
        await interaction.response.defer(ephemeral=True)
        check = (lambda m: m.author.id == user.id) if user is not None else None
        deleted = await channel.purge(limit=amount, check=check)

        lines = [
            f"**purge** — {len(deleted)} message(s) deleted",
            f"**channel:** {channel.mention}",
            f"**moderator:** {moderator}",
        ]
        if user is not None:
            lines.append(f"**filtered to:** {user}")
        layout = BaseLayout()
        layout.add_container(ui.TextDisplay("\n".join(lines)), accent_color=0x57F287)
        await interaction.followup.send(view=layout, ephemeral=True)

    @app_commands.command(name="shutdown", description="locks a channel (or all channels) in case of a raid")
    @app_commands.describe(
        channel="channel to lock (defaults to current)",
        all_channels="lock every text channel in the server",
        reason="reason for the shutdown",
    )
    @require_permission("moderation.shutdown")
    async def shutdown(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        all_channels: bool = False,
        reason: str | None = None,
    ) -> None:
        guild = interaction.guild
        moderator = interaction.user
        if guild is None or not isinstance(moderator, discord.Member):
            return

        if all_channels:
            targets = guild.text_channels
        elif channel is not None:
            targets = [channel]
        elif isinstance(interaction.channel, discord.TextChannel):
            targets = [interaction.channel]
        else:
            await interaction.response.send_message(
                "run this in a text channel or specify one", ephemeral=True
            )
            return

        cfg = await GuildConfig.load(self.bot.db, guild.id)
        actual_reason = reason or _pick(
            cfg.moderation.shutdown_default_reason, str(moderator)
        )

        await interaction.response.defer(ephemeral=True)
        locked: list[discord.TextChannel] = []
        for ch in targets:
            try:
                await ch.set_permissions(
                    guild.default_role, send_messages=False, reason=actual_reason
                )
            except discord.HTTPException:
                continue
            locked.append(ch)
            infraction = await add_infraction(
                self.bot.db,
                guild_id=guild.id,
                target_id=ch.id,
                target_name=ch.name,
                moderator_id=moderator.id,
                infraction_type="shutdown",
                reason=actual_reason,
            )
            await log_infraction(self.bot.db, guild, infraction)

        layout = BaseLayout()
        layout.add_container(
            ui.TextDisplay(
                f"**shutdown** — locked {len(locked)} channel(s)\n"
                + "\n".join(f"- {ch.mention}" for ch in locked[:20])
            ),
            accent_color=0xED4245,
        )
        await interaction.followup.send(view=layout)

    @app_commands.command(name="unshutdown", description="unlocks a channel after a shutdown")
    @app_commands.describe(channel="channel to unlock (defaults to current)")
    @require_permission("moderation.shutdown")
    async def unshutdown(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return
        target = channel or (
            interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None
        )
        if target is None:
            await interaction.response.send_message(
                "run this in a text channel or specify one", ephemeral=True
            )
            return
        await target.set_permissions(guild.default_role, send_messages=None)
        await interaction.response.send_message(f"unlocked {target.mention}", ephemeral=True)


async def setup(bot: "Bot") -> None:
    await bot.add_cog(ModerationActionsCog(bot))
