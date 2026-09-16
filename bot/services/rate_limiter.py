"""Cooldown + spam-prevention logic.

Tracks last-reply timestamps globally, per-channel, and per-user, plus a
rolling window of replies-per-minute so the bot can't flood a server even
if the AI decides many messages deserve a reply.
"""
import time
from collections import deque


class RateLimiter:
    def __init__(
        self,
        global_cooldown: int = 8,
        per_user_cooldown: int = 45,
        per_channel_cooldown: int = 20,
        max_replies_per_minute: int = 6,
    ):
        self.global_cooldown = global_cooldown
        self.per_user_cooldown = per_user_cooldown
        self.per_channel_cooldown = per_channel_cooldown
        self.max_replies_per_minute = max_replies_per_minute

        self._last_global_reply: float = 0.0
        self._last_user_reply: dict[int, float] = {}
        self._last_channel_reply: dict[int, float] = {}
        self._recent_reply_times: deque = deque()
        self._recently_replied_message_ids: set[int] = set()

    def can_reply(
        self,
        user_id: int,
        channel_id: int,
        bypass_cooldowns: bool = False,
    ) -> tuple[bool, str]:
        now = time.time()

        if not bypass_cooldowns:
            if now - self._last_global_reply < self.global_cooldown:
                return False, "global_cooldown"

            last_user = self._last_user_reply.get(user_id, 0)
            if now - last_user < self.per_user_cooldown:
                return False, "per_user_cooldown"

            last_channel = self._last_channel_reply.get(channel_id, 0)
            if now - last_channel < self.per_channel_cooldown:
                return False, "per_channel_cooldown"

        # prune replies older than 60s from the rolling window
        while self._recent_reply_times and now - self._recent_reply_times[0] > 60:
            self._recent_reply_times.popleft()
        if len(self._recent_reply_times) >= self.max_replies_per_minute:
            return False, "max_replies_per_minute"

        return True, "ok"

    def retry_after(
        self,
        user_id: int,
        channel_id: int,
        bypass_cooldowns: bool = False,
    ) -> float:
        now = time.time()
        waits = []

        if not bypass_cooldowns:
            waits.append(self.global_cooldown - (now - self._last_global_reply))
            waits.append(self.per_user_cooldown - (now - self._last_user_reply.get(user_id, 0)))
            waits.append(
                self.per_channel_cooldown - (now - self._last_channel_reply.get(channel_id, 0))
            )

        while self._recent_reply_times and now - self._recent_reply_times[0] > 60:
            self._recent_reply_times.popleft()
        if len(self._recent_reply_times) >= self.max_replies_per_minute:
            waits.append(60 - (now - self._recent_reply_times[0]))

        return max([0.0, *waits])

    def record_reply(self, user_id: int, channel_id: int, message_id: int):
        now = time.time()
        self._last_global_reply = now
        self._last_user_reply[user_id] = now
        self._last_channel_reply[channel_id] = now
        self._recent_reply_times.append(now)
        self._recently_replied_message_ids.add(message_id)
        # keep this set from growing unbounded
        if len(self._recently_replied_message_ids) > 500:
            self._recently_replied_message_ids = set(
                list(self._recently_replied_message_ids)[-250:]
            )

    def already_replied(self, message_id: int) -> bool:
        return message_id in self._recently_replied_message_ids
