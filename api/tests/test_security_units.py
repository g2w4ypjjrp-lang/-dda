"""Saf fonksiyon birim testleri: TOTP, kurtarma kodu, gizli kutu, maskeleme, ayar doğrulaması."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import pytest
from cryptography.exceptions import InvalidTag
from pydantic import ValidationError

from mi_api import security
from mi_api.config import Settings
from mi_api.guards import json_depth_exceeds
from mi_api.logs import MASK, JsonFormatter, redact

RFC6238_SECRET = b"12345678901234567890"


@pytest.mark.parametrize(
    ("t", "expected"),
    [(59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")],
)
def test_totp_rfc6238_vectors(t: int, expected: str) -> None:
    assert security.totp_code(RFC6238_SECRET, t // 30) == expected


def test_totp_window_and_replay() -> None:
    now = 1_800_000_000.0
    step = int(now // 30)
    code = security.totp_code(RFC6238_SECRET, step)
    assert security.verify_totp(RFC6238_SECRET, code, last_counter=None, now=now) == step
    assert security.verify_totp(RFC6238_SECRET, code, last_counter=step, now=now) is None
    prev = security.totp_code(RFC6238_SECRET, step - 1)
    assert security.verify_totp(RFC6238_SECRET, prev, last_counter=None, now=now) == step - 1
    old = security.totp_code(RFC6238_SECRET, step - 2)
    assert security.verify_totp(RFC6238_SECRET, old, last_counter=None, now=now) is None
    assert security.verify_totp(RFC6238_SECRET, "12a456", last_counter=None, now=now) is None


def test_recovery_code_normalization() -> None:
    codes = security.new_recovery_codes()
    assert len(codes) == 10 and all(len(c) == 11 and c[5] == "-" for c in codes)
    assert security.recovery_digest("abcde-fghjk") == security.recovery_digest("ABCDE FGHJK")
    assert security.recovery_digest("O0IL1-xxxxx") == security.recovery_digest("00111-XXXXX")


def test_secret_box_binds_record() -> None:
    box = security.SecretBox(b"x" * 32)
    blob = box.seal(b"gizli", "mfa|a")
    assert box.open(blob, "mfa|a") == b"gizli"
    with pytest.raises(InvalidTag):
        box.open(blob, "mfa|b")
    with pytest.raises(ValueError, match="32"):
        security.SecretBox(b"short")


def test_password_hashing() -> None:
    hashed = security.hash_password("Parola-Deneme-1")
    assert hashed.startswith("$argon2id$")
    assert security.verify_password(hashed, "Parola-Deneme-1")
    assert not security.verify_password(hashed, "yanlis")
    assert not security.verify_password(None, "Parola-Deneme-1")
    assert not security.verify_password("bozuk", "x")


def test_redaction() -> None:
    data = {
        "password": "p", "new_password": "p", "token": "t", "code": "123456", "role_code": "ADMIN",
        "nested": [{"api_key": "k"}], "note": "Authorization: Bearer abc.def", "id": "x" * 50,
    }  # fmt: skip
    out = redact(data)
    assert out["password"] == out["new_password"] == out["token"] == out["code"] == MASK
    assert out["role_code"] == "ADMIN"
    assert out["nested"][0]["api_key"] == MASK
    assert "abc.def" not in out["note"]
    assert out["id"] == MASK


def test_json_log_formatter_redacts() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "Bearer abcdef123", None, None)
    record.fields = {"password": "gizli"}
    line = json.loads(JsonFormatter().format(record))
    assert "abcdef123" not in line["msg"] and line["password"] == MASK


def test_json_depth() -> None:
    assert json_depth_exceeds(b"[" * 40 + b"]" * 40, 32)
    assert not json_depth_exceeds(b'{"a": "[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[["}', 32)


def _kek() -> str:
    return base64.b64encode(b"k" * 32).decode()


def test_production_settings_validation() -> None:
    with pytest.raises(ValidationError) as err:
        Settings(environment="production", database_url="postgresql://x/y")  # type: ignore[arg-type]
    message = str(err.value)
    for part in ("HTTPS", "MI_SECRET_KEK", "MI_REDIS_URL", "verify-full"):
        assert part in message
    ok = Settings(
        environment="production",
        database_url="postgresql://x/y?sslmode=verify-full",  # type: ignore[arg-type]
        redis_url="rediss://r:6380/0",  # type: ignore[arg-type]
        secret_kek=_kek(),  # type: ignore[arg-type]
        web_origins=["https://matchintelligence.ai"],
        admin_origins=["https://admin.matchintelligence.ai"],
        public_web_url="https://matchintelligence.ai",
    )
    assert ok.is_production_like


def test_private_network_database_only_for_container_hosts() -> None:
    """Tek VDS kurulumu: TLS şartı yalnızca aynı Docker ağındaki kapsayıcı adıyla kalkar."""
    common: dict[str, Any] = {
        "environment": "production",
        "redis_url": "redis://redis:6379/0",
        "secret_kek": _kek(),
        "web_origins": ["https://futbol.canarslan.net.tr"],
        "admin_origins": ["https://futbol.canarslan.net.tr"],
        "public_web_url": "https://futbol.canarslan.net.tr",
        "database_private_network": True,
    }
    ok = Settings(database_url="postgresql://mi:p@postgres:5432/mi", **common)
    assert ok.database_private_network
    for remote in ("db.example.com", "10.0.0.5", "localhost.localdomain"):
        with pytest.raises(ValidationError, match="kapsayıcı adıyla"):
            Settings(database_url=f"postgresql://mi:p@{remote}:5432/mi", **common)
    # Bayrak olmadan aynı adres reddedilir (TLS şartı geçerli).
    with pytest.raises(ValidationError, match="verify-full"):
        Settings(
            database_url="postgresql://mi:p@postgres:5432/mi",
            **{**common, "database_private_network": False},
        )


def test_kek_length_validated() -> None:
    with pytest.raises(ValidationError, match="32 bayt"):
        Settings(database_url="postgresql://x/y", secret_kek=base64.b64encode(b"k").decode())  # type: ignore[arg-type]
