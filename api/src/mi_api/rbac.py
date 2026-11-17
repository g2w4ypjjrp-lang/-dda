"""Rol ve izin kataloğu (RBAC).

Kaynak gerçeği veritabanıdır (``roles``, ``permissions``, ``role_permissions``); bu modül ilk
geçişin tohumladığı kataloğu ve kodun beklediği izin adlarını tanımlar. Testler, geçiş sonrası
veritabanının bu kataloğa eşit olduğunu doğrular.

Yetki kontrolü **her zaman backend'de** yapılır (``require_permission``); arayüz yalnızca
yetkisi olmayan düğmeleri gizler.

``SENSITIVE`` izinler, son ``reauth_window_s`` içinde parola + MFA ile yeniden doğrulama ister.
"""

from __future__ import annotations

from typing import Final

PERMISSIONS: Final[dict[str, str]] = {
    "users.read": "Kullanıcıları ve ayrıntılarını görüntüleme",
    "users.manage": "Kullanıcı hesabını askıya alma / etkinleştirme",
    "roles.read": "Rol ve izin matrisini görüntüleme",
    "roles.assign": "Kullanıcılara yönetici rolü atama / kaldırma",
    "audit.read": "Denetim kaydını görüntüleme ve doğrulama",
    "subscriptions.read": "Abonelikleri görüntüleme",
    "subscriptions.manage": "Abonelik ve plan limitlerini değiştirme",
    "finance.read": "Gelir ve ödeme raporlarını görüntüleme",
    "finance.refund": "İade başlatma",
    "licenses.read": "Lisansları görüntüleme",
    "licenses.manage": "Lisans üretme / iptal etme",
    "football.read": "Futbol verisini ve senkronizasyon durumunu görüntüleme",
    "football.manage": "Lig, takım, maç verisini ve veri işlerini yönetme",
    "models.read": "Model, deney ve metrikleri görüntüleme",
    "models.manage": "Model eğitimi, Optuna çalışması, şampiyon modeli değiştirme",
    "predictions.read": "Tahminleri görüntüleme",
    "predictions.manage": "Tahmin yayımlama / geri çekme",
    "coupons.read": "Kuponları görüntüleme",
    "coupons.manage": "Kupon oluşturma ve yayımlama",
    "virtual.read": "Sanal simülasyon hesaplarını görüntüleme",
    "design.read": "Tasarım sistemlerini görüntüleme",
    "design.edit": "Tasarım taslağı düzenleme",
    "design.publish": "Tasarımı yayımlama / geri alma",
    "content.manage": "Site içeriği ve SSS yönetimi",
    "notifications.manage": "Bildirim ve duyuru gönderme",
    "api.manage": "Dış API anahtarları ve kotaları yönetme",
    "settings.read": "Sistem ayarlarını görüntüleme",
    "settings.manage": "Sistem ayarlarını değiştirme",
    "security.read": "Güvenlik merkezi ve oturum olaylarını görüntüleme",
    "logs.read": "Uygulama loglarını görüntüleme",
    "backups.manage": "Yedekleme ve geri yükleme",
    "data.explore": "Data Explorer ile kayıt arama",
    "data.export": "CSV dışa aktarma",
    "system.read": "Sistem sağlığını görüntüleme",
    "flags.manage": "Özellik bayraklarını değiştirme",
}

SENSITIVE: Final[frozenset[str]] = frozenset(
    {
        "users.manage",
        "roles.assign",
        "subscriptions.manage",
        "finance.refund",
        "licenses.manage",
        "models.manage",
        "design.publish",
        "settings.manage",
        "backups.manage",
        "data.export",
        "api.manage",
        "flags.manage",
    }
)

ROLES: Final[dict[str, str]] = {
    "SUPER_ADMIN": "Tüm yetkiler; rol atama ve yedekleme dahil",
    "ADMIN": "Platform yönetimi; rol atama, iade ve yedekleme hariç",
    "SUPPORT": "Kullanıcı desteği",
    "ANALYST": "Model, tahmin ve kupon analizi",
    "FINANCE_MANAGER": "Gelir, abonelik, iade ve lisans",
    "OPERATIONS_MANAGER": "Veri işleri, sistem sağlığı, API ve özellik bayrakları",
    "CONTENT_MANAGER": "İçerik, bildirim ve tasarım taslakları",
}

_ALL = frozenset(PERMISSIONS)

ROLE_PERMISSIONS: Final[dict[str, frozenset[str]]] = {
    "SUPER_ADMIN": _ALL,
    "ADMIN": _ALL - {"roles.assign", "finance.refund", "backups.manage"},
    "SUPPORT": frozenset(
        {
            "users.read",
            "users.manage",
            "subscriptions.read",
            "licenses.read",
            "predictions.read",
            "coupons.read",
            "virtual.read",
        }
    ),
    "ANALYST": frozenset(
        {
            "football.read",
            "models.read",
            "models.manage",
            "predictions.read",
            "predictions.manage",
            "coupons.read",
            "coupons.manage",
            "virtual.read",
            "data.explore",
            "system.read",
        }
    ),
    "FINANCE_MANAGER": frozenset(
        {
            "users.read",
            "subscriptions.read",
            "subscriptions.manage",
            "finance.read",
            "finance.refund",
            "licenses.read",
            "licenses.manage",
            "data.explore",
            "data.export",
        }
    ),
    "OPERATIONS_MANAGER": frozenset(
        {
            "football.read",
            "football.manage",
            "predictions.read",
            "coupons.read",
            "api.manage",
            "settings.read",
            "security.read",
            "logs.read",
            "system.read",
            "flags.manage",
        }
    ),
    "CONTENT_MANAGER": frozenset(
        {
            "football.read",
            "content.manage",
            "notifications.manage",
            "design.read",
            "design.edit",
        }
    ),
}

STAFF_ROLES: Final[frozenset[str]] = frozenset(ROLES)
