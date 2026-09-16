"""Post-generation safety net.

The system prompt already instructs the model to follow these rules, but
this filter is a deterministic second layer that runs on every generated
reply before it's sent — models can be jailbroken or slip up, so nothing
reaches Discord without passing this check.
"""
import re

# Deliberately coarse — this is a backstop, not the primary moderation
# mechanism (that's the LLM's own judgment plus server/Discord moderation).
BLOCKED_PATTERNS = [
    r"\bkill yourself\b",
    r"\bkys\b",
    r"\bslur\b",  # placeholder marker; real deployments should use a proper
                   # slur/hate-speech classifier or word list here
]

MAX_REPLY_LENGTH = 300


def is_reply_safe(reply: str) -> tuple[bool, str]:
    if not reply or not reply.strip():
        return False, "empty"

    if len(reply) > MAX_REPLY_LENGTH:
        return False, "too_long"

    lowered = reply.lower()
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, lowered):
            return False, f"blocked_pattern:{pattern}"

    # Block @everyone / @here abuse and mass mentions
    if "@everyone" in lowered or "@here" in lowered:
        return False, "mass_mention"
    if reply.count("<@") > 1:
        return False, "multi_mention"

    return True, "ok"


def sanitize_reply(reply: str) -> str:
    """Strip anything that could trigger unwanted mentions/links accidentally."""
    reply = reply.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
    return reply.strip()
