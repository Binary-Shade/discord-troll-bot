"""Short-lived, in-memory rolling context per channel.

This intentionally does NOT persist message content to disk — only a small
in-memory ring buffer per channel, capped in size and age, so the bot can
"understand context" without indefinitely storing private conversation
content (see SKILL requirement: don't store message content indefinitely).
"""
import time
from collections import deque
from dataclasses import dataclass

from bot.config.settings import settings


@dataclass
class ContextEntry:
    author: str
    content: str
    timestamp: float
    message_id: int | None = None
    is_reply: bool = False
    mentions_bot: bool = False
    attachment_count: int = 0

    def format(self) -> str:
        markers = []
        if self.is_reply:
            markers.append("reply")
        if self.mentions_bot:
            markers.append("mentioned bot")
        if self.attachment_count:
            markers.append(f"{self.attachment_count} attachment(s)")
        suffix = f" ({', '.join(markers)})" if markers else ""
        return f"{self.author}{suffix}: {self.content}"


class ChannelContext:
    def __init__(
        self,
        max_entries: int = settings.context_max_messages,
        max_age_seconds: int = settings.context_max_age_seconds,
        max_chars: int = settings.context_max_chars,
    ):
        self.max_entries = max_entries
        self.max_age_seconds = max_age_seconds
        self.max_chars = max_chars
        self._buffers: dict[int, deque] = {}

    def add(
        self,
        channel_id: int,
        author: str,
        content: str,
        message_id: int | None = None,
        is_reply: bool = False,
        mentions_bot: bool = False,
        attachment_count: int = 0,
    ):
        buf = self._buffers.setdefault(channel_id, deque(maxlen=self.max_entries))
        buf.append(
            ContextEntry(
                author=author,
                content=content,
                timestamp=time.time(),
                message_id=message_id,
                is_reply=is_reply,
                mentions_bot=mentions_bot,
                attachment_count=attachment_count,
            )
        )

    def get_recent(self, channel_id: int) -> list[ContextEntry]:
        buf = self._buffers.get(channel_id)
        if not buf:
            return []
        cutoff = time.time() - self.max_age_seconds
        return [e for e in buf if e.timestamp >= cutoff]

    def format_for_prompt(
        self,
        channel_id: int,
        current_message_id: int | None = None,
    ) -> str:
        entries = self.get_recent(channel_id)
        if current_message_id is not None:
            entries = [e for e in entries if e.message_id != current_message_id]
        if not entries:
            return "(no recent context)"

        selected = []
        total_chars = 0
        for entry in reversed(entries):
            line = entry.format()
            if selected and total_chars + len(line) + 1 > self.max_chars:
                break
            selected.append(line)
            total_chars += len(line) + 1
        return "\n".join(reversed(selected))

    def clear(self, channel_id: int):
        self._buffers.pop(channel_id, None)


context_manager = ChannelContext()
