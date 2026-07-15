from __future__ import annotations

import hashlib
import hmac
import json

from aiohttp.test_utils import TestClient, TestServer

from src.cogs.twitch.webserver import WEBHOOK_PATH, build_app


def _sign(secret: str, msg_id: str, timestamp: str, body: bytes) -> str:
    hmac_message = (msg_id + timestamp).encode() + body
    return "sha256=" + hmac.new(secret.encode(), hmac_message, hashlib.sha256).hexdigest()


def test_webhook_rejects_bad_signature(monkeypatch) -> None:
    monkeypatch.setattr("src.cogs.twitch.webserver.TWITCH_WEBHOOK_SECRET", "test-secret")

    async def scenario() -> None:
        notified = []

        async def notify(broadcaster_id: str) -> None:
            notified.append(broadcaster_id)

        app = build_app(notify)
        async with TestClient(TestServer(app)) as client:
            body = json.dumps({"subscription": {"type": "stream.online"}}).encode()
            resp = await client.post(
                WEBHOOK_PATH,
                data=body,
                headers={
                    "Twitch-Eventsub-Message-Id": "1",
                    "Twitch-Eventsub-Message-Timestamp": "t",
                    "Twitch-Eventsub-Message-Signature": "sha256=wrong",
                    "Twitch-Eventsub-Message-Type": "notification",
                },
            )
            assert resp.status == 403
            assert notified == []

    import asyncio
    asyncio.run(scenario())


def test_webhook_verification_challenge_is_echoed_back(monkeypatch) -> None:
    secret = "test-secret"
    monkeypatch.setattr("src.cogs.twitch.webserver.TWITCH_WEBHOOK_SECRET", secret)

    async def scenario() -> None:
        async def notify(broadcaster_id: str) -> None:
            pass

        app = build_app(notify)
        async with TestClient(TestServer(app)) as client:
            body = json.dumps({"challenge": "abc123"}).encode()
            signature = _sign(secret, "msg-1", "2024-01-01T00:00:00Z", body)
            resp = await client.post(
                WEBHOOK_PATH,
                data=body,
                headers={
                    "Twitch-Eventsub-Message-Id": "msg-1",
                    "Twitch-Eventsub-Message-Timestamp": "2024-01-01T00:00:00Z",
                    "Twitch-Eventsub-Message-Signature": signature,
                    "Twitch-Eventsub-Message-Type": "webhook_callback_verification",
                },
            )
            assert resp.status == 200
            text = await resp.text()
            assert text == "abc123"

    import asyncio
    asyncio.run(scenario())


def test_webhook_notification_triggers_callback_for_stream_online(monkeypatch) -> None:
    secret = "test-secret"
    monkeypatch.setattr("src.cogs.twitch.webserver.TWITCH_WEBHOOK_SECRET", secret)

    async def scenario() -> None:
        notified = []

        async def notify(broadcaster_id: str) -> None:
            notified.append(broadcaster_id)

        app = build_app(notify)
        async with TestClient(TestServer(app)) as client:
            payload = {
                "subscription": {"type": "stream.online"},
                "event": {"broadcaster_user_id": "12345"},
            }
            body = json.dumps(payload).encode()
            signature = _sign(secret, "msg-2", "2024-01-01T00:00:00Z", body)
            resp = await client.post(
                WEBHOOK_PATH,
                data=body,
                headers={
                    "Twitch-Eventsub-Message-Id": "msg-2",
                    "Twitch-Eventsub-Message-Timestamp": "2024-01-01T00:00:00Z",
                    "Twitch-Eventsub-Message-Signature": signature,
                    "Twitch-Eventsub-Message-Type": "notification",
                },
            )
            assert resp.status == 204
            assert notified == ["12345"]

    import asyncio
    asyncio.run(scenario())


def test_webhook_refuses_when_secret_not_configured(monkeypatch) -> None:
    monkeypatch.setattr("src.cogs.twitch.webserver.TWITCH_WEBHOOK_SECRET", "")

    async def scenario() -> None:
        async def notify(broadcaster_id: str) -> None:
            pass

        app = build_app(notify)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                WEBHOOK_PATH,
                data=b"{}",
                headers={
                    "Twitch-Eventsub-Message-Id": "1",
                    "Twitch-Eventsub-Message-Timestamp": "t",
                    "Twitch-Eventsub-Message-Signature": "sha256=whatever",
                    "Twitch-Eventsub-Message-Type": "notification",
                },
            )
            assert resp.status == 403

    import asyncio
    asyncio.run(scenario())
