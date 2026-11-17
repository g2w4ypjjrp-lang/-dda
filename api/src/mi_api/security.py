"""Güvenlik yapı taşları: parola özeti, belirteç özeti, TOTP (RFC 6238), kurtarma kodları,
AES-256-GCM gizli değer kutusu.

AI Trading Intelligence bulut servisindeki (``cloud/admin/security.py``) kanıtlanmış
uygulamadan taşınmıştır.

* Parola: Argon2id (t=3, m=64 MiB, p=2). Var olmayan kullanıcıda da aynı süre harcanır.
* Oturum / e-posta belirteçleri: 256 bit rastgele; veritabanında yalnızca SHA-256 özeti.
* TOTP: HMAC-SHA1, 6 hane, 30 sn, ±1 adım; aynı adım ikinci kez kabul edilmez.
* Kurtarma kodları: 10 adet ``XXXXX-XXXXX`` (Crockford Base32, 50 bit); yalnızca özet, tek kullanım.
* Gizli değer kutusu: AES-256-GCM, AAD kayda bağlı (başka kayda taşınan şifreli değer çözülmez).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TOTP_STEP_S = 30
TOTP_DIGITS = 6
ISSUER = "Match Intelligence AI"
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
MIN_PASSWORD = 10
MAX_PASSWORD = 256
COMMON_PASSWORDS = frozenset(
    {
        "1234567890", "12345678910", "password123", "parola1234", "qwertyuiop", "1q2w3e4r5t",
        "abcdefghij", "sifre12345", "0123456789", "password1!", "galatasaray", "fenerbahce",
        "besiktas1903", "trabzonspor", "football123", "futbol1234",
    }
)  # fmt: skip

hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)
_DUMMY_HASH = hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(stored: str | None, password: str) -> bool:
    """Sabit maliyetli doğrulama: ``stored`` yoksa da bir Argon2 doğrulaması yapılır."""
    try:
        return hasher.verify(stored or _DUMMY_HASH, password) and stored is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_problem(password: str, email: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"Parola en az {MIN_PASSWORD} karakter olmalı"
    if len(password) > MAX_PASSWORD:
        return "Parola çok uzun"
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS or len(set(password)) < 4:
        return "Bu parola çok kolay tahmin edilir"
    local = email.split("@", 1)[0].lower()
    if len(local) >= 4 and local in lowered:
        return "Parola e-posta adresinizi içermemeli"
    return None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


# --- TOTP -------------------------------------------------------------------------------------


def new_totp_secret() -> bytes:
    return secrets.token_bytes(20)


def totp_code(secret: bytes, counter: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)


def verify_totp(secret: bytes, code: str, *, last_counter: int | None, now: float) -> int | None:
    """Kod geçerliyse kullanılan zaman adımını döner; geçersiz veya tekrar kullanılmışsa None."""
    code = "".join(code.split())
    if len(code) != TOTP_DIGITS or not code.isdigit():
        return None
    current = int(now // TOTP_STEP_S)
    for counter in (current - 1, current, current + 1):
        if last_counter is not None and counter <= last_counter:
            continue
        if hmac.compare_digest(totp_code(secret, counter), code):
            return counter
    return None


def otpauth_uri(secret: bytes, account: str) -> str:
    label = quote(f"{ISSUER}:{account}")
    encoded = base64.b32encode(secret).decode().rstrip("=")
    return (
        f"otpauth://totp/{label}?secret={encoded}&issuer={quote(ISSUER)}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_STEP_S}"
    )


def new_recovery_codes(count: int = 10) -> list[str]:
    codes = []
    for _ in range(count):
        body = "".join(secrets.choice(_CROCKFORD) for _ in range(10))
        codes.append(f"{body[:5]}-{body[5:]}")
    return codes


def recovery_digest(code: str) -> bytes:
    normalized = "".join(code.split()).upper().replace("-", "")
    normalized = normalized.translate(str.maketrans("ILO", "110"))
    return hashlib.sha256(f"mi-recovery|{normalized}".encode()).digest()


class SecretBox:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Gizli anahtar 32 bayt olmalı")
        self._aead = AESGCM(key)

    def seal(self, plaintext: bytes, aad: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._aead.encrypt(nonce, plaintext, aad.encode())

    def open(self, blob: bytes, aad: str) -> bytes:
        return self._aead.decrypt(blob[:12], blob[12:], aad.encode())
