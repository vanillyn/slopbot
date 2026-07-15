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
    │   ├── db.py               Database: single aiosqlite conn + full schema + migrations
    │   ├── config.py           GuildConfig — THE per-guild settings model (see below)
    │   └── button_containers.py
    ├── utils/
    │   ├── ui.py                BaseLayout/BaseView/ConfirmView/PaginatedLayout helpers (components v2)
    │   └── logger.py
    ├── web/
    │   ├── server.py            DashboardServer: oauth-gated JSON API + static file serving
    │   └── static/              the dashboard/landing page itself (plain html/css/js)
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
        │   ├── eventsub.py       EventSub over WebSocket — no public server needed
        │   ├── notifications.py live-notification layout builder
        │   └── db.py
        ├── music/
        │   ├── cog.py           /play /skip /stop, yt-dlp offloaded to executor
        │   └── queue.py          per-guild queue, isolated cog state
        └── dashboard/
            └── cog.py            starts/stops DashboardServer alongside the bot
```

## configuration — one model, `src/data/config.py`

Previously settings were split across a bespoke dashboard key/value table and a bunch of
`cfg.moderation.xxx` attributes that `moderation/cog.py` assumed existed but were never
defined anywhere. That's fixed: **`GuildConfig` in `src/data/config.py` is now the only
place a per-guild setting is defined.**

- `GuildConfig.moderation` (`ModerationConfig`) — every default reason, DM template, and
  channel message template moderation commands use, plus `mute_role`/`mute_channel` and
  `require_confirm`.
- `GuildConfig.dashboard` (`DashboardConfig`) — the role/channel settings the web dashboard
  edits (moderator/admin/member/image/music roles, ticket channel + message).

It's stored as one JSON blob per guild in the `guild_config` table (see `src/data/db.py`),
loaded with `await GuildConfig.load(bot.db, guild_id)` and written back with `await cfg.save(bot.db)`.
If you need a new setting: add a field with a default to the relevant dataclass. That's it —
no new table, no migration, and it round-trips through `to_dict()` for the dashboard for free.

`src/data/db.py` owns **all** schema — every table any cog uses is created there, including
migrations for older databases (e.g. `twitch_streamers` gaining a `guild_id` column for
multi-guild support without losing existing rows).

## twitch live notifications — no public server required

The old setup needed a public HTTPS callback URL, a webhook secret, and (for local testing)
something like DuckDNS + a reverse proxy just to receive Twitch's `stream.online` events.

That's gone. `src/cogs/twitch/eventsub.py` uses **EventSub over WebSocket**: the bot opens
one outbound connection to `wss://eventsub.wss.twitch.tv/ws`, and Twitch pushes events over
that connection directly. There is nothing to expose to the internet — this works identically
whether the bot runs on your laptop, behind NAT, or on a VPS.

Setup is just:

1. Create a Twitch application at <https://dev.twitch.tv/console/apps> (any redirect URL
   works, it's unused for this flow — App Access Token / client-credentials grant only).
2. Put the client id/secret in `.env`:
   ```
   TWITCH_CLIENT_ID=...
   TWITCH_CLIENT_SECRET=...
   ```
3. `/setup <username>` in a server. That's it — no callback URL, no webhook secret, no
   port forwarding.

(The client-credentials/webhook-secret env vars for the old callback flow —
`TWITCH_WEBHOOK_SECRET`, `TWITCH_CALLBACK_URL`, `TWITCH_WEBHOOK_ENABLED`, `WEBHOOK_HOST`,
`WEBHOOK_PORT` — are gone; delete them from your `.env` if you have an old one.)

## dashboard

`src/cogs/dashboard/cog.py` starts a single `DashboardServer` (`src/web/server.py`) alongside
the bot. It serves the static frontend in `src/web/static/` *and* a JSON API behind Discord
OAuth (implicit grant — the browser gets a user token directly, no client secret touches the
frontend).

