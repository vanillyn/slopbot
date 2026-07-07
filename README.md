# discord bot — modular monolith

```
discordbot/
├── main.py                     entry point: logging, bot, run loop
├── requirements.txt
├── .env.example
├── data/                       sqlite db + yt-dlp cache live here (gitignored)
└── src/
    ├── bot.py                  Bot subclass: db, twitch client, extension loading
    ├── config.py               env-driven BotConfig
    ├── permissions.py          role -> permission node overrides (shared by all cogs)
    ├── data/
    │   ├── db.py               Database: single aiosqlite conn + schema, passed to every cog
    │   └── config.py           GuildConfig / ModerationConfig defaults
    ├── utils/
    │   ├── ui.py                BaseLayout/BaseView/ConfirmView/PaginatedLayout helpers (components v2)
    │   └── logger.py
    └── cogs/
        ├── moderation/
        │   ├── cog.py           warn/kick/ban/mute/slowmode/purge/shutdown
        │   ├── infractions.py   case log persistence
        │   ├── logging.py       posts infractions to the configured log channel
        │   └── util.py          hierarchy checks + require_permission()
        ├── antiraid/
        │   └── cog.py           join-rate tracking, new-account filter, auto lockdown
        ├── ticketing/
        │   ├── cog.py           panel command, persistent open/close buttons
        │   └── db.py
        ├── twitch/
        │   ├── cog.py           setup/edit/untrack/testlive commands
        │   ├── api.py           TwitchClient (one aiohttp session, token refresh)
        │   ├── webserver.py     aiohttp.web eventsub listener
        │   ├── notifications.py live-notification layout builder
        │   └── db.py
        └── music/
            ├── cog.py           /play /skip /stop, yt-dlp offloaded to executor
            └── queue.py          per-guild queue, isolated cog state
```

## why it's structured this way

- **every cog is its own file/package** — nothing shares logic across feature boundaries except
  `src/permissions.py`, `src/data/db.py`, and `src/utils/ui.py`, which are intentionally shared
  infrastructure, not feature logic.
- **no global in-memory state for persistent data.** tickets, raid config, infractions, and
  twitch streamer configs all live in sqlite via `bot.db`. the only in-memory state is
  the anti-raid join-rate tracker and the music queue, both scoped to their own cog instance —
  neither is a module-level global, and both are fine to lose on restart.
- **the twitch webhook listener runs on the bot's own event loop**, started from
  `TwitchCog.cog_load()` using `aiohttp.web.AppRunner` + `TCPSite`. this is non-blocking by
  construction (it just binds a socket and lets the loop's selector handle it), so it never
  blocks the gateway connection.
- **failure isolation**: `Bot.setup_hook()` loads each extension in its own try/except, so if
  yt-dlp or the twitch webhook fail to import/start, moderation and anti-raid still come up.
  yt-dlp calls are additionally offloaded to a thread executor so a slow/broken download can't
  stall the event loop.

## running it

```
pip install -r requirements.txt
cp .env.example .env   # fill in DISCORD_TOKEN, twitch creds if you want streamer notifications
python main.py
```

the twitch webhook needs a public HTTPS URL pointing at `WEBHOOK_HOST:WEBHOOK_PORT/webhook/twitch`
(reverse-proxy it) — set that as `TWITCH_CALLBACK_URL`. if you don't need twitch notifications,
set `TWITCH_WEBHOOK_ENABLED=false` and leave the twitch env vars blank; the cog still loads for
slash commands but skips starting the listener.

## known gaps / things to wire up before production

- `permissions.py`'s `permission_overrides` table has no admin command yet to grant/revoke
  nodes — `grant()`/`revoke()` exist in `src/permissions.py`, just add a slash command wrapper
  if you want non-admins running moderation commands.
- anti-raid lockdown state is per-guild in sqlite (`raid_config.lockdown_active`), but the
  actual channel permission overwrites aren't diffed/restored — `unshutdown`/`lockdown off`
  clears the override entirely rather than remembering per-channel prior state. fine for most
  servers, worth tightening if you have channels with custom `send_messages` overrides already.
- music has no queue-list/now-playing command yet, just play/skip/stop.
