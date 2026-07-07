import asyncio

from src.cogs.twitch.webserver import _build_dashboard_page


def test_dashboard_page_renders_without_template_errors() -> None:
    page = asyncio.run(_build_dashboard_page(None))

    assert "arcade control panel" in page.lower()
    assert "/api/music/queue" in page
