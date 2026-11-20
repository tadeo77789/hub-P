"""Paula's personality, kept in a text file the user edits to shape how she talks.

The file is read again whenever it changes, so an edit applies from the next question
without restarting the hub. The system prompt only changes when the file does, so
Ollama's prompt cache keeps working between edits.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

# User-facing, Spanish: the user edits this text in their own words.
DEFAULT_PERSONALITY = """\
Eres Paula (también te llaman Paula Port), la asistente personal que vive en el PC con \
Windows de Alejandro. Alejandro te habla por voz o desde una pequeña ventana de chat.

Tu forma de ser: cálida, tranquila y natural, como una amiga de confianza que sabe de \
tecnología. Tratas a Alejandro de tú. Eres directa y no das rodeos."""
# Longer text would crowd out the conversation in the context window.
MAX_PERSONALITY_CHARS = 4000


class PersonalityFile:
    """Returns the personality text; falls back to the default if the file is unusable."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._stamp: tuple[int, int] | None = None
        self._text = DEFAULT_PERSONALITY
        try:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(DEFAULT_PERSONALITY + "\n", encoding="utf-8")
                log.info("Created the personality file at %s", path)
        except OSError as exc:
            log.warning("Could not create the personality file %s: %s", path, exc)

    def __call__(self) -> str:
        with self._lock:
            try:
                stat = self._path.stat()
            except OSError as exc:
                if self._stamp is not None:
                    log.warning("Cannot find the personality file %s: %s", self._path, exc)
                self._stamp = None
                self._text = DEFAULT_PERSONALITY
                return self._text
            stamp = (stat.st_mtime_ns, stat.st_size)
            if stamp != self._stamp:
                self._stamp = stamp
                self._text = self._read()
            return self._text

    def _read(self) -> str:
        try:
            text = self._path.read_text(encoding="utf-8-sig").strip()
        except (OSError, ValueError) as exc:  # ValueError: not valid UTF-8
            log.warning(
                "Cannot read the personality file %s: %s; using the default", self._path, exc
            )
            return DEFAULT_PERSONALITY
        if not text:
            log.warning("The personality file %s is empty; using the default", self._path)
            return DEFAULT_PERSONALITY
        if len(text) > MAX_PERSONALITY_CHARS:
            log.warning(
                "The personality file has %d characters; only the first %d are used",
                len(text),
                MAX_PERSONALITY_CHARS,
            )
            text = text[:MAX_PERSONALITY_CHARS]
        log.info("Loaded the personality from %s", self._path)
        return text
