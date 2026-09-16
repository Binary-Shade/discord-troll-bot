"""Wraps the HCNSEC chat-completions API for reply decisions."""
import asyncio
import json
import logging
import random
from dataclasses import dataclass

import aiohttp

from bot.config.personality import build_system_prompt
from bot.config.settings import settings

logger = logging.getLogger("genz_troll_bot.ai")

RETRIABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504, 522, 524}
STALE_REPLY_PATTERNS = (
    "bro really",
    "bro literally",
    "bro is really",
    "ain't no way",
    "aint no way",
    "blud",
    "the audacity",
    "nah because",
)


@dataclass
class AIDecision:
    should_reply: bool
    reply: str
    humor_type: str
    confidence: float


class AIService:
    def __init__(self):
        self.api_key = settings.hcnsec_api_key
        self.api_url = settings.hcnsec_api_url
        self.model = settings.hcnsec_model
        self._request_lock = asyncio.Lock()

    async def decide_and_generate(
        self,
        message_content: str,
        author_display_name: str,
        recent_context: str,
        humor_mode: str,
        running_jokes: list[str],
        force_reply: bool = False,
    ) -> AIDecision:
        system_prompt = build_system_prompt(humor_mode)

        jokes_block = "\n".join(f"- {j}" for j in running_jokes) if running_jokes else "(none yet)"
        reply_instruction = (
            "The bot was directly mentioned. Reply unless the message is unsafe, harmful, "
            "or genuinely non-joking/distressing."
            if force_reply
            else "Decide whether to reply and, if so, generate the reply."
        )

        user_prompt = f"""Recent channel context (oldest to newest):
{recent_context}

Server running jokes / recurring bits:
{jokes_block}

New message from {author_display_name}:
"{message_content}"

{reply_instruction} Respond with ONLY the JSON object."""

        payload = await self._request([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        if payload is None:
            return AIDecision(should_reply=False, reply="", humor_type="none", confidence=0.0)

        text = self._extract_message_text(payload)
        decision = self._parse(text)
        if decision.should_reply and self._needs_style_rewrite(decision.reply):
            rewritten = await self._rewrite_reply_style(decision.reply)
            if rewritten:
                decision.reply = rewritten

        if decision.confidence > 0 or decision.should_reply:
            return decision

        repaired = await self._repair_response(text)
        if repaired is not None:
            return self._parse(repaired)

        return decision

    async def _request(self, messages: list[dict[str, str]]) -> dict | None:
        async with self._request_lock:
            return await self._request_with_retries(messages)

    async def _request_with_retries(self, messages: list[dict[str, str]]) -> dict | None:
        attempts = max(1, settings.hcnsec_retry_attempts)
        for attempt in range(1, attempts + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        self.api_url,
                        headers=self._headers(),
                        json={
                            "model": self.model,
                            "messages": messages,
                            "max_tokens": settings.hcnsec_max_tokens,
                            "temperature": 0.7,
                        },
                        timeout=aiohttp.ClientTimeout(total=settings.hcnsec_timeout_seconds),
                    ) as response:
                        if response.status >= 400:
                            error_body = (await response.text())[:500]
                            if (
                                response.status in RETRIABLE_STATUS_CODES
                                and attempt < attempts
                            ):
                                logger.warning(
                                    "HCNSEC API returned retryable HTTP %s on attempt %s/%s: %s",
                                    response.status,
                                    attempt,
                                    attempts,
                                    error_body,
                                )
                                await asyncio.sleep(self._retry_delay(attempt))
                                continue

                            logger.error(
                                "HCNSEC API returned HTTP %s after %s attempt(s): %s",
                                response.status,
                                attempt,
                                error_body,
                            )
                            return None
                        return await response.json()
            except TimeoutError:
                if attempt < attempts:
                    logger.warning(
                        "HCNSEC API timed out after %s seconds on attempt %s/%s; retrying.",
                        settings.hcnsec_timeout_seconds,
                        attempt,
                        attempts,
                    )
                    await asyncio.sleep(self._retry_delay(attempt))
                    continue

                logger.error(
                    "HCNSEC API timed out after %s seconds and %s attempt(s). Try lowering "
                    "HCNSEC_MAX_TOKENS or raising HCNSEC_TIMEOUT_SECONDS.",
                    settings.hcnsec_timeout_seconds,
                    attempts,
                )
                return None
            except aiohttp.ClientError:
                if attempt < attempts:
                    logger.warning(
                        "HCNSEC API client error on attempt %s/%s; retrying.",
                        attempt,
                        attempts,
                        exc_info=True,
                    )
                    await asyncio.sleep(self._retry_delay(attempt))
                    continue

                logger.exception("HCNSEC API client error after %s attempt(s)", attempts)
                return None
            except Exception:
                logger.exception("HCNSEC API call failed")
                return None

        return None

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        base = settings.hcnsec_retry_base_delay_seconds
        cap = settings.hcnsec_retry_max_delay_seconds
        delay = min(cap, base * (2 ** (attempt - 1)))
        return delay + random.uniform(0, min(1.0, delay * 0.25))

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "genz-troll-bot/1.0",
        }
        return headers

    async def _repair_response(self, bad_response: str) -> str | None:
        if not bad_response.strip():
            return None

        payload = await self._request([
            {
                "role": "system",
                "content": "Convert the input into the required JSON object. Output JSON only.",
            },
            {
                "role": "user",
                "content": (
                    "Required keys: should_reply boolean, reply string, "
                    "humor_type string, confidence number.\n\n"
                    f"Input:\n{bad_response[:2000]}"
                ),
            },
        ])
        if payload is None:
            return None

        return self._extract_message_text(payload)

    async def _rewrite_reply_style(self, reply: str) -> str | None:
        payload = await self._request([
            {
                "role": "system",
                "content": (
                    "Rewrite the Discord bot reply to sound like a natural human friend. "
                    "Keep the same meaning, keep it short, lowercase, and output only "
                    "the rewritten reply text. Do not use 'bro really', 'ain't no way', "
                    "'blud', 'the audacity', or repetitive meme-template wording."
                ),
            },
            {"role": "user", "content": reply[:500]},
        ])
        if payload is None:
            return None

        rewritten = self._extract_message_text(payload).strip().strip('"')
        return rewritten if rewritten and not self._needs_style_rewrite(rewritten) else None

    @staticmethod
    def _needs_style_rewrite(reply: str) -> bool:
        lowered = reply.lower().strip()
        if lowered.count("bro") > 1:
            return True
        return any(lowered.startswith(pattern) for pattern in STALE_REPLY_PATTERNS)

    @staticmethod
    def _extract_message_text(payload: dict) -> str:
        choices = payload.get("choices") or []
        if not choices:
            logger.warning("HCNSEC response did not include choices: %r", payload)
            return ""

        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if not content:
            content = message.get("reasoning_content", "") or message.get("reasoning", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            ).strip()
        return ""

    @staticmethod
    def _parse(text: str) -> AIDecision:
        # Strip accidental markdown fences just in case.
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()
        if not cleaned:
            logger.warning("AI response content was empty")
            return AIDecision(should_reply=False, reply="", humor_type="none", confidence=0.0)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            data = AIService._extract_json_object(cleaned)

        try:
            return AIDecision(
                should_reply=bool(data.get("should_reply", False)),
                reply=str(data.get("reply", "")),
                humor_type=str(data.get("humor_type", "unknown")),
                confidence=float(data.get("confidence", 0.0)),
            )
        except (AttributeError, TypeError, ValueError):
            logger.warning("Failed to parse AI response as JSON: %r", text[:200])
            return AIDecision(should_reply=False, reply="", humor_type="none", confidence=0.0)

    @staticmethod
    def _extract_json_object(text: str) -> dict | None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None


ai_service = AIService()
