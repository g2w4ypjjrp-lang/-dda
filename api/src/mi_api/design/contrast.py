"""WCAG 2.1 kontrast denetimi (AA: normal metin için en az 4,5:1).

Arayüzde metin olarak kullanılan her renk (ana/ikincil/soluk metin, vurgu, durum renkleri), metnin
durabileceği her yüzeyde (sayfa, yükseltilmiş alan, kart, iç kart) denetlenir; ayrıca vurgu rengi
üzerindeki yazı (düğmeler). Eşiğin altındaki bir tasarım **yayımlanamaz**; taslakta uyarı olarak
gösterilir. Faz 10 erişilebilirlik taramasında 10 varsayılan tasarımdan 6'sı bu eşiğin altındaydı.

Vurgu tonlu zeminlerde (seçili durum, okunmamış satır) soluk metin kullanılmaz: web'de bu
kapsayıcılar ``tone-highlight`` sınıfı taşır ve içlerindeki soluk metin ikincil metne çıkar
(``web/app/globals.css``); E2E erişilebilirlik testleri (axe) bunu sayfa üzerinde denetler.
"""

from __future__ import annotations

from typing import Any

AA = 4.5
# Rozetler ve vurgulu satırlar: renk, kendi açık tonunun (rengin %15'i + zemin) üzerinde yazılır
# (web: --mi-*-soft = color-mix(renk 13–15%, saydam)). En koyu ton (%15) denetlenir.
SOFT = ("accent", "data", "positive", "warning", "negative")
SOFT_ALPHA = 0.15
FOREGROUNDS = ("text", "text_2", "muted", "accent", "positive", "warning", "negative", "data")
BACKGROUNDS = ("bg", "bg_elevated", "surface", "surface_2")
LABELS = {
    "text": "ana metin",
    "text_2": "ikincil metin",
    "muted": "soluk metin",
    "accent": "vurgu",
    "positive": "olumlu",
    "warning": "uyarı",
    "negative": "olumsuz",
    "data": "veri",
    "accent_text": "vurgu üzerindeki yazı",
    "bg": "sayfa",
    "bg_elevated": "yükseltilmiş alan",
    "surface": "kart",
    "surface_2": "iç kart",
}


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")[:6]  # saydamlık (8 haneli) yok sayılır: düz renk varsayımı
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def mix(fg: str, base: str, alpha: float) -> str:
    """CSS color-mix(in srgb): fg'nin alpha oranı + base."""
    f = [int(fg.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    b = [int(base.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(
        f"{round(alpha * x + (1 - alpha) * y):02x}" for x, y in zip(f, b, strict=True)
    )


def ratio(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def issues(colors: dict[str, Any]) -> list[dict[str, Any]]:
    """Eşiğin altındaki renk çiftleri (boş liste = AA uyumlu)."""
    out: list[dict[str, Any]] = []
    checks: list[tuple[str, str, str, str]] = []  # (ön, arka, arka rengi, arka adı)
    for f in FOREGROUNDS:
        for b in BACKGROUNDS:
            if f in colors and b in colors:
                checks.append((f, b, colors[b], LABELS[b]))
    for f in SOFT:
        for b in BACKGROUNDS:
            if f in colors and b in colors:
                tint = mix(colors[f], colors[b], SOFT_ALPHA)
                checks.append(
                    (f, f"{f}_soft@{b}", tint, f"{LABELS[f]} rozeti zemini ({LABELS[b]} üstünde)")
                )
    if "accent_text" in colors and "accent" in colors:
        checks.append(("accent_text", "accent", colors["accent"], LABELS["accent"]))
    for fg, bg_key, bg, bg_label in checks:
        r = ratio(colors[fg], bg)
        if r < AA:
            out.append(
                {
                    "foreground": fg,
                    "background": bg_key,
                    "ratio": round(r, 2),
                    "message": f"{LABELS[fg]} ({colors[fg]}) / {bg_label} ({bg}): "
                    f"{r:.2f}:1 — en az {AA}:1 olmalı",
                }
            )
    return out
