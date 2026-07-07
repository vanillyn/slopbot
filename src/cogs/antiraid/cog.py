from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.utils.ui import BaseLayout
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.bot import Bot

log = get_logger("antiraid")


@dataclass
class RaidConfig:
    guild_id: int
    enabled: bool = True
    join_threshold: int = 8
    join_window: int = 10
    account_age_min_days: int = 3
    action: str = "kick"  # kick | ban
    log_channel_id: int = 0
    lockdown_active: bool = False

    @classmethod
    async def load(cls, bot: "Bot", guild_id: int) -> "RaidConfig":
        row = await bot.db.fetchone(
            "select guild_id, enabled, join_threshold, join_window,"
            " account_age_min_days, action, log_channel_id, lockdown_active"
            " from raid_config where guild_id = ?",
            (guild_id,),
        )
        if row is None:
            cfg = cls(guild_id=guild_id)
            await cfg.save(bot)
            return cfg
        return cls(
            guild_id=row[0],
            enabled=bool(row[1]),
            join_threshold=row[2],
            join_window=row[3],
            account_age_min_days=row[4],
            action=row[5],
            log_channel_id=row[6],
            lockdown_active=bool(row[7]),
        )

    async def save(self, bot: "Bot") -> None:
        await bot.db.execute(
            "insert into raid_config"
            " (guild_id, enabled, join_threshold, join_window, account_age_min_days,"
            " action, log_channel_id, lockdown_active)"
            " values (?, ?, ?, ?, ?, ?, ?, ?)"
            " on conflict (guild_id) do update set"
            " enabled=excluded.enabled, join_threshold=excluded.join_threshold,"
            " join_window=excluded.join_window, account_age_min_days=excluded.account_age_min_days,"
            " action=excluded.action, log_channel_id=excluded.log_channel_id,"
            " lockdown_active=excluded.lockdown_active",
            (
                self.guild_id,
                int(self.enabled),
                self.join_threshold,
                self.join_window,
                self.account_age_min_days,
                self.action,
                self.log_channel_id,
                int(self.lockdown_active),
            ),
        )


class AntiRaidCog(commands.Cog, name="antiraid"):
    """join-rate raid detection with automated lockdown. tracking state is per-cog-instance,
    not module-global — nothing here is shared outside this cog."""

    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        self._recent_joins: dict[int, deque[float]] = defaultdict(deque)

    async def _log(self, guild: discord.Guild, cfg: RaidConfig, text: str, color: int) -> None:
        if not cfg.log_channel_id:
            return
        channel = guild.get_channel(cfg.log_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        layout = BaseLayout()
        layout.add_container(discord.ui.TextDisplay(text), accent_color=color)
        try:
            await channel.send(view=layout)
        except discord.HTTPException:
            pass

    async def _trigger_lockdown(self, guild: discord.Guild, cfg: RaidConfig) -> None:
        if cfg.lockdown_active:
            return
        cfg.lockdown_active = True
        await cfg.save(self.bot)
        locked = 0
        for ch in guild.text_channels:
            try:
                await ch.set_permissions(
                    guild.default_role, send_messages=False, reason="anti-raid lockdown"
                )
                locked += 1
            except discord.HTTPException:
                continue
        await self._log(
            guild,
            cfg,
            f"**raid detected** — locked {locked} channel(s). run `/antiraid lockdown off` once it's clear.",
            0xED4245,
        )
        log.warning("lockdown triggered in guild %s (%d channels locked)", guild.id, locked)

    async def _lift_lockdown(self, guild: discord.Guild, cfg: RaidConfig) -> None:
        cfg.lockdown_active = False
        await cfg.save(self.bot)
        for ch in guild.text_channels:
            try:
                await ch.set_permissions(guild.default_role, send_messages=None)
            except discord.HTTPException:
                continue

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        cfg = await RaidConfig.load(self.bot, guild.id)
        if not cfg.enabled:
            return

        now = time.time()
        joins = self._recent_joins[guild.id]
        joins.append(now)
        while joins and now - joins[0] > cfg.join_window:
            joins.popleft()

        account_age = datetime.now(timezone.utc) - member.created_at
        is_new_account = account_age.days < cfg.account_age_min_days

        if is_new_account:
            reason = f"account younger than {cfg.account_age_min_days}d (anti-raid)"
            try:
                if cfg.action == "ban":
                    await member.ban(reason=reason, delete_message_seconds=0)
                else:
                    await member.kick(reason=reason)
                await self._log(
                    guild, cfg,
                    f"**{cfg.action}ed** {member} (`{member.id}`) — {reason}",
                    0xF57C00,
                )
            except discord.HTTPException:
                pass

        if len(joins) >= cfg.join_threshold:
            await self._trigger_lockdown(guild, cfg)

    antiraid = app_commands.Group(
        name="antiraid", description="anti-raid configuration", default_permissions=discord.Permissions(manage_guild=True)
    )

    @antiraid.command(name="config", description="configure anti-raid thresholds")
    @app_commands.describe(
        enabled="turn detection on or off",
        join_threshold="joins within the window that count as a raid",
        join_window="window in seconds",
        account_age_min_days="min account age before a join is treated as suspicious",
        action="action to take against suspicious new accounts",
        log_channel="channel to post anti-raid alerts to",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="kick", value="kick"),
            app_commands.Choice(name="ban", value="ban"),
        ]
    )
    async def config(
        self,
        interaction: discord.Interaction,
        enabled: bool | None = None,
        join_threshold: app_commands.Range[int, 2, 100] | None = None,
        join_window: app_commands.Range[int, 3, 300] | None = None,
        account_age_min_days: app_commands.Range[int, 0, 90] | None = None,
        action: app_commands.Choice[str] | None = None,
        log_channel: discord.TextChannel | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return
        cfg = await RaidConfig.load(self.bot, guild.id)
        if enabled is not None:
            cfg.enabled = enabled
        if join_threshold is not None:
            cfg.join_threshold = join_threshold
        if join_window is not None:
            cfg.join_window = join_window
        if account_age_min_days is not None:
            cfg.account_age_min_days = account_age_min_days
        if action is not None:
            cfg.action = action.value
        if log_channel is not None:
            cfg.log_channel_id = log_channel.id
        await cfg.save(self.bot)

        lines = [
            "**anti-raid config**",
            f"enabled: `{cfg.enabled}`",
            f"join threshold: `{cfg.join_threshold}` per `{cfg.join_window}s`",
            f"min account age: `{cfg.account_age_min_days}d`",
            f"action: `{cfg.action}`",
            f"log channel: {f'<#{cfg.log_channel_id}>' if cfg.log_channel_id else 'not set'}",
        ]
        layout = BaseLayout()
        layout.add_container(discord.ui.TextDisplay("\n".join(lines)), accent_color=0x5865F2)
        await interaction.response.send_message(view=layout, ephemeral=True)

    @antiraid.command(name="lockdown", description="manually trigger or lift lockdown")
    @app_commands.describe(state="on to lock the server, off to unlock it")
    @app_commands.choices(
        state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")]
    )
    async def lockdown_cmd(self, interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        guild = interaction.guild
        if guild is None:
            return
        cfg = await RaidConfig.load(self.bot, guild.id)
        await interaction.response.defer(ephemeral=True)
        if state.value == "on":
            await self._trigger_lockdown(guild, cfg)
            await interaction.followup.send("lockdown engaged", ephemeral=True)
        else:
            await self._lift_lockdown(guild, cfg)
            await interaction.followup.send("lockdown lifted", ephemeral=True)


async def setup(bot: "Bot") -> None:
    await bot.add_cog(AntiRaidCog(bot))
