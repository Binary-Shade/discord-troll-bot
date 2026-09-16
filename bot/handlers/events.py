import logging

import discord
from discord.ext import commands

from bot.services.reply_pipeline import handle_message

logger = logging.getLogger("genz_troll_bot.events")


class EventHandlers(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("Logged in as %s (id=%s)", self.bot.user, self.bot.user.id)
        try:
            synced = await self.bot.tree.sync()
            logger.info("Synced %d slash commands", len(synced))
        except discord.HTTPException:
            logger.exception("Failed to sync slash commands")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            await handle_message(message, self.bot.db, self.bot.rate_limiter)  # type: ignore[attr-defined]
        except Exception:
            logger.exception("Unhandled error in message pipeline")

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, discord.app_commands.CheckFailure):
            await interaction.response.send_message(
                "nah you don't have perms for that \U0001F6AB", ephemeral=True
            )
            return
        logger.exception("App command error", exc_info=error)
        if not interaction.response.is_done():
            await interaction.response.send_message("something broke, L", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EventHandlers(bot))
