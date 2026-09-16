import asyncio
import logging

import discord
from discord.ext import commands

from bot.config.settings import settings, validate_settings
from bot.services.database import Database
from bot.services.rate_limiter import RateLimiter

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("genz_troll_bot")


class TrollBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # required to read message text
        intents.members = False
        super().__init__(command_prefix="!troll-unused!", intents=intents)

        self.db = Database(settings.database_path)
        self.rate_limiter = RateLimiter(
            global_cooldown=settings.global_cooldown_seconds,
            per_user_cooldown=settings.per_user_cooldown_seconds,
            per_channel_cooldown=settings.per_channel_cooldown_seconds,
            max_replies_per_minute=settings.max_replies_per_minute,
        )

    async def setup_hook(self):
        await self.db.connect()
        await self.load_extension("bot.handlers.events")
        await self.load_extension("bot.handlers.commands")

    async def close(self):
        await self.db.close()
        await super().close()


async def main():
    validate_settings()
    bot = TrollBot()
    async with bot:
        try:
            await bot.start(settings.discord_token)
        except discord.PrivilegedIntentsRequired as exc:
            raise SystemExit(
                "Discord rejected the bot because Message Content Intent is not enabled. "
                "Open Discord Developer Portal -> your application -> Bot -> Privileged "
                "Gateway Intents, enable Message Content Intent, save changes, then rerun "
                "`python -m bot.main`."
            ) from exc


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down.")
