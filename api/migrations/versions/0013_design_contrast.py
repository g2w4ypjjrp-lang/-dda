"""Erişilebilirlik: varsayılan tasarımlarda WCAG AA kontrast düzeltmesi.

Faz 10 axe taramasında 10 tasarımdan 6'sında soluk metin 4,5:1 eşiğinin altındaydı; genişletilmiş
denetim (her metin rengi × her yüzey + rozet zeminleri) 9 tasarımda düzeltme gerektirdi.
Yayımlanmış sürüm değiştirilemediği için düzeltme **yeni sürüm** olarak yayımlanır; eski sürüm arşivde kalır. Yalnızca hâlâ eski varsayılan değeri taşıyan renkler
değiştirilir (yönetici bir rengi kendisi değiştirdiyse ona dokunulmaz).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-18
"""

import json

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

# tasarım → renk → (eski, yeni). Değerler sabittir (geçiş, uygulama kodundan bağımsız kalsın).
FIXES: dict[str, dict[str, tuple[str, str]]] = {
    "signature-black": {"data": ("#5b84ff", "#6a8fff"), "negative": ("#e2645a", "#e57269")},
    "swiss-intelligence": {"muted": ("#77736c", "#6e6a64"), "accent": ("#d52b1e", "#b22419"), "positive": ("#1d7a52", "#196b48"), "warning": ("#b86e00", "#895100"), "negative": ("#c0362c", "#aa3027")},
    "quantum-terminal": {"muted": ("#6c7a74", "#76857e")},
    "editorial-sports": {"muted": ("#7c7168", "#726860"), "accent": ("#b4232a", "#b12229"), "positive": ("#2f7a4f", "#296a45"), "warning": ("#b06d12", "#86520d"), "negative": ("#b4232a", "#b12229")},
    "ai-atelier": {"muted": ("#7f81a3", "#8587a7")},
    "architectural-luxury": {"muted": ("#857e71", "#696359"), "accent": ("#8a6d3b", "#6b542d"), "positive": ("#3d6b4f", "#376047"), "warning": ("#a0701d", "#745115"), "negative": ("#9e3b2f", "#95382c")},
    "institutional-blue": {"muted": ("#6b7a90", "#5e6b7e"), "data": ("#2e6bd1", "#275ab1"), "positive": ("#1f8a5b", "#186a46"), "warning": ("#b7791f", "#805415"), "negative": ("#c2413a", "#a43731")},
    "future-sports-lab": {"muted": ("#76889a", "#7b8c9e"), "negative": ("#ff5f6d", "#ff6472")},
    "mi-signature": {"muted": ("#6f7c76", "#5e6964"), "accent": ("#0e7a5f", "#0b6750"), "data": ("#2753c7", "#2651c3"), "positive": ("#0e7a5f", "#0b6750"), "warning": ("#b8741a", "#805012"), "negative": ("#b33a2e", "#a13429")},
}  # fmt: skip

NOTE = "Erişilebilirlik: WCAG AA renk kontrastı düzeltmesi (geçiş 0013)"


def upgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    for key, fixes in FIXES.items():
        row = raw.execute(
            "SELECT id, version, config FROM design_versions WHERE design_key = %s AND status = 'published'",
            (key,),
        ).fetchone()
        if row is None:
            continue
        vid, _, config = row
        colors = dict(config.get("colors", {}))
        changed = False
        for name, (old, new) in fixes.items():
            if str(colors.get(name, "")).lower() == old:
                colors[name] = new
                changed = True
        if not changed:
            continue
        last = raw.execute("SELECT max(version) FROM design_versions WHERE design_key = %s", (key,)).fetchone()
        raw.execute("UPDATE design_versions SET status = 'archived' WHERE id = %s", (vid,))
        raw.execute(
            "INSERT INTO design_versions (design_key, version, status, config, note, based_on, published_at)"
            " VALUES (%s, %s, 'published', %s, %s, %s, now())",
            (key, int(last[0]) + 1, json.dumps({**config, "colors": colors}), NOTE, vid),
        )


def downgrade() -> None:
    raise RuntimeError("Tasarım sürüm geçmişi geri alınamaz; yedekten geri yükleyin")
