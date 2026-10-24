import pytest

from paula_hub.adapters.outbound.memory.store import OllamaEmbedder, SqliteMemory
from paula_hub.ports.outbound.memory import MemoryUnavailable

# One axis per topic: texts that mention the same topic point the same way.
TOPICS = ("rock", "perro", "dentista", "cumpleaños")


def fake_embed(texts):
    vectors = []
    for text in texts:
        lowered = text.lower()
        vector = [1.0 if topic in lowered else 0.0 for topic in TOPICS]
        vector.append(0.1)  # never a zero vector
        vectors.append(vector)
    return vectors


@pytest.fixture
def memory(tmp_path):
    return SqliteMemory(tmp_path / "memory.sqlite3", fake_embed)


def test_recall_finds_facts_by_topic(memory):
    memory.remember("A Ola le gusta el rock de los 80")
    memory.remember("Ola tiene un perro llamado Toby")

    assert [f.text for f in memory.recall("¿qué rock me gusta?")] == [
        "A Ola le gusta el rock de los 80"
    ]


def test_unrelated_question_recalls_nothing(memory):
    memory.remember("Ola tiene un perro llamado Toby")

    assert memory.recall("¿qué hora es?") == []


def test_near_duplicate_replaces_the_old_wording(memory):
    memory.remember("A Ola le gusta el rock")
    memory.remember("A Ola le encanta el rock de los 80")

    assert [f.text for f in memory.all()] == ["A Ola le encanta el rock de los 80"]


def test_forget_deletes_matching_facts(memory):
    memory.remember("Ola tiene cita con el dentista el lunes")
    memory.remember("Ola tiene un perro llamado Toby")

    gone = memory.forget("lo del dentista")

    assert [f.text for f in gone] == ["Ola tiene cita con el dentista el lunes"]
    assert [f.text for f in memory.all()] == ["Ola tiene un perro llamado Toby"]


def test_forget_with_no_match_deletes_nothing(memory):
    memory.remember("Ola tiene un perro llamado Toby")

    assert memory.forget("el cumpleaños") == []
    assert len(memory.all()) == 1


def test_memory_survives_a_restart(tmp_path):
    SqliteMemory(tmp_path / "m.sqlite3", fake_embed).remember("Ola tiene un perro")

    assert [f.text for f in SqliteMemory(tmp_path / "m.sqlite3", fake_embed).all()] == [
        "Ola tiene un perro"
    ]


def test_empty_memory_skips_the_embedding_call(tmp_path):
    def broken(texts):
        raise MemoryUnavailable("should not be called")

    assert SqliteMemory(tmp_path / "m.sqlite3", broken).recall("hola") == []


def test_empty_fact_is_rejected(memory):
    with pytest.raises(ValueError):
        memory.remember("   ")


def test_embedder_reports_ollama_down():
    embed = OllamaEmbedder("http://127.0.0.1:9", timeout=0.5)

    with pytest.raises(MemoryUnavailable):
        embed(["hola"])


def test_forget_by_keyword_when_the_score_is_low(tmp_path):
    def flat(texts):
        # The question points away from every fact: only the keyword can match.
        axes = {"rock": [1.0, 0.0, 0.0], "lo del": [0.0, 0.0, 1.0]}
        return [next((v for k, v in axes.items() if k in t), [0.0, 1.0, 0.0]) for t in texts]

    memory = SqliteMemory(tmp_path / "m.sqlite3", flat)
    memory.remember("Ola tiene una cita mañana con el taller para el carro")
    memory.remember("A Ola le gusta el rock")

    gone = memory.forget("lo del Taller")

    assert [f.text for f in gone] == ["Ola tiene una cita mañana con el taller para el carro"]
    assert [f.text for f in memory.all()] == ["A Ola le gusta el rock"]


def test_vague_forget_only_drops_the_closest_facts(tmp_path):
    def close(texts):
        # Every fact scores above the threshold, the dentist one clearly best.
        table = {"dentista": [1.0, 0.0], "perro": [0.6, 0.8], "rock": [0.55, 0.835]}
        return [next((v for k, v in table.items() if k in t), [0.95, 0.31]) for t in texts]

    memory = SqliteMemory(tmp_path / "m.sqlite3", close)
    for fact in ("Ola va al dentista", "Ola tiene un perro", "A Ola le gusta el rock"):
        memory.remember(fact)

    gone = memory.forget("eso que te dije")

    assert [f.text for f in gone] == ["Ola va al dentista"]
