from __future__ import annotations

from datetime import datetime

import discord
from discord.ext import commands

from src.cogs.twitch.db import get_all_streamers
from src.utils.logger import get_logger

log = get_logger("twitch.notifications")


class LiveNotificationView(discord.ui.LayoutView):
    def __init__(
        self,
        stream_url: str,
        profile_pic: str,
        custom_msg: str,
        footer_msg: str,
        stream_title: str,
        game: str,
        thumbnail_url: str,
        relative_ts: str,
        accent_color: int,
        ping_role_id: int,
    ) -> None:
        super().__init__()
        footer_parts = footer_msg + (f" | {relative_ts}" if relative_ts else "")
        text = f"# {custom_msg}\n[{stream_title}]({stream_url})\nplaying **{game}**"
        if ping_role_id:
            text = f"<@&{ping_role_id}>\n{text}"

        container = discord.ui.Container(
            discord.ui.Section(
                discord.ui.TextDisplay(text),
                accessory=discord.ui.Thumbnail(media=profile_pic),
            ),
            discord.ui.MediaGallery(
                discord.MediaGalleryItem(media=thumbnail_url),
            ),
            discord.ui.TextDisplay(f"-# {footer_parts}"),
            discord.ui.ActionRow(
                discord.ui.Button(
                    label="watch live",
                    url=stream_url,
                    style=discord.ButtonStyle.link,
                )
            ),
            accent_color=discord.Color(accent_color),
        )
        self.add_item(container)


async def _send_to_streamer(bot: commands.Bot, streamer: dict[str, object]) -> None:
    channel_id = int(streamer["discord_channel_id"])  # type: ignore[arg-type]
    if not channel_id:
        log.warning("no channel set for %s", streamer["twitch_username"])
        return

    try:
        channel = await bot.fetch_channel(channel_id)
    except discord.NotFound:
        log.error("channel %s not found", channel_id)
        return
    except discord.Forbidden:
        log.error("no access to channel %s", channel_id)
        return

    if not isinstance(channel, discord.TextChannel):
        log.error("channel %s is not a text channel", channel_id)
        return

    twitch = bot.twitch  # type: ignore[attr-defined]
    broadcaster_id = str(streamer["twitch_user_id"])
    user_info = await twitch.get_user_info(broadcaster_id)
    if user_info is None:
        log.error("could not fetch user info for %s", broadcaster_id)
        return

    stream_info = await twitch.get_stream(broadcaster_id)
    follower_count = await twitch.get_follower_count(broadcaster_id)

    display_name: str = user_info["display_name"]
    profile_pic: str = user_info["profile_image_url"]
    stream_url = f"https://twitch.tv/{streamer['twitch_username']}"
    stream_title = stream_info["title"] if stream_info else "untitled stream"
    game = stream_info["game_name"] if stream_info else "unknown"
    thumbnail_url = (
        stream_info["thumbnail_url"].replace("{width}", "1280").replace("{height}", "720")
        if stream_info
        else profile_pic
    )

    relative_ts = ""
    if stream_info and stream_info.get("started_at"):
        started_at = datetime.fromisoformat(stream_info["started_at"].replace("Z", "+00:00"))
        relative_ts = f"<t:{int(started_at.timestamp())}:R>"

    custom_msg = str(streamer["custom_message"]).replace("{user}", display_name)
    footer_msg = str(streamer["footer_message"]).replace("{followers}", f"{follower_count:,}")

    view = LiveNotificationView(
        stream_url=stream_url,
        profile_pic=profile_pic,
        custom_msg=custom_msg,
        footer_msg=footer_msg,
        stream_title=stream_title,
        game=game,
        thumbnail_url=thumbnail_url,
        relative_ts=relative_ts,
        accent_color=int(streamer["accent_color"]),  # type: ignore[arg-type]
        ping_role_id=int(streamer["ping_role_id"]),  # type: ignore[arg-type]
    )

    await channel.send(view=view)
    log.info("sent live notification for %s to channel %s", display_name, channel_id)


async def send_live_notification(bot: commands.Bot, broadcaster_id: str) -> None:
    streamers = await get_all_streamers(bot.db)  # type: ignore[attr-defined]
    matching = [streamer for streamer in streamers if str(streamer["twitch_user_id"]) == broadcaster_id]
    if not matching:
        log.warning("no streamer found for %s", broadcaster_id)
        return

    for streamer in matching:
        await _send_to_streamer(bot, streamer)
