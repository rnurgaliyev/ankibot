# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AnkiBot is a Telegram bot for language learning that translates words/phrases using OpenAI and creates bidirectional Anki flashcards. It syncs directly to a self-hosted Anki sync server.

## Commands

```bash
# Run with Docker (recommended)
docker compose up -d          # Start bot + sync server
docker compose logs -f bot    # View bot logs
docker compose down           # Stop everything

# Run manually
pip install -r requirements.txt
python src/main.py

# Code quality
mypy src/
pylint src/
black src/
isort src/
```

## Architecture

```
User (Telegram) → bot.py → translation.py → openai.py → OpenAI API
                    ↓
                anki_client.py → Anki sync server
                    ↓
                config.py (loads config.yaml)
```

**Key components:**

- `bot.py` — Telegram bot with message and callback handlers. Sends one message per translation context and uses TTLCache (24hr) to store contexts by UUID for Anki callbacks
- `translation.py` — Prompts OpenAI and parses structured responses with Pydantic
- `anki_client.py` — `AnkiSession` context manager for sync server auth, collection download/upload, card creation
- `openai.py` — OpenAI chat completions wrapper with Pydantic response models
- `config.py` — Pydantic config models, loads from `config.yaml` (or `ANKIBOT_CONFIG` env var)

**Callback data format:** `"command:argument"` (colon-delimited) for Telegram inline button callbacks.

**Exception hierarchy:** `AnkiSyncError` (base) → `AnkiLoginError`, `AnkiDownloadError`, `AnkiUploadError`

## Code Quality

- Python 3.12+
- `mypy --strict` with exceptions for untyped libs (telebot, anki, cachetools)
- pylint with minimal disabled rules (broad-exception-caught, line-too-long)
- black for formatting, isort for import ordering
