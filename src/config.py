"""Configuration loading and validation using Pydantic models."""

import os
import sys

import yaml
from pydantic import BaseModel


class UserConfig(BaseModel):
    """Per-user configuration for Anki sync server connection."""

    anki_sync_server: str
    anki_user: str
    anki_password: str
    anki_deck: str


class Configuration(BaseModel):
    """Main application configuration."""

    telegram_bot_token: str
    openai_api_key: str
    openai_model: str
    source_language: str
    target_language: str
    users: dict[int, UserConfig]


def load_config(path: str) -> Configuration:
    """Load configuration from YAML file."""
    if not os.path.exists(path):
        print(f"Error: Config file not found: {path}", file=sys.stderr)
        print(
            "Copy config.yaml.example to config.yaml and fill in your values.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        return Configuration(**yaml.safe_load(f))


CONFIG_PATH = os.getenv("ANKIBOT_CONFIG", "config.yaml")
CONFIG = load_config(CONFIG_PATH)
