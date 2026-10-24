import pytest

from paula_hub.adapters.signing import InvalidSignature, SeenIds, sign, verify

SECRET = "s3cret"
BODY = b'{"id": "1"}'


def test_signed_message_verifies():
    verify(SECRET, BODY, sign(SECRET, BODY, now=1000), now=1010)


def test_tampered_body_is_rejected():
    headers = sign(SECRET, BODY, now=1000)

    with pytest.raises(InvalidSignature):
        verify(SECRET, b"{}", headers, now=1000)


def test_missing_headers_are_rejected():
    with pytest.raises(InvalidSignature):
        verify(SECRET, BODY, {})


def test_old_message_is_rejected():
    headers = sign(SECRET, BODY, now=1000)

    with pytest.raises(InvalidSignature):
        verify(SECRET, BODY, headers, max_age_seconds=60, now=2000)


def test_seen_ids_reject_replays_and_forget_old_ones():
    seen = SeenIds(limit=2)

    assert seen.add("a") and seen.add("b")
    assert not seen.add("a")
    assert seen.add("c")  # evicts "a"
    assert seen.add("a")
    assert seen.add(None)


def test_seen_ids_persist(tmp_path):
    path = tmp_path / "seen.txt"
    SeenIds(path=path).add("action-1")

    assert not SeenIds(path=path).add("action-1")
