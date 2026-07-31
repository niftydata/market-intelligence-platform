from __future__ import annotations

from market_intelligence.dashboard.auth import (
    create_password_hash,
    verify_credentials,
    verify_password,
)


def test_password_hash_round_trip() -> None:
    encoded_hash = create_password_hash(
        "correct horse battery staple",
        salt=b"0123456789abcdef",
        iterations=1_000,
    )

    assert verify_password("correct horse battery staple", encoded_hash)
    assert not verify_password("wrong password", encoded_hash)


def test_malformed_password_hash_is_rejected() -> None:
    assert not verify_password("anything", "not-a-valid-hash")


def test_credentials_require_both_username_and_password() -> None:
    encoded_hash = create_password_hash(
        "demo-password",
        salt=b"0123456789abcdef",
        iterations=1_000,
    )

    assert verify_credentials(
        "macquarie",
        "demo-password",
        configured_username="macquarie",
        configured_password_hash=encoded_hash,
    )
    assert not verify_credentials(
        "someone-else",
        "demo-password",
        configured_username="macquarie",
        configured_password_hash=encoded_hash,
    )
