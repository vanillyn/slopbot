from __future__ import annotations

from src.cogs.music.queue import QueueCog


class DummyBot:
    pass


def test_queue_tracks_and_peek_order() -> None:
    cog = QueueCog(DummyBot())
    cog.add_to_queue(42, "/tmp/a.mp3", {"title": "A"}, True)
    cog.add_to_queue(42, "/tmp/b.mp3", {"title": "B"}, True)

    queued = cog.peek(42)

    assert [track.metadata["title"] for track in queued] == ["A", "B"]