There used to be a second, unauthenticated HTML dashboard baked into the Twitch webhook
listener (`webserver.py`'s `_build_dashboard_page`). That's been removed — it was dead weight
duplicating this one and a likely source of "the dashboard breaks locally" confusion, since it
ran on a separate port with none of the guild-access checks the real dashboard has.
Delete `src/cogs/twitch/webserver.py` and `tests/test_webserver_dashboard.py` if you still have
them from before this change.

### running it locally

```
cp .env.example .env    # fill in DISCORD_TOKEN, DISCORD_CLIENT_ID, twitch creds if wanted
python main.py
```

The dashboard comes up at `http://localhost:8081` by default (`DASHBOARD_HOST`/`DASHBOARD_PORT`
in `.env`). Discord's OAuth implicit grant accepts `http://localhost...` redirect URIs for
testing, so logging in locally works out of the box — just add
`http://localhost:8081/` as a redirect URI on your Discord application (OAuth2 → Redirects).

### hosting it for free

The frontend (`src/web/static/`) is plain HTML/CSS/JS with no build step, and it already talks
to the API over `fetch()` with CORS — so frontend and backend don't have to live in the same
place. Two free options:

**Option A — everything on your machine.** Simplest. Point a free dynamic-DNS hostname
(DuckDNS) at your home IP, forward `DASHBOARD_PORT` through your router, and put a lightweight
reverse proxy (Caddy is easiest — it gets you free HTTPS via Let's Encrypt automatically) in
front of `DASHBOARD_HOST:DASHBOARD_PORT`. Set the Discord OAuth redirect URI and
`DASHBOARD_ORIGIN` to that DuckDNS URL. The bot serves both the frontend and the API; nothing
else to deploy.

**Option B — static frontend, bot stays home.** Host `src/web/static/` on GitHub Pages or
Cloudflare Pages (both free, both give you real HTTPS instantly, no DuckDNS/port-forwarding
needed for the frontend itself). Then either:
   - point the frontend at your bot over DuckDNS + Caddy as in Option A (you still need *some*
     way to reach the bot's machine from the internet for the API calls), or
   - use a **Cloudflare Tunnel** (also free) from the bot's machine instead of DuckDNS/port
     forwarding — it gives you a public HTTPS URL for the dashboard API without opening any
     ports on your router at all, which is generally the least fiddly option if you don't want
     to touch your router's config.

  Either way:
  1. In `src/web/static/index.html`, set `window.COCO_API_BASE` to wherever the API ends up
     being reachable, e.g. `"https://coco.duckdns.org"` or your Cloudflare Tunnel URL.
  2. Set `DASHBOARD_ORIGIN` in `.env` to your GitHub Pages/Cloudflare Pages URL, so the API's
     CORS allows the static frontend through.
  3. Add that same static-hosting URL as a redirect URI on your Discord application.

Twitch notifications need none of this — see the section above, it's a plain outbound
connection either way.

### testing purely on localhost (no tunnel at all)

Discord's OAuth matches `redirect_uri` with **exact string comparison** — it does not
normalize trailing slashes, so `http://localhost:8081` and `http://localhost:8081/` are
different URIs as far as Discord is concerned. `app.js` now always sends the bare origin
with no trailing slash and no path, so:

1. In the Discord Developer Portal → your app → OAuth2 → General → Redirects, add exactly:
   `http://localhost:8081` (no trailing slash, no `/callback`, nothing after the port).
2. Restart the bot, open `http://localhost:8081` in a browser, click log in.

If you still get "invalid redirect_uri", open the login link Discord sends you to and look
at the `redirect_uri=` query parameter in the address bar (URL-decode it) — whatever's there
has to be byte-for-byte identical to what you registered.

### temporary public access without owning a domain

If you want a public HTTPS URL just long enough to configure the bot from somewhere other
than the machine it runs on (or because your OAuth app requires https and localhost isn't an
option for your use case), the easiest zero-setup option is a **Cloudflare quick tunnel** —
this is different from a regular (named) Cloudflare Tunnel and does *not* require you to own
a domain or even have a Cloudflare account:

```
# install cloudflared, then:
cloudflared tunnel --url http://localhost:8081
```

This prints a random `https://something-random-words.trycloudflare.com` URL within a few
seconds. That URL is a real, valid HTTPS endpoint proxying straight to your local dashboard.
To use it:

1. Add that exact URL (no trailing slash) as a redirect URI in the Discord Developer Portal.
2. Set `DASHBOARD_ORIGIN=https://something-random-words.trycloudflare.com` in `.env` and
   restart the bot.
3. Open that URL instead of `localhost:8081` and log in.

It's disposable — closing the `cloudflared` process kills the URL, and a new run gives you a
new random one, so you'll re-register the redirect URI each time. Fine for "get in long
enough to change some settings," not meant to be permanent (that's the DuckDNS/named-tunnel
setup from the previous section).

**If you'd rather fix ngrok:** the SSL error is almost always caused by telling ngrok to
tunnel as if the local server were already HTTPS. Run it as plain HTTP on the inside:
```
ngrok http 8081
```
not `ngrok http https://localhost:8081` — ngrok terminates TLS itself and proxies to your
local server over plain HTTP, so pointing it at an `https://` local address makes it attempt
a second, unnecessary TLS handshake against a port that isn't serving TLS, which is what
throws the SSL error. Use the `https://xxxx.ngrok-free.app` forwarding URL it prints (again,
no trailing slash) as the redirect URI and `DASHBOARD_ORIGIN`. Also note ngrok's free tier
shows an interstitial "you are about to visit" warning page on first load — that's normal,
just click through it, it isn't the SSL error.

## known gaps / things to wire up before production

- `permissions.py`'s `permission_overrides` table has no admin command yet to grant/revoke
  nodes — `grant()`/`revoke()` exist in `src/permissions.py`, just add a slash command wrapper
  if you want non-admins running moderation commands.
- anti-raid lockdown state is per-guild in sqlite (`raid_config.lockdown_active`), but the
  actual channel permission overwrites aren't diffed/restored — `unshutdown`/`lockdown off`
  clears the override entirely rather than remembering per-channel prior state. fine for most
  servers, worth tightening if you have channels with custom `send_messages` overrides already.
- the dashboard's OAuth flow is implicit-grant (token lives in the URL fragment, never touches
  a server). that's fine for a self-hosted single-operator dashboard, but if you're exposing
  this more broadly, consider moving to the authorization-code flow with a backend token
  exchange instead.
