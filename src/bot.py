"""Telegram bot for translating words and adding them to Anki."""

import logging
import uuid

import telebot
from cachetools import TTLCache
from telebot.types import CallbackQuery, Message

from anki_client import AnkiDownloadError, AnkiLoginError, AnkiSession, AnkiUploadError
from config import CONFIG
from translation import GermanVerbForms, Translation, TranslationContext, translate_ai

logger = logging.getLogger(__name__)

# Constants
CACHE_MAX_SIZE = 128
CACHE_TTL_SECONDS = 86400  # 24 hours
MAX_REQUEST_SPACES = 4
MAX_REQUEST_BYTES = 58  # 64 (Telegram callback limit) - 6 ("retry:")

CALLBACK_RETRY = "retry"
CALLBACK_ADD_TO_ANKI = "add_anki"

LANGUAGE_FLAGS: dict[str, str] = {
    "GERMAN": "🇩🇪",
    "ENGLISH": "🇬🇧",
    "UKRAINIAN": "🇺🇦",
    "FRENCH": "🇫🇷",
    "SPANISH": "🇪🇸",
}

bot = telebot.TeleBot(CONFIG.telegram_bot_token)
cache: TTLCache[str, Translation] = TTLCache(
    maxsize=CACHE_MAX_SIZE, ttl=CACHE_TTL_SECONDS
)


@bot.callback_query_handler(func=lambda call: True)
def callback_query_handler(call: CallbackQuery) -> None:
    """Handle inline button clicks (retry translation or add to Anki)."""
    if call.message is None:
        return

    chat_id = call.message.chat.id

    # Authentication
    if chat_id not in CONFIG.users:
        logger.warning("User %s is not authorized", chat_id)
        return

    bot.answer_callback_query(call.id)

    # Parse callback data (format: "command:argument")
    pos = call.data.find(":") if call.data else -1
    if pos <= 0 or call.data is None or pos == len(call.data) - 1:
        logger.warning("Malformed callback data: %s", call.data)
        return

    command = call.data[:pos]
    arg = call.data[pos + 1 :]

    if command == CALLBACK_RETRY:
        translate(chat_id, arg)
    elif command == CALLBACK_ADD_TO_ANKI:
        translation = cache.get(arg)
        if translation is not None:
            add_to_anki(chat_id, translation)
        else:
            bot.send_message(
                chat_id, "Translation is stale, try another one or retry this one 🙈"
            )
    else:
        logger.warning("Unknown command: %s", command)


@bot.message_handler(func=lambda message: True)
def message_handler(message: Message) -> None:
    """Handle incoming messages (commands and translation requests)."""
    # Authentication
    if message.from_user is None or message.from_user.id not in CONFIG.users:
        logger.warning("User %s is not authorized", message.from_user)
        return

    if message.text is None:
        return

    # Slash commands
    if message.text.startswith("/"):
        if message.text == "/start":
            bot.send_message(message.chat.id, "Yeah sure let's go 🫠")
        else:
            bot.send_message(message.chat.id, "Sorry what? 🫠")
        return

    # Translation request
    translate(message.chat.id, message.text)


def start_bot() -> None:
    """Start the Telegram bot polling loop."""
    logger.info("Starting telegram bot polling...")
    bot.polling(
        allowed_updates=["message", "callback_query"],
        timeout=30,
        long_polling_timeout=30,
        none_stop=True,
    )


def translate(chat_id: int, request: str) -> None:
    """Translate a word/phrase and send the result with action buttons."""
    # Validate request
    if (
        request.count(" ") > MAX_REQUEST_SPACES
        or len(request.encode("utf-8")) > MAX_REQUEST_BYTES
        or not all(c.isalnum() or c in " '-" for c in request)
    ):
        bot.send_message(
            chat_id, "Are you kidding me? 🫠 Go to Google Translate or smth."
        )
        return

    # Translate
    try:
        translation = translate_ai(request)
    except Exception as e:
        logger.error("Translation failed for '%s': %s", request, e)
        bot.send_message(
            chat_id,
            f"Oh no! Error happened! 😮\n```\n{e}\n```",
            parse_mode="MARKDOWN",
        )
        return

    # Cache translation for later retrieval
    translation_id = str(uuid.uuid4())
    cache[translation_id] = translation

    # Build reply markup
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton(
            f'Add translations to Anki deck "{CONFIG.users[chat_id].anki_deck}"',
            callback_data=f"{CALLBACK_ADD_TO_ANKI}:{translation_id}",
        )
    )
    markup.add(
        telebot.types.InlineKeyboardButton(
            "Retry translation",
            callback_data=f"{CALLBACK_RETRY}:{request}",
        )
    )

    bot.send_message(
        chat_id,
        translation_to_md(translation),
        parse_mode="MARKDOWN",
        reply_markup=markup,
    )


