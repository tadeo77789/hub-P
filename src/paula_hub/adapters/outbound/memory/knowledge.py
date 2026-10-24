"""KnowledgePort over a folder of documents (.md, .txt, .pdf), indexed in SQLite.

The user drops files into the folder; `sync` (at start and then every minute) splits
new or changed files into passages, embeds them and stores them, and drops passages of
files that were removed. `search` embeds the question and returns the closest passages.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import unicodedata
from array import array
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from paula_hub.adapters.outbound.memory.store import QUERY_PREFIX, Embed, _cosine
from paula_hub.domain.knowledge import Passage
from paula_hub.ports.outbound.memory import MemoryUnavailable

log = logging.getLogger(__name__)

SUFFIXES = (".md", ".txt", ".pdf")
CHUNK_CHARS = 900
MAX_FILE_BYTES = 20_000_000
MAX_CHUNKS_PER_FILE = 2000
EMBED_BATCH = 16
# Passages are longer than facts, so they score a bit higher against a related question.
SEARCH_SIMILARITY = 0.45
NOTES_DIR = "notas de Paula"


@dataclass(frozen=True)
class SyncReport:
    indexed: list[str]
    removed: list[str]
    failed: list[str]


def read_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        return "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    return path.read_text(encoding="utf-8", errors="replace")


def split_passages(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Paragraph-sized passages, each prefixed with the Markdown headings above it."""
    passages: list[str] = []
    headings: dict[int, str] = {}
    current: list[str] = []

    def flush() -> None:
        body = "\n".join(current).strip()
        if body:
            trail = " > ".join(headings[k] for k in sorted(headings))
            passages.append(f"{trail}\n{body}" if trail else body)
        current.clear()

    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)", block)
        if heading and "\n" not in block:
            flush()
            level = len(heading.group(1))
            headings = {k: v for k, v in headings.items() if k < level}
            headings[level] = heading.group(2).strip()
            continue
        while len(block) > limit:  # a huge paragraph: cut at a sentence end if possible
            cut = block.rfind(". ", 0, limit)
            cut = cut + 1 if cut > limit // 2 else limit
            flush()
            current.append(block[:cut])
            block = block[cut:].strip()
        if sum(len(p) for p in current) + len(block) > limit:
            flush()
        current.append(block)
    flush()
    return passages


def _slug(title: str) -> str:
    plain = unicodedata.normalize("NFKD", title.casefold())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:60] or "nota"


class FolderKnowledge:
    def __init__(
        self, folder: Path, db_path: Path, embed: Embed, *, recall_embed: Embed | None = None
    ) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.folder = folder
        self._embed = embed
        self._recall_embed = recall_embed or embed
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, timeout=2)
        self._db.executescript(
            "CREATE TABLE IF NOT EXISTS files ("
            " source TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL);"
            "CREATE TABLE IF NOT EXISTS passages ("
            " source TEXT NOT NULL, idx INTEGER NOT NULL, text TEXT NOT NULL,"
            " embedding BLOB NOT NULL, PRIMARY KEY (source, idx));"
        )
        self._db.commit()

    # Indexing

    def _files(self) -> dict[str, Path]:
        found = {}
        for path in self.folder.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUFFIXES:
                found[path.relative_to(self.folder).as_posix()] = path
        return found

    def sync(self) -> SyncReport:
        files = self._files()
        with self._lock:
            known = {s: (m, z) for s, m, z in self._db.execute("SELECT * FROM files")}
        indexed, failed = [], []
        for source, path in sorted(files.items()):
            stat = path.stat()
            if known.get(source) == (stat.st_mtime, stat.st_size):
                continue
            try:
                self._index(source, path, stat.st_mtime, stat.st_size)
                indexed.append(source)
            except MemoryUnavailable:
                raise  # Ollama is down: try the whole sync again later
            except Exception:
                log.warning("Could not read %s", source, exc_info=True)
                failed.append(source)
        removed = sorted(set(known) - set(files))
        with self._lock:
            for source in removed:
                self._db.execute("DELETE FROM passages WHERE source = ?", (source,))
                self._db.execute("DELETE FROM files WHERE source = ?", (source,))
            self._db.commit()
        if indexed or removed:
            log.info("Knowledge: %d indexed, %d removed", len(indexed), len(removed))
        return SyncReport(indexed, removed, failed)

    def _index(self, source: str, path: Path, mtime: float, size: int) -> None:
        if size > MAX_FILE_BYTES:
            raise ValueError(f"{source} is larger than {MAX_FILE_BYTES} bytes")
        passages = split_passages(read_text(path))[:MAX_CHUNKS_PER_FILE]
        vectors: list[list[float]] = []
        for start in range(0, len(passages), EMBED_BATCH):
            vectors += self._embed(passages[start : start + EMBED_BATCH])
        with self._lock:
            self._db.execute("DELETE FROM passages WHERE source = ?", (source,))
            self._db.executemany(
                "INSERT INTO passages (source, idx, text, embedding) VALUES (?, ?, ?, ?)",
                [
                    (source, i, text, array("f", vector).tobytes())
                    for i, (text, vector) in enumerate(zip(passages, vectors, strict=True))
                ],
            )
            self._db.execute(
                "INSERT OR REPLACE INTO files (source, mtime, size) VALUES (?, ?, ?)",
                (source, mtime, size),
            )
            self._db.commit()

    # KnowledgePort

    def search(self, query: str, limit: int = 3) -> list[Passage]:
        if not query.strip():
            return []
        try:
            with self._lock:
                empty = self._db.execute("SELECT 1 FROM passages LIMIT 1").fetchone() is None
            if empty:
                return []
            [vector] = self._recall_embed([QUERY_PREFIX + query])
            scored = []
            with self._lock:
                for source, text, blob in self._db.execute(
                    "SELECT source, text, embedding FROM passages"
                ):
                    stored = array("f")
                    stored.frombytes(blob)
                    if len(stored) == len(vector):
                        scored.append((_cosine(vector, stored), Passage(source, text)))
        except sqlite3.Error as exc:
            raise MemoryUnavailable(f"Knowledge database error: {exc}") from exc
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [p for score, p in scored[:limit] if score >= SEARCH_SIMILARITY]

    def learn(self, title: str, text: str) -> str:
        text = text.strip()
        if not text:
            raise ValueError("Empty note")
        notes = self.folder / NOTES_DIR
        notes.mkdir(exist_ok=True)
        name = f"{datetime.now():%Y-%m-%d %H%M} {_slug(title)}.md"
        path = notes / name
        path.write_text(f"# {title.strip() or 'Nota'}\n\n{text}\n", encoding="utf-8")
        stat = path.stat()
        source = path.relative_to(self.folder).as_posix()
        try:
            self._index(source, path, stat.st_mtime, stat.st_size)
        except sqlite3.Error as exc:
            raise MemoryUnavailable(f"Knowledge database error: {exc}") from exc
        return source
