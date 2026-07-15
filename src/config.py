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

    discord_client_id: str = os.getenv("DISCORD_CLIENT_ID", "")
