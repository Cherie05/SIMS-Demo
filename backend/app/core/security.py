"""Password hashing, tokens, one-time codes and field encryption.

passwords     Argon2id (OWASP parameters). Legacy bcrypt hashes verify and are upgraded on sign-in.
access tokens HS256 JWTs with a key id (kid): JWT_PREVIOUS_SECRET_KEYS keep tokens signed by a
              retired key valid until they expire, so the signing key can be rotated without
              signing everyone out.
derived keys  each purpose (one-time codes, recovery codes, field encryption fallback) gets its
              own key derived from the master secret, so one use can't be confused with another.
encryption    Fernet (AES-128-CBC + HMAC-SHA256) with key rotation via MultiFernet.
"""

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import bcrypt
import jwt
import pyotp
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import settings

ACCESS_TOKEN_TYPE = "access"  # nosec B105 - the JWT "type" claim value, not a secret
OTP_LENGTH = 6
TOTP_ISSUER = "SIMS"

# ----------------------------------------------------------------------------- passwords

_hasher = PasswordHasher(
    time_cost=settings.PASSWORD_HASH_ITERATIONS,
    memory_cost=settings.PASSWORD_HASH_MEMORY_KIB,
    parallelism=settings.PASSWORD_HASH_PARALLELISM,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith("$argon2"):
        try:
            return _hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
    if password_hash.startswith("$2"):  # bcrypt, from before the move to Argon2id
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except ValueError:
            return False
    return False


def password_needs_rehash(password_hash: str) -> bool:
    """True for legacy bcrypt hashes and Argon2 hashes made with weaker parameters than today's."""
    if not password_hash.startswith("$argon2"):
        return True
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# ----------------------------------------------------------------------------- key derivation


def _derive(purpose: str, secret: str | None = None) -> bytes:
    return hmac.new(
        (secret or settings.JWT_SECRET_KEY).encode("utf-8"), purpose.encode("utf-8"), hashlib.sha256
    ).digest()


def key_id(secret: str) -> str:
    """Public identifier of a signing key (never the key itself)."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]


# ----------------------------------------------------------------------------- access tokens (JWT)


def create_access_token(user_id: int, role: str, session_id: str | None = None) -> tuple[str, int]:
    """Return a signed, short-lived JWT and its lifetime in seconds."""
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": ACCESS_TOKEN_TYPE,
        "jti": secrets.token_hex(8),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    if session_id:
        payload["sid"] = session_id
    token = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        headers={"kid": key_id(settings.JWT_SECRET_KEY)},
    )
    return token, expires_in


def _verification_keys(token: str) -> list[str]:
    keys = settings.jwt_verification_keys
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError:
        return keys
    matching = [key for key in keys if key_id(key) == kid]
    return matching or keys


def decode_access_token(token: str) -> dict:
    """Validate signature, expiry, issuer, audience and token type. Raises jwt.PyJWTError."""
    error: jwt.PyJWTError = jwt.InvalidSignatureError("No verification key")
    for key in _verification_keys(token):
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=[settings.JWT_ALGORITHM],
                audience=settings.JWT_AUDIENCE,
                issuer=settings.JWT_ISSUER,
                options={"require": ["exp", "iat", "sub", "type"]},
            )
        except jwt.InvalidSignatureError as exc:
            error = exc
            continue
        if payload.get("type") != ACCESS_TOKEN_TYPE:
            raise jwt.InvalidTokenError("Not an access token")
        return payload
    raise error


# ----------------------------------------------------------------------------- opaque tokens


def new_opaque_token() -> str:
    """High-entropy random token (refresh tokens, OTP challenge ids)."""
    return secrets.token_urlsafe(32)


def new_session_id() -> str:
    return secrets.token_hex(16)


def hash_token(token: str) -> str:
    """Refresh tokens are stored hashed, so a database leak doesn't expose live sessions."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def request_fingerprint(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


# ----------------------------------------------------------------------------- one-time codes


def generate_otp() -> str:
    return f"{secrets.randbelow(10**OTP_LENGTH):0{OTP_LENGTH}d}"


def hash_otp(challenge_id: str, code: str) -> str:
    """Keyed hash: without the server secret, a leaked hash can't be brute-forced offline."""
    message = f"{challenge_id}:{code}".encode()
    return hmac.new(_derive("sims/otp"), message, hashlib.sha256).hexdigest()


def otp_matches(challenge_id: str, code: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(challenge_id, code), expected_hash)


# ----------------------------------------------------------------------------- recovery codes

_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i look-alikes


def generate_recovery_code() -> str:
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def normalize_recovery_code(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch.isalnum())


def hash_recovery_code(user_id: int, code: str) -> str:
    message = f"{user_id}:{normalize_recovery_code(code)}".encode()
    return hmac.new(_derive("sims/recovery-code"), message, hashlib.sha256).hexdigest()


# ----------------------------------------------------------------------------- field encryption


@lru_cache
def _fernet() -> MultiFernet:
    keys = settings.data_encryption_keys
    if not keys:
        # Development fallback. Deployed environments must set DATA_ENCRYPTION_KEYS (see config).
        keys = [base64.urlsafe_b64encode(_derive("sims/field-encryption")).decode()]
    return MultiFernet([Fernet(key) for key in keys])


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Stored secret can't be decrypted with the configured DATA_ENCRYPTION_KEYS") from exc


# ----------------------------------------------------------------------------- authenticator apps (TOTP)


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, account: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=TOTP_ISSUER)


def totp_match_step(secret: str, code: str, last_used_step: int | None, *, at: datetime | None = None) -> int | None:
    """Return the time step the code belongs to (current one, or one either side for clock drift),
    or None. A step at or before last_used_step is refused, so a code can't be replayed."""
    totp = pyotp.TOTP(secret)
    moment = at or datetime.now(UTC)
    current = totp.timecode(moment)
    for step in (current, current - 1, current + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None
