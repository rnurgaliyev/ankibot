"""Anki sync client for downloading collections, adding cards, and syncing back."""

import logging
import os
import tempfile
import uuid
from types import TracebackType
from typing import Literal, cast

from anki.collection import Collection
from anki.decks import DeckId
from anki.models import NotetypeId
from anki.sync import SyncAuth

logger = logging.getLogger(__name__)


class AnkiSyncError(Exception):
    """Base exception for Anki sync operations."""


class AnkiLoginError(AnkiSyncError):
    """Failed to authenticate with Anki sync server."""


class AnkiDownloadError(AnkiSyncError):
    """Failed to download collection from server."""


class AnkiUploadError(AnkiSyncError):
    """Failed to upload collection to server."""


class AnkiSession:
    """
    Context manager for Anki collection operations.

    Downloads a fresh collection from the sync server, allows adding cards,
    and syncs changes back. Handles cleanup automatically.

    Usage:
        with AnkiSession(server, user, password) as anki:
            anki.add_card("German", "Hund", "dog")
            anki.sync()
    """

    def __init__(self, server: str, username: str, password: str):
        """Initialize session parameters."""
        self.server = server
        self.username = username
        self.password = password
        self.collection: Collection | None = None
        self.auth: SyncAuth | None = None
        self.temp_path: str | None = None

    def __enter__(self) -> "AnkiSession":
        """Set up Anki collection: create temp file, login, and download."""
        temp_dir = tempfile.gettempdir()
        random_id = uuid.uuid4().hex[:8]
        self.temp_path = os.path.join(temp_dir, f"ankibot_{random_id}.anki2")

        logger.debug("Creating temp collection: %s", self.temp_path)

        if os.path.exists(self.temp_path):
            logger.debug("Removing existing file: %s", self.temp_path)
            os.remove(self.temp_path)

        try:
            self.collection = Collection(self.temp_path)
            logger.debug("Collection created")

            try:
                self.auth = self.collection.sync_login(
                    username=self.username, password=self.password, endpoint=self.server
                )
                logger.info("Authenticated with Anki sync server")
            except Exception as e:
                logger.error("Login failed: %s", e)
                raise AnkiLoginError(f"Could not authenticate: {e}") from e

            try:
                result = self.collection.sync_collection(
                    auth=self.auth, sync_media=False
                )
                logger.debug("Sync result: %s", result)

                if result.required == 3:  # FULL_DOWNLOAD
                    logger.debug("Performing full download")
                    self.collection.full_upload_or_download(
                        auth=self.auth, server_usn=None, upload=False
                    )

                logger.info("Collection downloaded from server")

            except Exception as e:
                logger.error("Download failed: %s", e)
                raise AnkiDownloadError(f"Could not fetch collection: {e}") from e

            return self

        except Exception:
            self._cleanup()
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        """Clean up resources (close collection, delete temp file)."""
        self._cleanup()
        return False

    def _cleanup(self) -> None:
        """Internal cleanup method."""
        if self.collection is not None:
            try:
                self.collection.close()
                logger.debug("Collection closed")
            except Exception as e:
                logger.error("Error closing collection: %s", e)

        if self.temp_path and os.path.exists(self.temp_path):
            try:
                os.remove(self.temp_path)
                logger.debug("Deleted temp file: %s", self.temp_path)
            except Exception as e:
                logger.error("Error deleting temp file: %s", e)

    def add_card(self, deck: str, front: str, back: str) -> None:
        """
        Add a card to the specified deck.

        Args:
            deck: Deck name (created if doesn't exist)
            front: Front side content (HTML)
            back: Back side content (HTML)
        """
        if self.collection is None:
            raise RuntimeError("Session not initialized. Use with statement.")

        deck_id_result: DeckId | None = self.collection.decks.id_for_name(deck)
        if deck_id_result is None:
            deck_id_result = cast(
                DeckId, self.collection.decks.add_normal_deck_with_name(deck).id
            )
        deck_id = deck_id_result

        notetype = self.collection.models.by_name("Basic")
        if notetype is None:
            all_notetypes = list(self.collection.models.all_names_and_ids())
            if not all_notetypes:
                raise RuntimeError("No note types available in collection")
            notetype_id = cast(NotetypeId, all_notetypes[0].id)
            notetype = self.collection.models.get(notetype_id)

        if notetype is None:
            raise RuntimeError("Could not get note type from collection")

        note = self.collection.new_note(notetype)
        note.fields[0] = front
        note.fields[1] = back
        self.collection.add_note(note, deck_id)

        logger.debug("Added card to deck '%s'", deck)

    def sync(self) -> None:
        """Sync collection back to server."""
        if self.collection is None or self.auth is None:
            raise RuntimeError("Session not initialized. Use with statement.")

        try:
            self.collection.sync_collection(auth=self.auth, sync_media=False)
            logger.info("Collection synced to server")
        except Exception as e:
            logger.error("Sync failed: %s", e)
            raise AnkiUploadError(f"Could not sync to server: {e}") from e