def add_to_anki(chat_id: int, translation: Translation) -> None:
    """Create Anki flashcards from a translation and sync to server."""
    user_config = CONFIG.users[chat_id]
    cards_added = 0

    try:
        with AnkiSession(
            user_config.anki_sync_server,
            user_config.anki_user,
            user_config.anki_password,
        ) as anki:
            for context in translation.response.contexts:
                # Forward card (source -> target)
                front, back = context_to_card(context)
                anki.add_card(user_config.anki_deck, front, back)

                # Reverse card (target -> source)
                front, back = context_to_reverse_card(context)
                anki.add_card(user_config.anki_deck, front, back)

                cards_added += 2

            anki.sync()

        logger.info(
            "Added %d Anki cards for '%s' (user %d)",
            cards_added,
            translation.request,
            chat_id,
        )
        bot.send_message(
            chat_id,
            f"Added {cards_added} Anki cards for *{translation.request}* 😎\n\n"
            f"✅ Anki collection fetched\n"
            f"✅ Cards added\n"
            f"✅ Collection synced back to server\n\n"
            f"Don't forget to sync!",
            parse_mode="MARKDOWN",
        )

    except AnkiLoginError as e:
        logger.error("Anki login failed for user %d: %s", chat_id, e)
        bot.send_message(
            chat_id,
            f"Oh no! Could not authenticate with Anki sync server! 😮\n"
            f"Check your username/password in config.\n```\n{e}\n```",
            parse_mode="MARKDOWN",
        )
    except AnkiDownloadError as e:
        logger.error("Anki download failed for user %d: %s", chat_id, e)
        bot.send_message(
            chat_id,
            f"Oh no! Could not download Anki collection! 😮\n"
            f"Check if your sync server is running.\n```\n{e}\n```",
            parse_mode="MARKDOWN",
        )
    except AnkiUploadError as e:
        logger.error("Anki sync failed for user %d: %s", chat_id, e)
        bot.send_message(
            chat_id,
            f"Oh no! Could not sync Anki collection back to the server! 😮\n"
            f"Cards may have been added locally but not synced.\n```\n{e}\n```",
            parse_mode="MARKDOWN",
        )
    except Exception as e:
        logger.error("Unexpected error for user %d: %s", chat_id, e)
        bot.send_message(
            chat_id,
            f"Oh no! Unexpected error! 😮\n```\n{e}\n```",
            parse_mode="MARKDOWN",
        )


# --- Formatting helpers ---


def _format_article(article: str | None) -> str:
    """Format article prefix (e.g., 'der ', 'die ', 'das ')."""
    return f"{article} " if article else ""


def _format_verb_forms(verb_forms: GermanVerbForms | None) -> str:
    """Format German verb forms (e.g., ' (machte, hat gemacht)')."""
    if verb_forms is None:
        return ""
    return f" ({verb_forms.praeteritum}, {verb_forms.perfekt})"


def _format_plural(plural: str | None) -> str:
    """Format plural (e.g., ' (pl. Hunde)')."""
    return f" (pl. {plural})" if plural else ""


def _format_label(word_type: str | None, label: str | None) -> str:
    """Format type and label (e.g., ' [noun, animal]')."""
    if label is None:
        return ""
    prefix = f"{word_type}, " if word_type else ""
    return f" \\[{prefix}{label}]"


def translation_to_md(translation: Translation) -> str:
    """Convert translation to Markdown for Telegram."""
    flag = LANGUAGE_FLAGS.get(CONFIG.source_language.upper(), "")
    if flag:
        flag += " "

    lines = [f"{flag}Translation for *{translation.request}*\n"]

    for ctx in translation.response.contexts:
        # Word with article, verb forms, plural, and label
        word_line = (
            f"*{_format_article(ctx.article)}{ctx.text}*"
            f"{_format_verb_forms(ctx.verb_forms)}"
            f"{_format_plural(ctx.plural)}"
            f"{_format_label(ctx.type, ctx.label)}"
        )
        lines.append(word_line)
        lines.append(", ".join(ctx.translations))
        lines.append(f"💬 _{ctx.example}_\n")

    return "\n".join(lines).rstrip("\n")


def context_to_card(context: TranslationContext) -> tuple[str, str]:
    """Create forward Anki card (source language -> target language)."""
    front = (
        f"{_format_article(context.article)}{context.text}"
        f"{_format_verb_forms(context.verb_forms)}"
        f"<br><br><i>[{context.type}, {context.label}]</i>"
    )
    back = f"{', '.join(context.translations)}<br><br><i>{context.example}</i>"
    return front, back


def context_to_reverse_card(context: TranslationContext) -> tuple[str, str]:
    """Create reverse Anki card (target language -> source language)."""
    front = f"{', '.join(context.translations)}<br><br><i>[{context.type}, {context.label}]</i>"
    back = (
        f"{_format_article(context.article)}{context.text}"
        f"{_format_verb_forms(context.verb_forms)}"
        f"<br><br><i>{context.example}</i>"
    )
    return front, back
