"""Servis ayarları (ortam değişkenleri, ``MI_`` önekli).

Gizli değerler (veritabanı parolası, ``MI_SECRET_KEK``) yönetilen bir gizli bilgi deposundan
ortam değişkeni olarak verilir; depoya ve imaja asla yazılmaz.
"""

from __future__ import annotations

import base64
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MI_", extra="ignore")

    environment: Environment = "development"
    # SQLAlchemy biçimi: postgresql+psycopg://kullanici:parola@sunucu:5432/veritabani
    database_url: SecretStr
    # Boşsa hız sınırı tek süreç içi bellekte tutulur (yalnızca geliştirme/test).
    redis_url: SecretStr | None = None

    # Kullanıcı uygulaması ve yönetim paneli kökenleri (CSRF: durum değiştiren istekler).
    web_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    admin_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    public_web_url: str = "http://localhost:3000"
    trusted_proxies: list[str] = ["127.0.0.1"]

    session_cookie_secure: bool = True
    session_days: int = Field(default=30, ge=1, le=90)
    admin_session_hours: int = Field(default=8, ge=1, le=12)
    # Kritik işlemlerden önce parola + MFA ile yeniden doğrulamanın geçerlilik süresi.
    reauth_window_s: int = Field(default=300, ge=60, le=900)
    # MFA ikinci adımı için bekleyen oturumun ömrü.
    mfa_pending_s: int = Field(default=300, ge=60, le=900)

    # TOTP sırlarını şifreleyen AES-256 anahtarı (base64, 32 bayt). Yoksa MFA kurulamaz.
    secret_kek: SecretStr | None = None

    # Futbol veri sağlayıcısı (Faz 2). "none": sağlayıcı yok; veri uydurulmaz, arayüz bunu gösterir.
    football_provider: Literal["none", "api_football", "football_data"] = "none"
    football_api_key: SecretStr | None = None
    # Yerel kota bütçesi (sağlayıcı paketine göre ayarlanır). Düşük öncelikli işler günlük bütçenin
    # son %reserve_pct'sini kullanamaz; o pay canlı maç ve günün fikstürü için ayrılır.
    football_daily_budget: int = Field(default=100, ge=1)
    football_minute_budget: int = Field(default=10, ge=1)
    football_reserve_pct: int = Field(default=20, ge=0, le=90)

    log_level: str = "INFO"
    log_json: bool = True

    @property
    def is_production_like(self) -> bool:
        return self.environment in ("staging", "production")

    def secret_kek_bytes(self) -> bytes | None:
        if self.secret_kek is None:
            return None
        return base64.b64decode(self.secret_kek.get_secret_value())

    @model_validator(mode="after")
    def _validate(self) -> Self:
        kek = self.secret_kek_bytes()
        if kek is not None and len(kek) != 32:
            raise ValueError("MI_SECRET_KEK base64 kodlu 32 bayt olmalı")
        key = self.football_api_key.get_secret_value() if self.football_api_key else ""
        if self.football_provider != "none" and not key.strip():
            raise ValueError("MI_FOOTBALL_PROVIDER seçiliyken MI_FOOTBALL_API_KEY zorunlu")
        if not self.is_production_like:
            return self
        problems: list[str] = []
        if not self.session_cookie_secure:
            problems.append("oturum çerezi Secure olmalı")
        insecure = [
            u
            for u in [self.public_web_url, *self.web_origins, *self.admin_origins]
            if not u.startswith("https://")
        ]
        if insecure:
            problems.append("adresler HTTPS olmalı: " + ", ".join(insecure))
        if kek is None:
            problems.append("MI_SECRET_KEK zorunlu (yönetici MFA'sı)")
        if self.redis_url is None:
            problems.append("MI_REDIS_URL zorunlu (çok örnekli hız sınırı)")
        dsn = self.database_url.get_secret_value()
        if "sslmode=verify-full" not in dsn:
            problems.append("veritabanı bağlantısında sslmode=verify-full zorunlu")
        if problems:
            raise ValueError(f"{self.environment} ortamı için ayar hatası: " + "; ".join(problems))
        return self
