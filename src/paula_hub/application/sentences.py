"""Cut streamed model text into sentences, so speech can start before the reply is done."""

from __future__ import annotations

import re

# End of a sentence: punctuation (optionally a closing quote) followed by whitespace.
BOUNDARY = re.compile(r"[.!?…]+[\"»”)]?\s")


class SentenceSplitter:
    def __init__(self, min_chars: int = 8) -> None:
        # Very short sentences ("Sí.") are merged with the next one: one TTS call each costs time.
        self._min_chars = min_chars
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        sentences = []
        pos = 0
        while (match := BOUNDARY.search(self._buffer, pos)) is not None:
            candidate = self._buffer[: match.end()].strip()
            if len(candidate) >= self._min_chars:
                sentences.append(candidate)
                self._buffer = self._buffer[match.end() :]
                pos = 0
            else:
                pos = match.end()
        return sentences

    def flush(self) -> list[str]:
        rest, self._buffer = self._buffer.strip(), ""
        return [rest] if rest else []
