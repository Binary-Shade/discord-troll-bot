"""Slash commands: /troll enable|disable|mode|status|cooldown|personality."""
import discord
from discord import app_commands
from discord.ext import commands

from bot.config.settings import settings
from bot.config.personality import HUMOR_MODES


def _is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        return (
            interaction.user.guild_permissions.manage_guild
            or interaction.user.id in settings.bot_admin_user_ids
        )
    return app_commands.check(predicate)


class TrollCommands(commands.GroupCog, name="troll"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]
        self.rate_limiter = bot.rate_limiter  # type: ignore[attr-defined]
        super().__init__()

    @app_commands.command(description="Re-enable troll replies in this channel")
    @_is_admin()
    async def enable(self, interaction: discord.Interaction):
        await self.db.set_channel_enabled(interaction.guild_id, interaction.channel_id, True)
        await interaction.response.send_message(
            f"aight, locked in \U0001F979 troll mode is ON in <#{interaction.channel_id}>",
            ephemeral=True,
        )

    @app_commands.command(description="Disable troll replies in this channel")
    @_is_admin()
    async def disable(self, interaction: discord.Interaction):
        await self.db.set_channel_enabled(interaction.guild_id, interaction.channel_id, False)
        await interaction.response.send_message(
            f"fine, going quiet \U0001F971 troll mode is OFF in <#{interaction.channel_id}>",
            ephemeral=True,
        )

    @app_commands.command(description="Set the bot's humor mode for this server")
    @app_commands.choices(
        mode=[app_commands.Choice(name=k, value=k) for k in HUMOR_MODES.keys()]
    )
    @_is_admin()
    async def mode(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        await self.db.update_guild_settings(interaction.guild_id, humor_mode=mode.value)
        await interaction.response.send_message(f"humor mode set to `{mode.value}`", ephemeral=True)

    @app_commands.command(description="Show current troll bot configuration for this server")
    async def status(self, interaction: discord.Interaction):
        settings = await self.db.get_guild_settings(interaction.guild_id)
        enabled = await self.db.is_channel_enabled(interaction.guild_id, interaction.channel_id)
        embed = discord.Embed(title="troll bot status", color=discord.Color.dark_purple())
        embed.add_field(name="this channel", value="enabled" if enabled else "disabled")
        embed.add_field(name="humor mode", value=settings["humor_mode"])
        embed.add_field(name="response probability", value=f"{settings['response_probability']:.2f}")
        embed.add_field(name="cooldown (s)", value=str(settings["cooldown_seconds"]))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Set response probability (0.0-1.0) and base cooldown seconds")
    @_is_admin()
    async def cooldown(
        self,
        interaction: discord.Interaction,
        probability: app_commands.Range[float, 0.0, 1.0] = None,
        seconds: app_commands.Range[int, 0, 3600] = None,
    ):
        kwargs = {}
        if probability is not None:
            kwargs["response_probability"] = probability
        if seconds is not None:
            kwargs["cooldown_seconds"] = seconds
            self.rate_limiter.global_cooldown = seconds
        if kwargs:
            await self.db.update_guild_settings(interaction.guild_id, **kwargs)
        await interaction.response.send_message("updated \U0001F44D", ephemeral=True)

    @app_commands.command(description="Opt yourself in or out of being roasted")
    @app_commands.choices(
        choice=[
            app_commands.Choice(name="opt out", value="out"),
            app_commands.Choice(name="opt in", value="in"),
        ]
    )
    async def personality(self, interaction: discord.Interaction, choice: app_commands.Choice[str]):
        # naming kept as "personality" isn't ideal for opt-out; expose a clearer alias too
        if choice.value == "out":
            await self.db.opt_out(interaction.guild_id, interaction.user.id)
            await interaction.response.send_message("you're opted OUT of roasts now", ephemeral=True)
        else:
            await self.db.opt_in(interaction.guild_id, interaction.user.id)
            await interaction.response.send_message("you're opted back IN, brave choice", ephemeral=True)

    @app_commands.command(description="Clear the bot's stored running-joke memory for this server")
    @_is_admin()
    async def clearmemory(self, interaction: discord.Interaction):
        await self.db.clear_memory(interaction.guild_id)
        await interaction.response.send_message("memory wiped \U0001F9F9", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TrollCommands(bot))
