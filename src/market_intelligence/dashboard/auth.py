from __future__ import annotations

import base64
import hashlib
import secrets

PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 600_000


def create_password_hash(
    password: str,
    *,
    salt: bytes | None = None,
    iterations: int = PASSWORD_HASH_ITERATIONS,
) -> str:
    if not password:
        raise ValueError("Password cannot be empty")
    if iterations <= 0:
        raise ValueError("Iterations must be positive")

    resolved_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        resolved_salt,
        iterations,
    )
    return "$".join(
        (
            PASSWORD_HASH_SCHEME,
            str(iterations),
            base64.urlsafe_b64encode(resolved_salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        scheme, iterations_text, salt_text, expected_text = encoded_hash.split("$")
        if scheme != PASSWORD_HASH_SCHEME:
            return False
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(expected_text.encode("ascii"))
    except (TypeError, ValueError):
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return secrets.compare_digest(candidate, expected)


def verify_credentials(
    submitted_username: str,
    submitted_password: str,
    *,
    configured_username: str,
    configured_password_hash: str,
) -> bool:
    username_matches = secrets.compare_digest(
        submitted_username.encode("utf-8"),
        configured_username.encode("utf-8"),
    )
    password_matches = verify_password(submitted_password, configured_password_hash)
    return username_matches and password_matches
