"""The full smart-reply decision pipeline described in the spec:

Incoming message
 -> check permissions/ignored channels
 -> check cooldowns
 -> analyze message + context
 -> decide whether it deserves a response (delegated to the AI)
 -> generate a funny response
 -> apply safety + spam checks
 -> send the reply
"""
import asyncio
import logging
import random
from dataclasses import dataclass

import discord

from bot.services.ai_service import ai_service
from bot.services.context_manager import context_manager
from bot.services.database import Database
from bot.services.rate_limiter import RateLimiter
from bot.services.safety_filter import is_reply_safe, sanitize_reply

logger = logging.getLogger("genz_troll_bot.pipeline")

# Skip obviously low-effort / low-signal messages before spending an API call.
MIN_MESSAGE_LENGTH = 3
_pending_replies: dict[int, "PendingReply"] = {}
_pending_tasks: set[int] = set()


@dataclass
class PendingReply:
    message: discord.Message
    content: str
    is_direct_mention: bool


async def handle_message(
    message: discord.Message,
    db: Database,
    rate_limiter: RateLimiter,
) -> None:
    if message.author.bot or message.webhook_id is not None:
        return
    if not message.guild:
        return
    if message.author.id == message.guild.me.id if message.guild.me else False:
        return

    bot_user = message.guild.me
    is_direct_mention = bot_user is not None and bot_user in message.mentions

    # 1. permissions / ignored channels
    enabled = await db.is_channel_enabled(message.guild.id, message.channel.id)
    if not enabled:
        return

    content = _message_content_for_context(message)
    if content:
        context_manager.add(
            message.channel.id,
            message.author.display_name,
            content,
            message_id=message.id,
            is_reply=message.reference is not None,
            mentions_bot=is_direct_mention,
            attachment_count=len(message.attachments),
        )

    content = message.content.strip()
    if len(content) < MIN_MESSAGE_LENGTH and not is_direct_mention:
        return
    if content.startswith(("/", "!", ".")):
        return  # likely another bot's command prefix

    if await db.is_opted_out(message.guild.id, message.author.id):
        return

    if rate_limiter.already_replied(message.id):
        return

    # 2. cooldowns
    can_reply, reason = rate_limiter.can_reply(
        message.author.id,
        message.channel.id,
        bypass_cooldowns=is_direct_mention,
    )
    if not can_reply:
        logger.debug("Skipping reply due to %s", reason)
        await _queue_pending_reply(
            message=message,
            content=content,
            is_direct_mention=is_direct_mention,
            db=db,
            rate_limiter=rate_limiter,
        )
        return

    await _generate_and_send_reply(
        message=message,
        content=content,
        is_direct_mention=is_direct_mention,
        db=db,
        rate_limiter=rate_limiter,
        bypass_probability=False,
    )


async def _generate_and_send_reply(
    message: discord.Message,
    content: str,
    is_direct_mention: bool,
    db: Database,
    rate_limiter: RateLimiter,
    bypass_probability: bool,
) -> None:
    bot_user = message.guild.me if message.guild else None
    if bot_user is None:
        return

    guild_settings = await db.get_guild_settings(message.guild.id)

    # Mentions are intentional, so answer them reliably. Ambient messages stay
    # probabilistic so the bot does not dominate normal chat.
    if (
        not bypass_probability
        and not is_direct_mention
        and random.random() > guild_settings["response_probability"]
    ):
        return

    # 3 & 4. analyze + decide + generate via AI
    recent_context = context_manager.format_for_prompt(
        message.channel.id,
        current_message_id=message.id,
    )
    running_jokes = await db.get_running_jokes(message.guild.id)

    async with message.channel.typing():
        decision = await ai_service.decide_and_generate(
            message_content=_clean_bot_mention(content, bot_user.id) if is_direct_mention else content,
            author_display_name=message.author.display_name,
            recent_context=recent_context,
            humor_mode=guild_settings["humor_mode"],
            running_jokes=running_jokes,
            force_reply=is_direct_mention,
        )

    if not decision.should_reply or decision.confidence < 0.5:
        return

    # 5. safety + spam checks
    safe, safety_reason = is_reply_safe(decision.reply)
    if not safe:
        logger.info("Blocked unsafe/invalid reply (%s): %r", safety_reason, decision.reply)
        return

    final_reply = sanitize_reply(decision.reply)

    # 6. send
    try:
        await message.reply(final_reply, mention_author=False)
    except discord.HTTPException:
        logger.exception("Failed to send reply")
        return

    rate_limiter.record_reply(message.author.id, message.channel.id, message.id)

    # lightweight memory: only store a short, non-identifying-beyond-name summary
    if decision.humor_type in ("roast", "context_comedian", "fake_dramatic"):
        summary = f"{message.author.display_name} said something about '{content[:60]}' -> bot: '{final_reply[:60]}'"
        await db.add_running_joke(message.guild.id, summary)


async def _queue_pending_reply(
    message: discord.Message,
    content: str,
    is_direct_mention: bool,
    db: Database,
    rate_limiter: RateLimiter,
) -> None:
    channel_id = message.channel.id
    _pending_replies[channel_id] = PendingReply(
        message=message,
        content=content,
        is_direct_mention=is_direct_mention,
    )
    if channel_id in _pending_tasks:
        return

    _pending_tasks.add(channel_id)
    asyncio.create_task(_process_pending_reply(channel_id, db, rate_limiter))


async def _process_pending_reply(
    channel_id: int,
    db: Database,
    rate_limiter: RateLimiter,
) -> None:
    try:
        while channel_id in _pending_replies:
            pending = _pending_replies[channel_id]
            wait_seconds = rate_limiter.retry_after(
                pending.message.author.id,
                pending.message.channel.id,
                bypass_cooldowns=pending.is_direct_mention,
            )
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds + 0.5)
                continue

            pending = _pending_replies.pop(channel_id)
            if not pending.message.guild:
                continue
            if not await db.is_channel_enabled(pending.message.guild.id, pending.message.channel.id):
                continue
            if await db.is_opted_out(pending.message.guild.id, pending.message.author.id):
                continue

            await _generate_and_send_reply(
                message=pending.message,
                content=pending.content,
                is_direct_mention=pending.is_direct_mention,
                db=db,
                rate_limiter=rate_limiter,
                bypass_probability=True,
            )
    except Exception:
        logger.exception("Failed to process pending cooldown reply")
    finally:
        _pending_tasks.discard(channel_id)


def _clean_bot_mention(content: str, bot_user_id: int) -> str:
    return (
        content.replace(f"<@{bot_user_id}>", "")
        .replace(f"<@!{bot_user_id}>", "")
        .strip()
        or "say something in character"
    )


def _message_content_for_context(message: discord.Message) -> str:
    content = message.content.strip()
    if content:
        return content
    if message.attachments:
        return "[attachment]"
    if message.stickers:
        return "[sticker]"
    return ""
