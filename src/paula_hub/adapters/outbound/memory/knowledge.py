"""KnowledgePort over a folder of documents (.md, .txt, .pdf), indexed in SQLite.

The user drops files into the folder; `sync` (at start and then every minute) splits
new or changed files into passages, embeds them and stores them, and drops passages of
files that were removed. `search` embeds the question and returns the closest passages.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from paula_hub.adapters.outbound.memory.store import Embed
from paula_hub.domain.knowledge import Passage
from paula_hub.ports.outbound.memory import MemoryUnavailable

log = logging.getLogger(__name__)

SUFFIXES = (".md", ".txt", ".pdf")
CHUNK_CHARS = 900
MAX_FILE_BYTES = 20_000_000
MAX_PDF_PAGES = 500
MAX_CHUNKS_PER_FILE = 2000
MAX_DEPTH = 8
EMBED_BATCH = 16
# Documents are not facts about the user, so they get their own instruction.
PASSAGE_PREFIX = (
    "Instruct: Given a question, retrieve passages from reference documents that answer it\nQuery: "
)
# Measured with qwen3-embedding:0.6b on the seed guides (2026-10-24): related questions
# scored 0.58-0.76, unrelated ones 0.36-0.41.
SEARCH_SIMILARITY = 0.50
# Notes for the user about the folder itself, not knowledge ("hola Paula" matched it).
IGNORED_NAMES = ("leeme", "readme")
NOTES_DIR = "notas de Paula"


@dataclass(frozen=True)
class SyncReport:
    indexed: list[str]
    removed: list[str]
    failed: list[str]


def read_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        pages = PdfReader(path).pages[:MAX_PDF_PAGES]
        return "\n\n".join(page.extract_text() or "" for page in pages)
    return path.read_text(encoding="utf-8", errors="replace")


def _blocks(text: str) -> Iterator[str]:
    """Paragraphs, with a Markdown heading always on its own and code fences kept whole."""
    current: list[str] = []
    in_fence = False
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            current.append(line)
        elif in_fence:
            current.append(line)
        elif re.match(r"^#{1,6}\s", line):
            if current:
                yield "\n".join(current)
            current = []
            yield line
        elif not line.strip():
            if current:
                yield "\n".join(current)
            current = []
        else:
            current.append(line)
    if current:
        yield "\n".join(current)


def _pieces(block: str, limit: int) -> Iterator[str]:
    """Cut a huge paragraph near sentence ends, walking by index (linear time)."""
    start = 0
    while len(block) - start > limit:
        cut = block.rfind(". ", start, start + limit)
        cut = cut + 1 if cut > start + limit // 2 else start + limit
        yield block[start:cut].strip()
        start = cut
    yield block[start:].strip()


def split_passages(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Paragraph-sized passages, each prefixed with the Markdown headings above it."""
    passages: list[str] = []
    headings: dict[int, str] = {}
    current: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal size
        body = "\n".join(current).strip()
        if body:
            trail = " > ".join(headings[k] for k in sorted(headings))
            passages.append(f"{trail}\n{body}" if trail else body)
        current.clear()
        size = 0

    for block in _blocks(text):
        heading = re.match(r"^(#{1,6})\s+(.*)", block)
        if heading and "\n" not in block:
            flush()
            level = len(heading.group(1))
            headings = {k: v for k, v in headings.items() if k < level}
            headings[level] = heading.group(2).strip()
            continue
        for piece in _pieces(block.strip(), limit):
            if not piece:
                continue
            if current and size + len(piece) > limit:
                flush()
            current.append(piece)
            size += len(piece)
    flush()
    return passages


def _is_link(path: Path) -> bool:
    # Path.is_junction only exists since Python 3.12.
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _slug(title: str) -> str:
    plain = unicodedata.normalize("NFKD", title.casefold())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:60] or "nota"


def _normalized(vector) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(array))
    return array / norm if norm else array


