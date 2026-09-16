# genz-troll-bot

A Discord bot with a chaotic, witty Gen Z persona. It reads messages in
server channels by default, decides via HCNSEC whether something deserves a funny
reaction, and replies in character — with cooldowns, opt-outs, and a safety
filter so it stays entertaining without being genuinely abusive.

## Architecture

```
bot/
  main.py                 # entrypoint, bot lifecycle
  config/
    settings.py            # env var loading
    personality.py         # system prompt + humor modes
  services/
    database.py            # SQLite: channel settings, opt-outs, running jokes
    context_manager.py      # in-memory rolling per-channel conversation context
    rate_limiter.py         # global / per-user / per-channel cooldowns, replies/min cap
    safety_filter.py        # deterministic post-generation safety backstop
    ai_service.py           # HCNSEC API call -> structured JSON decision
    reply_pipeline.py       # orchestrates the full decision pipeline
  handlers/
    events.py               # on_message, on_ready, error handling
    commands.py              # /troll slash command group
```

Pipeline: `on_message` → channel not disabled? → author opted out? → cooldowns →
probability gate → HCNSEC decides + generates → safety filter → send →
record cooldown + optional running-joke memory.

Stack: **discord.py** (Python) for the Discord side, **HCNSEC** for
generation, and local **SQLite** for lightweight persistence.

## 1. Discord Developer Portal setup

1. Go to https://discord.com/developers/applications → **New Application**.
2. Under **Bot**, click **Add Bot**. Copy the token → this is `DISCORD_BOT_TOKEN`.
3. Still under **Bot**, enable **Message Content Intent** (required — the bot
   reads message text). Leave Presence/Server Members intents off unless you
   need them.
4. Under **OAuth2 → URL Generator**, select scopes `bot` and
   `applications.commands`, and bot permissions: `Read Messages/View
   Channels`, `Send Messages`, `Read Message History`. Use the generated URL
   to invite the bot to your server.
5. Copy the **Application ID** from the General Information page →
   `DISCORD_APPLICATION_ID`.

## 2. Project setup

```bash
git clone <this project>
cd genz-troll-bot
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```
DISCORD_BOT_TOKEN=...
DISCORD_APPLICATION_ID=...
HCNSEC_API_KEY=...
HCNSEC_MODEL=auto
HCNSEC_API_URL=https://api.hcnsec.cn/v1/chat/completions
HCNSEC_MAX_TOKENS=600
HCNSEC_TIMEOUT_SECONDS=60
HCNSEC_RETRY_ATTEMPTS=3
HCNSEC_RETRY_BASE_DELAY_SECONDS=2
HCNSEC_RETRY_MAX_DELAY_SECONDS=15
CONTEXT_MAX_MESSAGES=50
CONTEXT_MAX_AGE_SECONDS=1800
CONTEXT_MAX_CHARS=5000
BOT_ADMIN_USER_IDS=957979111819718687
```

Adjust `DEFAULT_RESPONSE_PROBABILITY`, cooldowns, `MAX_REPLIES_PER_MINUTE`,
and the `CONTEXT_*` settings to taste. `BOT_ADMIN_USER_IDS` is a
comma-separated list of Discord user IDs that can run admin bot commands even
without the Discord **Manage Server** permission.

AI calls are queued one at a time and transient provider failures like HTTP
429, 5xx, 522, and 524 are retried with exponential backoff. Tune this with
`HCNSEC_RETRY_ATTEMPTS`, `HCNSEC_RETRY_BASE_DELAY_SECONDS`, and
`HCNSEC_RETRY_MAX_DELAY_SECONDS`.

## 3. Run it

```bash
python -m bot.main
```

On first run it creates the SQLite DB at `bot/data/troll_bot.db` and syncs
slash commands (can take up to an hour to appear globally the very first
time; per-guild sync is near-instant).

## 4. Commands

All under `/troll`:

- `/troll disable` — turn it off in the current channel (bot admin/Manage Server only)
- `/troll enable` — re-enable it in a channel you previously disabled (bot admin only)
- `/troll mode <mode>` — set humor mode: roaster, chaotic_friend, deadpan,
  genz_commentator, context_comedian, fake_dramatic (bot admin only)
- `/troll status` — show current config for the server/channel
- `/troll cooldown [probability] [seconds]` — tune reply probability and base
  cooldown (bot admin only)
- `/troll personality <opt out|opt in>` — any member can opt themselves out
  of being roasted
- `/troll clearmemory` — wipe stored running-joke memory (bot admin only)

## 5. Safety design

- System prompt enforces no hate speech, threats, sexual content, targeted
  bullying, or doxxing, and instructs the model to ignore any in-message
  attempt to override these rules.
- A deterministic `safety_filter.py` backstop runs on every generated reply
  before sending (blocks empty/oversized replies, mass mentions, obvious
  blocked phrases) regardless of what the model produced.
- Opted-out members are excluded from being targeted; the bot still sees
  their messages for context but the prompt is told not to roast them.
- Message content is **not** stored long-term — conversation context lives
  in an in-memory ring buffer per channel (capped by `CONTEXT_MAX_MESSAGES`,
`CONTEXT_MAX_AGE_SECONDS`, and `CONTEXT_MAX_CHARS`) that's lost on restart.
  Only short joke *summaries* (first ~60 chars) are
  persisted, capped at 25 per server, and `/troll clearmemory` wipes them.

Note: the blocked-phrase list in `safety_filter.py` is intentionally minimal
— it's a backstop, not the primary moderation layer. For real deployment,
swap in a proper hate-speech/toxicity classifier or word list, and rely on
Discord's own AutoMod alongside this.

## 6. Testing

Quick manual test loop:

1. Invite the bot to a private test server.
2. Send a few casual/joke-shaped messages and confirm it sometimes (not
   always) replies in character.
3. Send something distressing/non-joking and confirm it stays silent
   (`should_reply: false` from the model).
4. Have a second account run `/troll personality opt out`, then send
   roastable messages from that account — confirm the bot doesn't target
   them.
5. Spam several messages quickly — confirm cooldowns/max-replies-per-minute
   kick in and it doesn't flood the channel.

For automated checks, `ai_service._parse`, `ai_service._extract_message_text`,
and `safety_filter.is_reply_safe` are pure functions you can unit test directly
without hitting Discord or the HCNSEC API.

## 7. Deployment

Any host that can run a long-lived Python process works (a VPS, Railway,
Fly.io, a small container, etc.):

```bash
pip install -r requirements.txt
python -m bot.main
```

For production: run it under a process manager (systemd, `pm2`, or a
container restart policy) so it reconnects after crashes, and mount a
persistent volume for `bot/data/` so settings/opt-outs survive restarts.
Never commit `.env` or hardcode the tokens — keep them as environment
variables / secrets in whatever platform you deploy to.
# discord-troll-bot
