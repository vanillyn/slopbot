from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class BotConfig:
    token: str = os.getenv("DISCORD_TOKEN", "")
    command_prefix: str = os.getenv("COMMAND_PREFIX", ">>")
    db_path: str = os.getenv("DB_PATH", "data/bot.db")

    # dashboard (src/web/server.py) — this is the only network-facing server
    # the bot itself runs. twitch no longer needs one; see eventsub.py.
    dashboard_enabled: bool = _bool("DASHBOARD_ENABLED", True)
    dashboard_host: str = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    dashboard_port: int = int(os.getenv("DASHBOARD_PORT", "8081"))
    # origin allowed to call the dashboard API via CORS. set this to your
    # static frontend's URL (e.g. https://you.github.io) when the frontend
    # isn't served from the same place as this API. "*" is fine for local
    # testing but browsers will reject credentialed requests against it in
    # some setups, so prefer setting a real origin once deployed.
    dashboard_origin: str = os.getenv("DASHBOARD_ORIGIN", "*")

    # twitch EventSub webhook listener (src/cogs/twitch/webserver.py) — required
    # to track streamers other than the app owner; see TWITCH_WEBHOOK_SECRET.
    # runs on its own port, separate from the dashboard above.
    twitch_webhook_enabled: bool = _bool("TWITCH_WEBHOOK_ENABLED", True)
    twitch_webhook_host: str = os.getenv("TWITCH_WEBHOOK_HOST", "0.0.0.0")
    twitch_webhook_port: int = int(os.getenv("TWITCH_WEBHOOK_PORT", "8082"))
    # public https url twitch will POST event deliveries to, e.g.
    # https://flowerco.aichi.me:8082/webhook/twitch — must be reachable from
    # the internet and match whatever port/host this process binds above.
    twitch_webhook_callback_url: str = os.getenv("TWITCH_WEBHOOK_CALLBACK_URL", "")

    discord_client_id: str = os.getenv("DISCORD_CLIENT_ID", "")
