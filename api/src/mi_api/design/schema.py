"""Tasarım yapılandırması şeması.

Yapılandırma sayfa CSS'ine (CSS değişkenleri ve ``data-*`` öznitelikleri) dönüştürülür. Bu yüzden
**yalnızca** şu değerler kabul edilir: ``#rrggbb``/``#rrggbbaa`` renkler, sınırlı sayılar ve izinli
seçenekler. Serbest metin (isim, açıklama) CSS'e hiç yazılmaz. Böylece Design Studio'dan CSS
enjeksiyonu yapılamaz.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Hex = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")]
Font = Literal[
    "inter", "manrope", "space-grotesk", "ibm-plex-sans", "dm-sans", "fraunces", "source-serif",
    "system",
]  # fmt: skip
Mono = Literal["jetbrains-mono", "ibm-plex-mono", "system-mono"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Colors(Strict):
    bg: Hex
    bg_elevated: Hex
    surface: Hex
    surface_2: Hex
    surface_3: Hex
    line: Hex
    line_strong: Hex
    text: Hex
    text_2: Hex
    muted: Hex
    accent: Hex
    accent_text: Hex  # vurgu rengi üzerindeki yazı
    data: Hex
    positive: Hex
    warning: Hex
    negative: Hex
    home: Hex
    draw: Hex
    away: Hex


class Typography(Strict):
    font: Font
    heading_font: Font
    mono_font: Mono
    base_size: int = Field(ge=12, le=17)
    scale: float = Field(ge=1.1, le=1.45)
    heading_weight: int = Field(ge=300, le=800, multiple_of=100)
    heading_tracking: float = Field(ge=-0.05, le=0.05)  # em


class Shape(Strict):
    radius: int = Field(ge=0, le=28)
    radius_control: int = Field(ge=0, le=20)
    border_width: int = Field(ge=0, le=2)
    card: Literal["flat", "outlined", "elevated", "glass", "notched"]
    shadow: Literal["none", "soft", "deep", "glow", "neon"]  # neon: ev/deplasman renkleriyle parıltı


class Layout(Strict):
    shell: Literal["topbar", "sidebar", "terminal", "masthead"]
    sidebar_width: int = Field(ge=200, le=320)
    page_width: int = Field(ge=1024, le=1600)
    gap: int = Field(ge=8, le=40)
    grid_columns: Literal[12, 16]
    density: Literal["compact", "regular", "comfortable"]
    hero: Literal[
        "signature", "swiss", "terminal", "editorial", "atelier", "architectural",
        "institutional", "obsidian", "lab", "brand",
    ]  # fmt: skip
    match_list: Literal["rows", "cards", "table"]
    menu: Literal["pill", "underline", "block"]
    logo: Literal["monogram", "wordmark", "terminal", "serif", "signature"]


class Components(Strict):
    button: Literal["solid", "outline", "soft", "sharp"]
    table: Literal["lined", "zebra", "boxed"]
    chart: Literal["line", "area", "bars"]
    chart_stroke: float = Field(ge=1, le=3)
    chart_grid: bool


class Motion(Strict):
    level: Literal["none", "subtle", "standard"]
    duration_ms: int = Field(ge=0, le=600)


class Mobile(Strict):
    nav: Literal["tabs", "drawer", "top"]


class DesignConfig(Strict):
    """Bir tasarım sisteminin tam yapılandırması (sürümlenir)."""

    schema_version: Literal[1] = 1
    name: str = Field(min_length=2, max_length=48)
    tagline: str = Field(max_length=160)
    mode: Literal["dark", "light"]
    colors: Colors
    typography: Typography
    shape: Shape
    layout: Layout
    components: Components
    motion: Motion
    mobile: Mobile
