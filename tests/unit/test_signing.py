import pytest

from paula_hub.adapters.signing import InvalidSignature, sign, verify

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
