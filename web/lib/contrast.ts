// WCAG 2.1 kontrast denetimi — api/src/mi_api/design/contrast.py ile aynı kural (sunucu yayında
// zorunlu kılar; burada düzenleyicide anlık uyarı için). Her metin rengi × her yüzey, rozet
// zeminleri (rengin %15'i + yüzey) ve vurgu üzerindeki yazı en az 4,5:1 olmalı.
export const AA = 4.5;
const FOREGROUNDS = ["text", "text_2", "muted", "accent", "positive", "warning", "negative", "data"] as const;
const BACKGROUNDS = ["bg", "bg_elevated", "surface", "surface_2"] as const;
const SOFT = ["accent", "data", "positive", "warning", "negative"] as const;
const LABELS: Record<string, string> = {
  text: "ana metin", text_2: "ikincil metin", muted: "soluk metin", accent: "vurgu", positive: "olumlu", warning: "uyarı",
  negative: "olumsuz", data: "veri", accent_text: "vurgu üzerindeki yazı", bg: "sayfa", bg_elevated: "yükseltilmiş alan",
  surface: "kart", surface_2: "iç kart",
};

function rgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function luminance(hex: string): number {
  const lin = (v: number) => { const c = v / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  const [r, g, b] = rgb(hex);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}
export function ratio(a: string, b: string): number {
  const la = luminance(a), lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}
export function mix(fg: string, base: string, alpha: number): string {
  const f = rgb(fg), b = rgb(base);
  const ch = (x: number, y: number) => Math.round(alpha * x + (1 - alpha) * y).toString(16).padStart(2, "0");
  return `#${ch(f[0], b[0])}${ch(f[1], b[1])}${ch(f[2], b[2])}`;
}

export interface ContrastIssue { foreground: string; background: string; ratio: number; message: string }

const label = (k: string) => LABELS[k] ?? k;

export function contrastIssues(colors: Record<string, string>): ContrastIssue[] {
  const checks: { fg: string; fgColor: string; key: string; bg: string; name: string }[] = [];
  for (const f of FOREGROUNDS) {
    const fc = colors[f];
    if (!fc) continue;
    for (const b of BACKGROUNDS) {
      const bc = colors[b];
      if (bc) checks.push({ fg: f, fgColor: fc, key: b, bg: bc, name: label(b) });
    }
  }
  for (const f of SOFT) {
    const fc = colors[f];
    if (!fc) continue;
    for (const b of BACKGROUNDS) {
      const bc = colors[b];
      if (bc) checks.push({ fg: f, fgColor: fc, key: `${f}_soft@${b}`, bg: mix(fc, bc, 0.15), name: `${label(f)} rozeti zemini (${label(b)} üstünde)` });
    }
  }
  if (colors.accent_text && colors.accent) checks.push({ fg: "accent_text", fgColor: colors.accent_text, key: "accent", bg: colors.accent, name: label("accent") });
  const out: ContrastIssue[] = [];
  for (const c of checks) {
    const r = ratio(c.fgColor, c.bg);
    if (r < AA) out.push({ foreground: c.fg, background: c.key, ratio: Math.round(r * 100) / 100, message: `${label(c.fg)} (${c.fgColor}) / ${c.name} (${c.bg}): ${r.toFixed(2)}:1 — en az ${AA}:1 olmalı` });
  }
  return out;
}
