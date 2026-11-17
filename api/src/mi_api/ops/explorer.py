"""Data Explorer: yetkili, beyaz listeli kayıt gezgini (kontrolsüz veritabanı erişimi yok).

* Yalnızca burada tanımlı varlıklar ve **açıkça listelenen sütunlar** okunur. Parola özeti, MFA
  sırrı, oturum belirteci, lisans özeti, ödeme ham verisi gibi alanlar listede yoktur.
* Her varlık kendi okuma iznini ister (``data.explore`` + varlığın izni). CSV dışa aktarma ayrıca
  ``data.export`` (hassas: yeniden doğrulama) ister, en fazla 10.000 satırdır ve denetim kaydına
  filtreleriyle yazılır. CSV hücreleri formül enjeksiyonuna karşı temizlenir.
* Arama: varlığın arama sütunlarında büyük/küçük harf duyarsız içerir; filtre: listelenen
  sütunlarda tipine göre doğrulanmış eşitlik; sıralama: listelenen sütunlar; sayfalama.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Select, String, cast, func, or_, select

from mi_api.billing.models import License, Order, PaymentEventRow, Subscription
from mi_api.coupons.models import Coupon
from mi_api.errors import ApiError
from mi_api.football.models import Competition, Fixture, Team
from mi_api.models import AuditLog, User
from mi_api.predictions.models import Prediction
from mi_api.virtual.models import Ticket, VirtualAccount

MAX_EXPORT = 10_000


@dataclass(frozen=True)
class Col:
    key: str
    attr: Any  # InstrumentedAttribute
    kind: str  # text | int | uuid | bool | datetime | enum | float
    label: str
    choices: tuple[str, ...] = ()
    filter: bool = False
    link: str | None = None  # ilişkili varlık (değer o varlığın kimliği)


@dataclass(frozen=True)
class Entity:
    key: str
    label: str
    permission: str
    model: Any
    columns: tuple[Col, ...]
    search: tuple[Any, ...]
    default_sort: str
    related: tuple[tuple[str, str, str], ...] = field(
        default=()
    )  # (varlık, sütun, etiket): bu kaydın id'si ile süz

    def col(self, key: str) -> Col | None:
        return next((c for c in self.columns if c.key == key), None)


def _ent(
    key: str,
    label: str,
    perm: str,
    model: Any,
    cols: list[Col],
    search: list[Any],
    sort: str,
    related: list[tuple[str, str, str]] | None = None,
) -> Entity:
    return Entity(key, label, perm, model, tuple(cols), tuple(search), sort, tuple(related or ()))


ENTITIES: dict[str, Entity] = {
    e.key: e
    for e in [
        _ent(
            "users",
            "Kullanıcılar",
            "users.read",
            User,
            [
                Col("id", User.id, "uuid", "Kimlik", filter=True),
                Col("email", User.email, "text", "E-posta"),
                Col("display_name", User.display_name, "text", "Ad"),
                Col(
                    "status",
                    User.status,
                    "enum",
                    "Durum",
                    ("active", "suspended", "deleted"),
                    filter=True,
                ),
                Col("email_verified_at", User.email_verified_at, "datetime", "E-posta doğrulandı"),
                Col("mfa_enabled_at", User.mfa_enabled_at, "datetime", "MFA açıldı"),
                Col("created_at", User.created_at, "datetime", "Kayıt"),
            ],
            [User.email, User.display_name],
            "created_at",
            [
                ("subscriptions", "user_id", "Abonelikler"),
                ("orders", "user_id", "Siparişler"),
                ("coupons", "user_id", "Kuponlar"),
                ("virtual_accounts", "user_id", "Sanal hesap"),
                ("audit", "actor_id", "Etkinlik"),
            ],
        ),
        _ent(
            "subscriptions",
            "Abonelikler",
            "subscriptions.read",
            Subscription,
            [
                Col("id", Subscription.id, "int", "No", filter=True),
                Col(
                    "user_id", Subscription.user_id, "uuid", "Kullanıcı", filter=True, link="users"
                ),
                Col(
                    "plan_code",
                    Subscription.plan_code,
                    "enum",
                    "Paket",
                    ("PRO", "ELITE"),
                    filter=True,
                ),
                Col(
                    "status",
                    Subscription.status,
                    "enum",
                    "Durum",
                    ("active", "canceled", "refunded", "revoked"),
                    filter=True,
                ),
                Col(
                    "source",
                    Subscription.source,
                    "enum",
                    "Kaynak",
                    ("payment", "license", "admin"),
                    filter=True,
                ),
                Col("started_at", Subscription.started_at, "datetime", "Başlangıç"),
                Col("current_period_end", Subscription.current_period_end, "datetime", "Bitiş"),
                Col(
                    "order_id", Subscription.order_id, "int", "Sipariş", filter=True, link="orders"
                ),
                Col(
                    "license_id",
                    Subscription.license_id,
                    "int",
                    "Lisans",
                    filter=True,
                    link="licenses",
                ),
            ],
            [],
            "started_at",
        ),
        _ent(
            "orders",
            "Siparişler",
            "finance.read",
            Order,
            [
                Col("id", Order.id, "int", "No", filter=True),
                Col("user_id", Order.user_id, "uuid", "Kullanıcı", filter=True, link="users"),
                Col("plan_code", Order.plan_code, "enum", "Paket", ("PRO", "ELITE"), filter=True),
                Col("period", Order.period, "enum", "Dönem", ("monthly", "yearly"), filter=True),
                Col("amount_minor", Order.amount_minor, "int", "Tutar (kuruş)"),
                Col("currency", Order.currency, "text", "Para birimi"),
                Col(
                    "status",
                    Order.status,
                    "enum",
                    "Durum",
                    ("pending", "paid", "failed", "refunded", "review"),
                    filter=True,
                ),
                Col("provider", Order.provider, "text", "Sağlayıcı", filter=True),
                Col("test_mode", Order.test_mode, "bool", "Test", filter=True),
                Col("created_at", Order.created_at, "datetime", "Oluşturma"),
                Col("paid_at", Order.paid_at, "datetime", "Ödeme"),
            ],
            [cast(Order.id, String), cast(Order.public_id, String)],
            "created_at",
            [
                ("payment_events", "order_id", "Ödeme olayları"),
                ("subscriptions", "order_id", "Abonelik"),
            ],
        ),
        _ent(
            "payment_events",
            "Ödeme olayları",
            "finance.read",
            PaymentEventRow,
            [
                Col("id", PaymentEventRow.id, "int", "No"),
                Col("provider", PaymentEventRow.provider, "text", "Sağlayıcı", filter=True),
                Col("event_id", PaymentEventRow.event_id, "text", "Olay kimliği"),
                Col("received_at", PaymentEventRow.received_at, "datetime", "Alındı"),
                Col(
                    "signature_valid",
                    PaymentEventRow.signature_valid,
                    "bool",
                    "İmza geçerli",
                    filter=True,
                ),
                Col("event_type", PaymentEventRow.event_type, "text", "Tür"),
                Col(
                    "order_id",
                    PaymentEventRow.order_id,
                    "int",
                    "Sipariş",
                    filter=True,
                    link="orders",
                ),
                Col("result", PaymentEventRow.result, "text", "Sonuç", filter=True),
            ],
            [PaymentEventRow.event_id],
            "received_at",
        ),
        _ent(
            "licenses",
            "Lisanslar",
            "licenses.read",
            License,
            [
                Col("id", License.id, "int", "No", filter=True),
                Col("key_hint", License.key_hint, "text", "Son 4"),
                Col("plan_code", License.plan_code, "enum", "Paket", ("PRO", "ELITE"), filter=True),
                Col("duration_days", License.duration_days, "int", "Süre (gün)"),
                Col("max_activations", License.max_activations, "int", "Hak"),
                Col("activations_count", License.activations_count, "int", "Kullanım"),
                Col("status", License.status, "enum", "Durum", ("active", "revoked"), filter=True),
                Col("redeem_before", License.redeem_before, "datetime", "Son kullanma"),
                Col("created_at", License.created_at, "datetime", "Üretim"),
            ],
            [License.key_hint, License.note],
            "created_at",
            [("subscriptions", "license_id", "Abonelikler")],
        ),
        _ent(
            "competitions",
            "Ligler",
            "football.read",
            Competition,
            [
                Col("id", Competition.id, "int", "No", filter=True),
                Col("name", Competition.name, "text", "Lig"),
                Col("provider", Competition.provider, "text", "Kaynak", filter=True),
                Col("is_active", Competition.is_active, "bool", "Takipte", filter=True),
            ],
            [Competition.name],
            "name",
        ),
        _ent(
            "teams",
            "Takımlar",
            "football.read",
            Team,
            [
                Col("id", Team.id, "int", "No", filter=True),
                Col("name", Team.name, "text", "Takım"),
                Col("short_name", Team.short_name, "text", "Kısa ad"),
                Col("provider", Team.provider, "text", "Kaynak", filter=True),
            ],
            [Team.name, Team.short_name],
            "name",
            [
                ("fixtures", "home_team_id", "İç saha maçları"),
                ("fixtures", "away_team_id", "Deplasman maçları"),
            ],
        ),
        _ent(
            "fixtures",
            "Maçlar",
            "football.read",
            Fixture,
            [
                Col("id", Fixture.id, "int", "No", filter=True),
                Col("kickoff_at", Fixture.kickoff_at, "datetime", "Başlama"),
                Col(
                    "status",
                    Fixture.status,
                    "enum",
                    "Durum",
                    (
                        "tbd",
                        "scheduled",
                        "live",
                        "halftime",
                        "finished",
                        "postponed",
                        "suspended",
                        "cancelled",
                        "abandoned",
                        "awarded",
                    ),
                    filter=True,
                ),
                Col(
                    "home_team_id",
                    Fixture.home_team_id,
                    "int",
                    "Ev sahibi",
                    filter=True,
                    link="teams",
                ),
                Col(
                    "away_team_id",
                    Fixture.away_team_id,
                    "int",
                    "Deplasman",
                    filter=True,
                    link="teams",
                ),
                Col("home_goals", Fixture.home_goals, "int", "Ev golü"),
                Col("away_goals", Fixture.away_goals, "int", "Dep. golü"),
                Col("provider", Fixture.provider, "text", "Kaynak", filter=True),
            ],
            [cast(Fixture.id, String)],
            "kickoff_at",
            [("predictions", "fixture_id", "Tahminler")],
        ),
        _ent(
            "predictions",
            "Tahminler",
            "predictions.read",
            Prediction,
            [
                Col("id", Prediction.id, "int", "No", filter=True),
                Col(
                    "fixture_id", Prediction.fixture_id, "int", "Maç", filter=True, link="fixtures"
                ),
                Col(
                    "model_version_id",
                    Prediction.model_version_id,
                    "int",
                    "Model sürümü",
                    filter=True,
                ),
                Col("created_at", Prediction.created_at, "datetime", "Üretim"),
                Col(
                    "status",
                    Prediction.status,
                    "enum",
                    "Durum",
                    ("published", "abstained"),
                    filter=True,
                ),
                Col(
                    "reliability",
                    Prediction.reliability,
                    "enum",
                    "Güvenilirlik",
                    ("high", "medium", "low"),
                    filter=True,
                ),
            ],
            [cast(Prediction.id, String)],
            "created_at",
        ),
        _ent(
            "coupons",
            "Kuponlar",
            "coupons.read",
            Coupon,
            [
                Col("id", Coupon.id, "int", "No", filter=True),
                Col("user_id", Coupon.user_id, "uuid", "Kullanıcı", filter=True, link="users"),
                Col("created_at", Coupon.created_at, "datetime", "Oluşturma"),
                Col(
                    "profile",
                    Coupon.profile,
                    "enum",
                    "Profil",
                    ("low", "balanced", "high", "manual"),
                    filter=True,
                ),
                Col("legs_count", Coupon.legs_count, "int", "Seçim"),
                Col("joint_probability", Coupon.joint_probability, "float", "Birleşik olasılık"),
                Col(
                    "status",
                    Coupon.status,
                    "enum",
                    "Durum",
                    ("pending", "won", "lost", "void"),
                    filter=True,
                ),
            ],
            [cast(Coupon.id, String)],
            "created_at",
        ),
        _ent(
            "virtual_accounts",
            "Sanal hesaplar",
            "virtual.read",
            VirtualAccount,
            [
                Col("id", VirtualAccount.id, "int", "No", filter=True),
                Col(
                    "user_id",
                    VirtualAccount.user_id,
                    "uuid",
                    "Kullanıcı",
                    filter=True,
                    link="users",
                ),
                Col("balance_minor", VirtualAccount.balance_minor, "int", "Bakiye (SB kuruş)"),
                Col("reset_count", VirtualAccount.reset_count, "int", "Sıfırlama"),
                Col("created_at", VirtualAccount.created_at, "datetime", "Açılış"),
            ],
            [],
            "created_at",
            [("virtual_tickets", "account_id", "Biletler")],
        ),
        _ent(
            "virtual_tickets",
            "Sanal biletler",
            "virtual.read",
            Ticket,
            [
                Col("id", Ticket.id, "int", "No", filter=True),
                Col(
                    "account_id",
                    Ticket.account_id,
                    "int",
                    "Hesap",
                    filter=True,
                    link="virtual_accounts",
                ),
                Col("coupon_id", Ticket.coupon_id, "int", "Kupon", filter=True, link="coupons"),
                Col("created_at", Ticket.created_at, "datetime", "Açılış"),
                Col("stake_minor", Ticket.stake_minor, "int", "Tutar (SB kuruş)"),
                Col(
                    "odds_source",
                    Ticket.odds_source,
                    "enum",
                    "Oran kaynağı",
                    ("model_fair", "user_entered"),
                    filter=True,
                ),
                Col(
                    "status",
                    Ticket.status,
                    "enum",
                    "Durum",
                    ("pending", "won", "lost", "void"),
                    filter=True,
                ),
                Col("payout_minor", Ticket.payout_minor, "int", "Ödeme (SB kuruş)"),
            ],
            [],
            "created_at",
        ),
        _ent(
            "audit",
            "Denetim kaydı",
            "audit.read",
            AuditLog,
            [
                Col("id", AuditLog.id, "int", "No"),
                Col("occurred_at", AuditLog.occurred_at, "datetime", "Zaman"),
                Col("action", AuditLog.action, "text", "İşlem", filter=True),
                Col(
                    "actor_type",
                    AuditLog.actor_type,
                    "enum",
                    "Aktör türü",
                    ("system", "user", "admin", "webhook", "worker"),
                    filter=True,
                ),
                Col("actor_id", AuditLog.actor_id, "text", "Aktör", filter=True),
                Col("target_type", AuditLog.target_type, "text", "Hedef türü", filter=True),
                Col("target_id", AuditLog.target_id, "text", "Hedef", filter=True),
            ],
            [AuditLog.action, AuditLog.target_id, AuditLog.actor_id],
            "occurred_at",
        ),
    ]
}


def entity_for(key: str, permissions: frozenset[str]) -> Entity:
    e = ENTITIES.get(key)
    if e is None:
        raise ApiError(404, "not_found", "Bilinmeyen varlık")
    if "data.explore" not in permissions or e.permission not in permissions:
        raise ApiError(403, "forbidden", "Bu kayıtları görüntüleme yetkiniz yok")
    return e


_PARSERS: dict[str, Callable[[str], Any]] = {
    "int": int,
    "float": float,
    "uuid": uuid.UUID,
    "bool": lambda v: {"true": True, "false": False, "1": True, "0": False}[v.lower()],
    "text": lambda v: v[:200],
    "datetime": datetime.fromisoformat,
}


def parse(col: Col, raw: str) -> Any:
    if col.kind == "enum":
        if raw not in col.choices:
            raise ApiError(
                422, "invalid_filter", f"{col.label}: izinli değerler {', '.join(col.choices)}"
            )
        return raw
    try:
        return _PARSERS[col.kind](raw)
    except (ValueError, KeyError) as exc:
        raise ApiError(422, "invalid_filter", f"{col.label}: geçersiz değer") from exc


def build(
    e: Entity, *, q: str | None, filters: dict[str, str], sort: str | None, desc: bool
) -> Select[Any]:
    stmt: Select[Any] = select(*[c.attr for c in e.columns])
    for key, raw in filters.items():
        col = e.col(key)
        if col is None or not col.filter:
            raise ApiError(422, "invalid_filter", f"Süzülemeyen alan: {key}")
        stmt = stmt.where(col.attr == parse(col, raw))
    if q:
        term = q.strip()[:100]
        if term and e.search:
            stmt = stmt.where(
                or_(*[func.lower(s).contains(term.lower(), autoescape=True) for s in e.search])
            )
    sort_col = e.col(sort or e.default_sort)
    if sort_col is None:
        raise ApiError(422, "invalid_sort", "Sıralanamayan alan")
    order = sort_col.attr.desc().nulls_last() if desc else sort_col.attr.asc().nulls_last()
    return stmt.order_by(order, e.columns[0].attr.desc())


def jsonable(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


def describe(e: Entity) -> dict[str, Any]:
    return {
        "key": e.key,
        "label": e.label,
        "searchable": bool(e.search),
        "default_sort": e.default_sort,
        "columns": [
            {
                "key": c.key,
                "label": c.label,
                "kind": c.kind,
                "choices": list(c.choices),
                "filter": c.filter,
                "link": c.link,
            }
            for c in e.columns
        ],
        "related": [{"entity": r[0], "column": r[1], "label": r[2]} for r in e.related],
    }


def _safe_cell(v: Any) -> str:
    s = "" if v is None else str(jsonable(v))
    # Elektronik tabloda formül olarak çalışmasın (CSV/formula injection).
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def to_csv(e: Entity, rows: list[Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c.key for c in e.columns])
    for r in rows:
        w.writerow([_safe_cell(v) for v in r])
    return buf.getvalue()
