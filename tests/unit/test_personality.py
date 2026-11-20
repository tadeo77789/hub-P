import os

from paula_hub.adapters.outbound.ollama.personality import (
    DEFAULT_PERSONALITY,
    MAX_PERSONALITY_CHARS,
    PersonalityFile,
)


def touch_later(path):
    """Edits within one clock tick can keep the same mtime; push it forward."""
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


def test_missing_file_is_created_with_the_default(tmp_path):
    path = tmp_path / "Paula" / "personalidad.txt"

    personality = PersonalityFile(path)

    assert path.read_text(encoding="utf-8") == DEFAULT_PERSONALITY + "\n"
    assert personality() == DEFAULT_PERSONALITY


def test_an_edit_applies_from_the_next_call(tmp_path):
    path = tmp_path / "personalidad.txt"
    path.write_text("Eres Paula, seria.", encoding="utf-8")
    personality = PersonalityFile(path)
    assert personality() == "Eres Paula, seria."

    path.write_text("Eres Paula, bromista y alegre.", encoding="utf-8")
    touch_later(path)

    assert personality() == "Eres Paula, bromista y alegre."


def test_notepad_bom_is_ignored(tmp_path):
    path = tmp_path / "personalidad.txt"
    path.write_text("Eres Paula.", encoding="utf-8-sig")

    assert PersonalityFile(path)() == "Eres Paula."


def test_empty_unreadable_or_deleted_file_falls_back_to_the_default(tmp_path):
    path = tmp_path / "personalidad.txt"
    path.write_text("   \n", encoding="utf-8")
    personality = PersonalityFile(path)
    assert personality() == DEFAULT_PERSONALITY

    path.write_bytes("Eres Paula, ñoña.".encode("latin-1"))  # not UTF-8
    touch_later(path)
    assert personality() == DEFAULT_PERSONALITY

    path.unlink()
    assert personality() == DEFAULT_PERSONALITY


def test_long_text_is_cut(tmp_path):
    path = tmp_path / "personalidad.txt"
    path.write_text("a" * (MAX_PERSONALITY_CHARS + 50), encoding="utf-8")

    assert len(PersonalityFile(path)()) == MAX_PERSONALITY_CHARS
