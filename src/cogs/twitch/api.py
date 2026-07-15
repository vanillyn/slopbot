from __future__ import annotations

import os

import aiohttp

from src.utils.logger import get_logger

log = get_logger("twitch.api")

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")
# webhook transport (see webserver.py) — required to track streamers other than
# the app owner. websocket transport only works for broadcasters who've
# authorized this app via user OAuth, which in practice means just yourself;
# webhook transport uses an app access token and works for anyone.
TWITCH_WEBHOOK_SECRET = os.getenv("TWITCH_WEBHOOK_SECRET", "")
TWITCH_WEBHOOK_CALLBACK_URL = os.getenv("TWITCH_WEBHOOK_CALLBACK_URL", "")


class TwitchClient:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._token: str = ""

    async def start(self) -> None:
        self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    def _headers(self) -> dict[str, str]:
        return {"Client-Id": TWITCH_CLIENT_ID, "Authorization": f"Bearer {self._token}"}

    async def _get_token(self) -> str:
        assert self._session is not None
        if self._token:
            return self._token
        resp = await self._session.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": TWITCH_CLIENT_ID,
                "client_secret": TWITCH_CLIENT_SECRET,
                "grant_type": "client_credentials",
            },
        )
        data = await resp.json()
        self._token = data["access_token"]
        return self._token

    async def _request(self, method: str, url: str, **kwargs: object) -> aiohttp.ClientResponse:
        assert self._session is not None
        await self._get_token()
        resp = await self._session.request(method, url, headers=self._headers(), **kwargs)
        if resp.status == 401:
            self._token = ""
            await self._get_token()
            resp = await self._session.request(method, url, headers=self._headers(), **kwargs)
        return resp

    async def get_user_id(self, username: str) -> tuple[str, str] | None:
        resp = await self._request(
            "GET", "https://api.twitch.tv/helix/users", params={"login": username}
        )
        data = await resp.json()
        if not data.get("data"):
            return None
        user = data["data"][0]
        return user["id"], user["display_name"]

    async def get_user_info(self, user_id: str) -> dict[str, str] | None:
        resp = await self._request(
            "GET", "https://api.twitch.tv/helix/users", params={"id": user_id}
        )
        data = await resp.json()
        if not data.get("data"):
            return None
        return data["data"][0]

    async def get_stream(self, broadcaster_id: str) -> dict[str, str] | None:
        resp = await self._request(
            "GET",
            "https://api.twitch.tv/helix/streams",
            params={"user_id": broadcaster_id},
        )
        data = await resp.json()
        if not data.get("data"):
            return None
        return data["data"][0]

    async def get_follower_count(self, broadcaster_id: str) -> int:
        resp = await self._request(
            "GET",
            "https://api.twitch.tv/helix/channels/followers",
            params={"broadcaster_id": broadcaster_id},
        )
        if resp.status != 200:
            return 0
        data = await resp.json()
        return int(data.get("total", 0))

    async def subscribe_to_stream_online_ws(self, broadcaster_user_id: str, session_id: str) -> str | None:
        """subscribe using websocket transport — the subscription is delivered to
        the eventsub websocket connection identified by `session_id`, no public
        callback url involved.

        note: with an app access token, websocket transport only delivers
        events for broadcasters who have authorized this app (e.g. via a user
        OAuth flow). in practice that limits this to your own channel unless
        every tracked streamer separately authorizes the app. use
        subscribe_to_stream_online_webhook for tracking arbitrary streamers."""
        resp = await self._request(
            "POST",
            "https://api.twitch.tv/helix/eventsub/subscriptions",
            json={
                "type": "stream.online",
                "version": "1",
                "condition": {"broadcaster_user_id": broadcaster_user_id},
                "transport": {"method": "websocket", "session_id": session_id},
            },
        )
        if resp.status != 202:
            log.error("eventsub subscribe failed: %s %s", resp.status, await resp.text())
            return None
        data = await resp.json()
        return data["data"][0]["id"]

    async def subscribe_to_stream_online_webhook(
        self, broadcaster_user_id: str, callback_url: str, secret: str
    ) -> str | None:
        """subscribe using webhook transport — twitch POSTs events to
        `callback_url` (must be a public https url), signed with `secret`.
        works for any broadcaster, no per-user OAuth needed, since this uses
        an app access token."""
        resp = await self._request(
            "POST",
            "https://api.twitch.tv/helix/eventsub/subscriptions",
            json={
                "type": "stream.online",
                "version": "1",
                "condition": {"broadcaster_user_id": broadcaster_user_id},
                "transport": {"method": "webhook", "callback": callback_url, "secret": secret},
            },
        )
        if resp.status != 202:
            log.error("eventsub webhook subscribe failed: %s %s", resp.status, await resp.text())
            return None
        data = await resp.json()
        return data["data"][0]["id"]

    async def unsubscribe(self, subscription_id: str) -> None:
        if not subscription_id:
            return
        await self._request(
            "DELETE",
            "https://api.twitch.tv/helix/eventsub/subscriptions",
            params={"id": subscription_id},
        )
