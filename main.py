from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv

load_dotenv()
from src.bot import Bot
from src.config import BotConfig



def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)


async def main() -> None:
    setup_logging()
    config = BotConfig()
    if not config.token:
        raise SystemExit("DISCORD_TOKEN is not set (check your .env)")

    bot = Bot(config)
    async with bot:
        await bot.start(config.token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
