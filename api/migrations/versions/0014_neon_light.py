"""Açık neon tasarım ("Neon Light") ve varsayılan tasarım değişikliği.

Kullanıcı kararı (2026-11): site açık zeminli ve neon vurgulu olsun. Yeni tasarım yayımlanmış v1
olarak eklenir ve **yalnızca** varsayılan tasarım hâlâ ilk kurulumdaki değerse (``signature-black``,
yani yönetici panelden değiştirmediyse) varsayılan yapılır. Diğer tasarımlar ve kullanıcıların
kendi seçtiği tasarım korunur. Renkler WCAG AA kontrast kapısından geçer (``design/contrast.py``).
Yapılandırma burada sabittir; geçiş uygulama kodundan bağımsız kalır.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-19
"""

import json

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

KEY = "neon-light"
CONFIG = {
    "schema_version": 1,
    "name": "Neon Light",
    "tagline": "Açık zemin, neon pembe ve camgöbeği parıltı; sade ve okunaklı.",
    "mode": "light",
    "colors": {
        "bg": "#f5f6fc", "bg_elevated": "#f1f3fb", "surface": "#ffffff", "surface_2": "#f4f5fc",
        "surface_3": "#e6e9f7", "line": "#1a1f4a17", "line_strong": "#1a1f4a2e", "text": "#0c0f2e",
        "text_2": "#33385e", "muted": "#575c80", "accent": "#a00d8e", "accent_text": "#ffffff",
        "data": "#0058b8", "positive": "#006a46", "warning": "#8a5200", "negative": "#b01237",
        "home": "#00b8f0", "draw": "#9aa0bf", "away": "#ff2bd6",
    },
    "typography": {
        "font": "inter", "heading_font": "space-grotesk", "mono_font": "jetbrains-mono",
        "base_size": 15, "scale": 1.25, "heading_weight": 700, "heading_tracking": -0.02,
    },
    "shape": {"radius": 18, "radius_control": 12, "border_width": 1, "card": "elevated", "shadow": "neon"},
    "layout": {
        "shell": "topbar", "sidebar_width": 248, "page_width": 1200, "gap": 24, "grid_columns": 12,
        "density": "comfortable", "hero": "signature", "match_list": "cards", "menu": "pill",
        "logo": "monogram",
    },
    "components": {"button": "solid", "table": "lined", "chart": "area", "chart_stroke": 2.0, "chart_grid": True},
    "motion": {"level": "standard", "duration_ms": 360},
    "mobile": {"nav": "tabs"},
}  # fmt: skip


def upgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    exists = raw.execute("SELECT 1 FROM design_versions WHERE design_key = %s", (KEY,)).fetchone()
    if exists is None:  # yeni kurulumda 0008 zaten ekler
        raw.execute(
            "INSERT INTO design_versions (design_key, version, status, config, note, published_at)"
            " VALUES (%s, 1, 'published', %s, 'İlk sürüm (geçiş 0014)', now())",
            (KEY, json.dumps(CONFIG)),
        )
    raw.execute(
        "UPDATE design_settings SET default_design = %s, updated_at = now()"
        " WHERE id = 1 AND default_design = 'signature-black'",
        (KEY,),
    )


def downgrade() -> None:
    raise RuntimeError("Tasarım sürüm geçmişi geri alınamaz; yedekten geri yükleyin")
