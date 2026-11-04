import hashlib
import secrets

HASH_ITERATIONS = 600_000


def generate_salt() -> str:
    """Generate a cryptographically secure random salt."""

    return secrets.token_hex(16)


def hash_password(password: str, salt: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256."""

    return hashlib.pbkdf2_hmac(
        hash_name="sha256",
        password=password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        iterations=HASH_ITERATIONS,
    ).hex()
