import os

import pytest

from paula_hub.adapters.outbound.memory.knowledge import FolderKnowledge, split_passages

TOPICS = ("hexagonal", "solid", "git", "docker")


def fake_embed(texts):
    vectors = []
    for text in texts:
        lowered = text.lower()
        vectors.append([1.0 if t in lowered else 0.0 for t in TOPICS] + [0.05])
    return vectors


@pytest.fixture
def kb(tmp_path):
    folder = tmp_path / "Conocimiento"
    return FolderKnowledge(folder, tmp_path / "knowledge.sqlite3", fake_embed)


def write(kb, name, text):
    path = kb.folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_passages_keep_their_headings():
    text = "# Arquitectura\n\n## Hexagonal\n\nEl núcleo no conoce los adaptadores.\n\n## Capas\n\nCada capa usa la de abajo."

    assert split_passages(text) == [
        "Arquitectura > Hexagonal\nEl núcleo no conoce los adaptadores.",
        "Arquitectura > Capas\nCada capa usa la de abajo.",
    ]


def test_long_paragraphs_are_cut_near_a_sentence_end():
    text = "Primera frase larga. " * 80

    passages = split_passages(text, limit=300)

    assert all(len(p) <= 300 for p in passages)
    assert all(p.endswith(".") for p in passages[:-1])


def test_sync_indexes_new_files_and_search_finds_them(kb):
    write(kb, "arquitectura.md", "# Hexagonal\n\nPuertos y adaptadores.")
    write(kb, "git.txt", "Git flow usa ramas feature y develop.")
    write(kb, "ignorado.docx", "no soportado")

    report = kb.sync()

    assert report.indexed == ["arquitectura.md", "git.txt"]
    [passage] = kb.search("¿qué es la arquitectura hexagonal?")
    assert passage.source == "arquitectura.md"
    assert "Puertos y adaptadores" in passage.text


def test_sync_skips_unchanged_files_and_drops_removed_ones(kb):
    path = write(kb, "git.txt", "Git flow")
    kb.sync()

    assert kb.sync().indexed == []
    os.remove(path)
    report = kb.sync()

    assert report.removed == ["git.txt"]
    assert kb.search("git") == []


def test_changed_file_is_reindexed(kb):
    path = write(kb, "notas.md", "Docker sirve para contenedores.")
    kb.sync()
    path.write_text("Ahora hablo de SOLID.", encoding="utf-8")
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 10))

    assert kb.sync().indexed == ["notas.md"]
    assert kb.search("docker") == []
    assert kb.search("principios solid")[0].text == "Ahora hablo de SOLID."


def test_unrelated_question_finds_nothing(kb):
    write(kb, "git.txt", "Git flow")
    kb.sync()

    assert kb.search("¿qué hora es?") == []


def test_learn_saves_a_note_and_indexes_it(kb):
    source = kb.learn("Docker básico", "Docker empaqueta apps en contenedores.")

    assert source.startswith("notas de Paula/")
    assert (kb.folder / source).read_text(encoding="utf-8").startswith("# Docker básico")
    assert kb.search("¿qué es docker?")[0].source == source
    assert kb.sync().indexed == []  # already indexed


def test_unreadable_file_is_reported_not_fatal(kb):
    write(kb, "roto.pdf", "esto no es un pdf")
    write(kb, "git.txt", "Git flow")

    report = kb.sync()

    assert report.failed == ["roto.pdf"]
    assert report.indexed == ["git.txt"]


def test_reads_pdf(kb, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 20 200 Td (Docker y contenedores) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    with open(kb.folder / "guia.pdf", "wb") as handle:
        writer.write(handle)

    kb.sync()

    assert "Docker" in kb.search("docker")[0].text


def test_heading_without_blank_line_and_hash_inside_code():
    text = (
        "# Guía\n## Docker\nSirve para contenedores.\n\n```\nRUN echo hola\n\n# comentario\n```\n"
    )

    passages = split_passages(text)

    assert passages[0].startswith("Guía > Docker\nSirve para contenedores.")
    assert all("comentario" != p.split("\n")[0] for p in passages)
    assert any("# comentario" in p and "RUN echo hola" in p for p in passages)


def test_huge_paragraph_is_split_quickly():
    import time

    start = time.perf_counter()
    passages = split_passages("Una frase. " * 200_000)

    assert time.perf_counter() - start < 2
    assert all(len(p) <= 900 for p in passages)


def test_two_notes_with_the_same_title_never_overwrite(kb):
    first = kb.learn("Docker", "uno")
    second = kb.learn("Docker", "dos")

    assert first != second
    assert (kb.folder / first).read_text(encoding="utf-8").endswith("uno\n")


def test_failed_note_leaves_no_file(tmp_path):
    from paula_hub.ports.outbound.memory import MemoryUnavailable

    def down(texts):
        raise MemoryUnavailable("ollama down")

    kb = FolderKnowledge(tmp_path / "K", tmp_path / "k.sqlite3", down)

    with pytest.raises(MemoryUnavailable):
        kb.learn("Docker", "texto")

    assert not list((tmp_path / "K").rglob("*.md"))


def test_failed_file_is_not_retried_until_it_changes(kb, monkeypatch):
    path = write(kb, "roto.pdf", "no es un pdf")
    calls = []
    import paula_hub.adapters.outbound.memory.knowledge as module

    real = module.read_text
    monkeypatch.setattr(module, "read_text", lambda p: calls.append(p) or real(p))

    assert kb.sync().failed == ["roto.pdf"]
    assert kb.sync().failed == []  # skipped, not re-parsed
    assert len(calls) == 1
    path.write_text("ahora tampoco", encoding="utf-8")
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 10))
    assert kb.sync().failed == ["roto.pdf"]


def test_folder_readme_is_not_knowledge(kb):
    write(kb, "LEEME.txt", "Carpeta de conocimiento de Paula")
    write(kb, "git.txt", "Git flow")

    assert kb.sync().indexed == ["git.txt"]


def test_changing_the_embedding_model_reindexes(tmp_path):
    folder, db = tmp_path / "K", tmp_path / "k.sqlite3"
    kb = FolderKnowledge(folder, db, fake_embed, model="modelo-a")
    write(kb, "git.txt", "Git flow")
    kb.sync()

    again = FolderKnowledge(folder, db, fake_embed, model="modelo-b")

    assert again.sync().indexed == ["git.txt"]
