from paula_hub.application.sentences import SentenceSplitter


def feed_all(splitter, chunks):
    out = []
    for chunk in chunks:
        out.extend(splitter.feed(chunk))
    return out + splitter.flush()


def test_splits_streamed_tokens_into_sentences():
    splitter = SentenceSplitter()

    sentences = feed_all(splitter, ["Hola, Ola", ". Hoy el PC", " está bien. ¿Algo", " más?"])

    assert sentences == ["Hola, Ola.", "Hoy el PC está bien.", "¿Algo más?"]


def test_short_sentences_are_merged():
    splitter = SentenceSplitter()

    assert feed_all(splitter, ["Sí. Ya abrí Spotify. "]) == ["Sí. Ya abrí Spotify."]


def test_no_boundary_until_whitespace():
    splitter = SentenceSplitter()

    assert splitter.feed("Son las 3.5 horas") == []
    assert splitter.flush() == ["Son las 3.5 horas"]


def test_flush_on_empty_buffer():
    assert SentenceSplitter().flush() == []
