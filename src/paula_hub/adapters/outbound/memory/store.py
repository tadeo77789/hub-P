"""MemoryPort on SQLite, with embeddings from a local Ollama model.

Each fact is stored with its embedding (a vector that captures its meaning). Recall
embeds the question and returns the facts whose vectors point the same way (cosine
similarity), so "¿qué música me gusta?" finds "A Ola le gusta el rock de los 80".
A few hundred facts are compared in plain Python in milliseconds.
"""

from __future__ import annotations

import http.client
import json
import logging
import math
import sqlite3
import threading
import unicodedata
import urllib.request
import uuid
from array import array
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from paula_hub.domain.memory import MemoryFact
from paula_hub.ports.outbound.memory import MemoryUnavailable

log = logging.getLogger(__name__)

DEFAULT_EMBED_MODEL = "qwen3-embedding:0.6b"
# qwen3-embedding separates questions from facts better with an instruction on the
# query side only (facts are embedded as they are).
QUERY_PREFIX = (
    "Instruct: Given something the user says to their assistant, retrieve facts about "
    "the user that help to answer it\nQuery: "
)
# Measured on qwen3-embedding:0.6b with Spanish facts (2026-10-24): related questions
# scored 0.41-0.60, unrelated ones 0.28-0.43. A stray fact in the prompt is harmless;
# a missed one is not, so recall is generous.
RECALL_SIMILARITY = 0.40
FORGET_SIMILARITY = 0.50
# "El cumpleaños de Ola..." vs "El cumpleaños de la mamá de Ola..." scored 0.93, so only
# a near-identical fact replaces an old one; corrections go through forget + remember.
DUPLICATE_SIMILARITY = 0.98
FORGET_MARGIN = 0.05

Embed = Callable[[Sequence[str]], list[list[float]]]


class OllamaEmbedder:
    def __init__(
        self,
        url: str,
        model: str = DEFAULT_EMBED_MODEL,
        *,
        timeout: float = 20.0,
        keep_alive: str = "30m",
    ) -> None:
        self._endpoint = url.rstrip("/") + "/api/embed"
        self._model = model
        self._timeout = timeout
        self._keep_alive = keep_alive

    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        payload = {"model": self._model, "input": list(texts), "keep_alive": self._keep_alive}
        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                vectors = json.load(response)["embeddings"]
        except (OSError, http.client.HTTPException, ValueError, KeyError) as exc:
            raise MemoryUnavailable(f"Embedding failed: {exc}") from exc
        if len(vectors) != len(texts):
            raise MemoryUnavailable("Embedding returned the wrong number of vectors")
        return vectors


def _words(text: str) -> set[str]:
    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c if c.isalnum() else " " for c in plain if not unicodedata.combining(c))
    return set(plain.split())


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
    return dot / norm if norm else 0.0


class SqliteMemory:
    def __init__(self, path: Path, embed: Embed) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._embed = embed
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS facts ("
            " id TEXT PRIMARY KEY, text TEXT NOT NULL, embedding BLOB NOT NULL,"
            " created_at TEXT NOT NULL)"
        )
        self._db.commit()

    def remember(self, text: str) -> MemoryFact:
        text = " ".join(text.split())
        if not text:
            raise ValueError("Empty fact")
        [vector] = self._embed([text])
        with self._lock:
            match = self._best(vector)
            fact_id = (
                match[1].id if match and match[0] >= DUPLICATE_SIMILARITY else uuid.uuid4().hex
            )
            fact = MemoryFact(fact_id, text, datetime.now(UTC).isoformat(timespec="seconds"))
            self._db.execute(
                "INSERT OR REPLACE INTO facts (id, text, embedding, created_at) VALUES (?, ?, ?, ?)",
                (fact.id, fact.text, array("f", vector).tobytes(), fact.created_at),
            )
            self._db.commit()
        return fact

    def recall(self, query: str, limit: int = 5) -> list[MemoryFact]:
        if not query.strip():
            return []
        with self._lock:
            if not self._count():
                return []  # nothing saved yet: skip the embedding call
        [vector] = self._embed([QUERY_PREFIX + query])
        with self._lock:
            scored = self._scored(vector)
        return [fact for score, fact in scored[:limit] if score >= RECALL_SIMILARITY]

    def forget(self, about: str) -> list[MemoryFact]:
        if not about.strip():
            return []
        # No query prefix here: the model often passes a bare topic ("taller"), which scores
        # 0.18 with the prefix and 0.33 without. Facts that contain every content word of
        # `about` go too, so "olvida lo del taller" works even when the score is low.
        [vector] = self._embed([about])
        keywords = [w for w in _words(about) if len(w) >= 4]
        with self._lock:
            scored = self._scored(vector)
            best = scored[0][0] if scored else 0.0
            # A vague request ("lo que sabes de mí") can score above the threshold for every
            # fact; only the ones about as close as the best match go.
            gone = [
                fact
                for score, fact in scored
                if (score >= FORGET_SIMILARITY and score >= best - FORGET_MARGIN)
                or (keywords and all(w in _words(fact.text) for w in keywords))
            ]
            self._db.executemany("DELETE FROM facts WHERE id = ?", [(f.id,) for f in gone])
            self._db.commit()
        return gone

    def warm_up(self) -> None:
        """Load the embedding model now: the first call takes ~20 s on this PC."""
        self._embed(["hola"])

    def all(self) -> list[MemoryFact]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, text, created_at FROM facts ORDER BY created_at"
            ).fetchall()
        return [MemoryFact(*row) for row in rows]

    # Called with the lock held

    def _count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

    def _scored(self, vector: Sequence[float]) -> list[tuple[float, MemoryFact]]:
        scored = []
        for fact_id, text, blob, created_at in self._db.execute(
            "SELECT id, text, embedding, created_at FROM facts"
        ):
            stored = array("f")
            stored.frombytes(blob)
            if len(stored) != len(vector):
                continue  # saved with another embedding model
            scored.append((_cosine(vector, stored), MemoryFact(fact_id, text, created_at)))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored

    def _best(self, vector: Sequence[float]) -> tuple[float, MemoryFact] | None:
        scored = self._scored(vector)
        return scored[0] if scored else None
