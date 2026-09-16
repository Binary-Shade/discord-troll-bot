"""Central settings loaded from environment variables."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _int_set(name: str) -> frozenset[int]:
    raw = os.getenv(name, "")
    ids = []
    for value in raw.replace(" ", "").split(","):
        if value:
            ids.append(int(value))
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    discord_token: str = os.getenv("DISCORD_BOT_TOKEN", "")
    application_id: str = os.getenv("DISCORD_APPLICATION_ID", "")

    hcnsec_api_key: str = os.getenv("HCNSEC_API_KEY", "")
    hcnsec_model: str = os.getenv("HCNSEC_MODEL", "auto")
    hcnsec_api_url: str = os.getenv(
        "HCNSEC_API_URL",
        "https://api.hcnsec.cn/v1/chat/completions",
    )
    hcnsec_max_tokens: int = _int("HCNSEC_MAX_TOKENS", 600)
    hcnsec_timeout_seconds: int = _int("HCNSEC_TIMEOUT_SECONDS", 60)
    hcnsec_retry_attempts: int = _int("HCNSEC_RETRY_ATTEMPTS", 3)
    hcnsec_retry_base_delay_seconds: float = _float("HCNSEC_RETRY_BASE_DELAY_SECONDS", 2.0)
    hcnsec_retry_max_delay_seconds: float = _float("HCNSEC_RETRY_MAX_DELAY_SECONDS", 15.0)

    context_max_messages: int = _int("CONTEXT_MAX_MESSAGES", 50)
    context_max_age_seconds: int = _int("CONTEXT_MAX_AGE_SECONDS", 1800)
    context_max_chars: int = _int("CONTEXT_MAX_CHARS", 5000)

    default_response_probability: float = _float("DEFAULT_RESPONSE_PROBABILITY", 0.35)
    global_cooldown_seconds: int = _int("GLOBAL_COOLDOWN_SECONDS", 8)
    per_user_cooldown_seconds: int = _int("PER_USER_COOLDOWN_SECONDS", 45)
    per_channel_cooldown_seconds: int = _int("PER_CHANNEL_COOLDOWN_SECONDS", 20)
    max_replies_per_minute: int = _int("MAX_REPLIES_PER_MINUTE", 6)

    database_path: str = os.getenv("DATABASE_PATH", "./bot/data/troll_bot.db")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    bot_admin_user_ids: frozenset[int] = _int_set("BOT_ADMIN_USER_IDS")


settings = Settings()


def _is_missing_secret(value: str, placeholder: str) -> bool:
    stripped = value.strip()
    return not stripped or stripped == placeholder


def validate_settings() -> None:
    missing = []
    if _is_missing_secret(settings.discord_token, "your_discord_bot_token_here"):
        missing.append("DISCORD_BOT_TOKEN")
    if _is_missing_secret(settings.hcnsec_api_key, "your_hcnsec_api_key_here"):
        missing.append("HCNSEC_API_KEY")
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Copy .env.example to .env and fill these in."
        )
