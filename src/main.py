"""Entry point for the AnkiBot Telegram bot."""

import logging

from bot import start_bot


def main() -> None:
    """Initialize logging and start the Telegram bot."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    start_bot()


if __name__ == "__main__":
    main()
