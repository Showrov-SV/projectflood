"""Password hashing: salted PBKDF2-HMAC-SHA256, with transparent upgrade
of legacy hashes.

Stored format (self-describing, so the work factor can be raised later
without breaking existing accounts):

    pbkdf2_sha256$<iterations>$<salt hex>$<derived key hex>

Legacy format (what earlier versions of this app stored): a bare
64-character hex SHA-256 digest of the password with no salt.
verify_password() still accepts it so nobody is locked out, and
needs_rehash() flags it so authenticate_user() can silently replace it
with a PBKDF2 hash the next time that user logs in successfully.

Only the Python standard library is used (hashlib, hmac, os) - no extra
dependency. This module has no Streamlit or database dependency."""

import hashlib
import hmac
import os
import string
from concurrent.futures import ThreadPoolExecutor

from flood_app import config

SCHEME = "pbkdf2_sha256"

SALT_BYTES = 16

# Refuse absurd work factors found in a (possibly tampered) stored
# hash, so a bad row can't be used to hang the login page.
_MAX_ACCEPTED_ITERATIONS = 10_000_000

_HEX_DIGITS = set(string.hexdigits)


def _iterations():
    # Read at call time so tests (and deployments) can change it.
    return int(config.PASSWORD_HASH_ITERATIONS)


def _derive(password, salt, iterations):

    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )


def hash_password(password, iterations=None):
    """Returns a new salted PBKDF2 hash string for `password`."""

    iterations = int(iterations or _iterations())

    salt = os.urandom(SALT_BYTES)

    key = _derive(password, salt, iterations)

    return f"{SCHEME}${iterations}${salt.hex()}${key.hex()}"


def hash_many(passwords):
    """Hashes many passwords (used when seeding the default accounts).
    hashlib releases the GIL, so threads really do run in parallel on
    multi-core machines. Returns hashes in the same order."""

    passwords = list(passwords)

    if not passwords:
        return []

    workers = max(1, min(8, os.cpu_count() or 1))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(hash_password, passwords))


def is_legacy_hash(stored):
    """True for the old unsalted SHA-256 format (64 hex characters)."""

    return (
        isinstance(stored, str)
        and len(stored) == 64
        and all(ch in _HEX_DIGITS for ch in stored)
    )


def _parse(stored):
    """(iterations, salt_bytes, key_bytes) for a PBKDF2 hash string,
    or None if it isn't a well-formed one."""

    try:

        scheme, iterations, salt_hex, key_hex = stored.split("$")

        if scheme != SCHEME:
            return None

        iterations = int(iterations)

        if not 1 <= iterations <= _MAX_ACCEPTED_ITERATIONS:
            return None

        return iterations, bytes.fromhex(salt_hex), bytes.fromhex(key_hex)

    except (AttributeError, ValueError):

        return None


def verify_password(password, stored):
    """Constant-time check of `password` against a stored hash in
    either the PBKDF2 or the legacy SHA-256 format. Never raises."""

    if not stored or not isinstance(stored, str):
        return False

    password = password or ""

    if is_legacy_hash(stored):

        legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()

        return hmac.compare_digest(legacy, stored.lower())

    parsed = _parse(stored)

    if parsed is None:
        return False

    iterations, salt, expected = parsed

    return hmac.compare_digest(
        _derive(password, salt, iterations), expected
    )


def needs_rehash(stored):
    """True if the hash should be replaced after a successful login:
    legacy SHA-256, or PBKDF2 with fewer iterations than the current
    setting."""

    if is_legacy_hash(stored):
        return True

    parsed = _parse(stored)

    if parsed is None:
        return False

    return parsed[0] < _iterations()


_DUMMY_HASH = None


def dummy_verify(password):
    """Burns the same time as a real check. Used when the username
    doesn't exist, so response time doesn't reveal which usernames
    are real."""

    global _DUMMY_HASH

    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("dummy-password-for-timing")

    verify_password(password, _DUMMY_HASH)