class FolderKnowledge:
    def __init__(
        self,
        folder: Path,
        db_path: Path,
        embed: Embed,
        *,
        recall_embed: Embed | None = None,
        model: str = "",
    ) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.folder = folder
        self._embed = embed
        self._recall_embed = recall_embed or embed
        self._lock = threading.Lock()
        # Files that could not be read, with the (mtime, size) that failed: not retried
        # every minute, only when the file changes.
        self._failed: dict[str, tuple[float, int]] = {}
        # Normalised passage vectors kept in memory; rebuilt after the index changes.
        self._matrix: np.ndarray | None = None
        self._entries: list[Passage] = []
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, timeout=2)
        self._db.executescript(
            "CREATE TABLE IF NOT EXISTS files ("
            " source TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL);"
            "CREATE TABLE IF NOT EXISTS passages ("
            " source TEXT NOT NULL, idx INTEGER NOT NULL, text TEXT NOT NULL,"
            " embedding BLOB NOT NULL, PRIMARY KEY (source, idx));"
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        )
        stored = self._db.execute("SELECT value FROM meta WHERE key = 'model'").fetchone()
        if model and stored and stored[0] != model:
            # Vectors from another embedding model cannot be compared: index everything again.
            log.info("Embedding model changed (%s -> %s); re-indexing knowledge", stored[0], model)
            self._db.executescript("DELETE FROM passages; DELETE FROM files;")
        if model:
            self._db.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('model', ?)", (model,)
            )
        self._db.commit()

    # Indexing

    def _files(self) -> dict[str, Path]:
        found = {}
        for root, dirs, names in os.walk(self.folder):
            here = Path(root)
            depth = len(here.relative_to(self.folder).parts)
            # Never follow junctions or symlinks (loops, other drives), nor go too deep.
            dirs[:] = [d for d in dirs if depth < MAX_DEPTH and not _is_link(here / d)]
            for name in names:
                path = here / name
                if path.suffix.lower() in SUFFIXES and path.stem.lower() not in IGNORED_NAMES:
                    found[path.relative_to(self.folder).as_posix()] = path
        return found

    def sync(self) -> SyncReport:
        files = self._files()
        with self._lock:
            known = {s: (m, z) for s, m, z in self._db.execute("SELECT * FROM files")}
        indexed, failed = [], []
        for source, path in sorted(files.items()):
            try:
                stat = path.stat()
            except OSError:
                continue  # removed or locked since the folder was listed
            version = (stat.st_mtime, stat.st_size)
            if known.get(source) == version or self._failed.get(source) == version:
                continue
            try:
                self._index(source, path, *version)
                self._failed.pop(source, None)
                indexed.append(source)
            except MemoryUnavailable:
                raise  # Ollama is down: try the whole sync again later
            except Exception:
                log.warning("Could not read %s", source, exc_info=True)
                self._failed[source] = version
                failed.append(source)
        removed = sorted(set(known) - set(files))
        with self._lock:
            for source in removed:
                self._db.execute("DELETE FROM passages WHERE source = ?", (source,))
                self._db.execute("DELETE FROM files WHERE source = ?", (source,))
            self._db.commit()
            if removed:
                self._matrix = None
        if indexed or removed:
            log.info("Knowledge: %d indexed, %d removed", len(indexed), len(removed))
        return SyncReport(indexed, removed, failed)

    def _index(self, source: str, path: Path, mtime: float, size: int) -> None:
        if size > MAX_FILE_BYTES:
            raise ValueError(f"larger than {MAX_FILE_BYTES} bytes")
        passages = split_passages(read_text(path))[:MAX_CHUNKS_PER_FILE]
        vectors: list[list[float]] = []
        for start in range(0, len(passages), EMBED_BATCH):
            vectors += self._embed(passages[start : start + EMBED_BATCH])
        with self._lock:
            self._db.execute("DELETE FROM passages WHERE source = ?", (source,))
            self._db.executemany(
                "INSERT INTO passages (source, idx, text, embedding) VALUES (?, ?, ?, ?)",
                [
                    (source, i, text, _normalized(vector).tobytes())
                    for i, (text, vector) in enumerate(zip(passages, vectors, strict=True))
                ],
            )
            self._db.execute(
                "INSERT OR REPLACE INTO files (source, mtime, size) VALUES (?, ?, ?)",
                (source, mtime, size),
            )
            self._db.commit()
            self._matrix = None

    def _load(self) -> tuple[np.ndarray, list[Passage]]:
        """Called with the lock held."""
        if self._matrix is None:
            rows = self._db.execute("SELECT source, text, embedding FROM passages").fetchall()
            dims = {len(blob) for _, _, blob in rows}
            size = max(dims, key=lambda d: sum(len(b) == d for _, _, b in rows)) if dims else 0
            # Rows from another embedding model (other size) are left out.
            keep = [(s, t, b) for s, t, b in rows if len(b) == size]
            self._entries = [Passage(s, t) for s, t, _ in keep]
            self._matrix = (
                np.frombuffer(b"".join(b for _, _, b in keep), dtype=np.float32).reshape(
                    len(keep), -1
                )
                if keep
                else np.zeros((0, 0), dtype=np.float32)
            )
        return self._matrix, self._entries

    # KnowledgePort

    def search(self, query: str, limit: int = 3) -> list[Passage]:
        if not query.strip():
            return []
        try:
            with self._lock:
                matrix, entries = self._load()
        except sqlite3.Error as exc:
            raise MemoryUnavailable(f"Knowledge database error: {exc}") from exc
        if not entries:
            return []
        [vector] = self._recall_embed([PASSAGE_PREFIX + query])
        query_vector = _normalized(vector)
        if matrix.shape[1] != query_vector.shape[0]:
            return []  # indexed with another embedding model
        scores = matrix @ query_vector  # cosine: both sides are normalised
        best = np.argsort(scores)[::-1][:limit]
        return [entries[i] for i in best if scores[i] >= SEARCH_SIMILARITY]

    def learn(self, title: str, text: str) -> str:
        text = text.strip()
        if not text:
            raise ValueError("Empty note")
        notes = self.folder / NOTES_DIR
        notes.mkdir(exist_ok=True)
        stem = f"{datetime.now():%Y-%m-%d %H%M%S} {_slug(title)}"
        path = notes / f"{stem}.md"
        n = 2
        while True:
            try:
                with path.open("x", encoding="utf-8") as handle:  # never overwrite a note
                    handle.write(f"# {title.strip() or 'Nota'}\n\n{text}\n")
                break
            except FileExistsError:
                path = notes / f"{stem} ({n}).md"
                n += 1
        stat = path.stat()
        source = path.relative_to(self.folder).as_posix()
        try:
            self._index(source, path, stat.st_mtime, stat.st_size)
        except Exception as exc:
            # Reported as failed, so leave no file behind that would be indexed later.
            path.unlink(missing_ok=True)
            raise MemoryUnavailable(f"Could not index the note: {exc}") from exc
        return source
