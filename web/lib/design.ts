// Tasarım sistemleri: API'deki yayımlanmış yapılandırmayı CSS değişkenlerine ve <html> data-*
// özniteliklerine çevirir. Bileşenler yalnızca bu tokenları ve öznitelikleri kullanır.
//
// Güvenlik: yapılandırma sunucuda katı şemayla doğrulanır; burada da her değer yeniden denetlenir
// (yalnızca hex renk, sınırlı sayı, izinli seçenek). Geçmeyen değer CSS'e yazılmaz.

export type Mode = "dark" | "light";
export type Shell = "topbar" | "sidebar" | "terminal" | "masthead";
export type Hero =
  | "signature" | "swiss" | "terminal" | "editorial" | "atelier"
  | "architectural" | "institutional" | "obsidian" | "lab" | "brand";
export type MatchListStyle = "rows" | "cards" | "table";

export interface DesignConfig {
  schema_version: 1;
  name: string;
  tagline: string;
  mode: Mode;
  colors: Record<
    | "bg" | "bg_elevated" | "surface" | "surface_2" | "surface_3" | "line" | "line_strong" | "text"
    | "text_2" | "muted" | "accent" | "accent_text" | "data" | "positive" | "warning" | "negative"
    | "home" | "draw" | "away",
    string
  >;
  typography: { font: string; heading_font: string; mono_font: string; base_size: number; scale: number; heading_weight: number; heading_tracking: number };
  shape: { radius: number; radius_control: number; border_width: number; card: "flat" | "outlined" | "elevated" | "glass" | "notched"; shadow: "none" | "soft" | "deep" | "glow" | "neon" };
  layout: { shell: Shell; sidebar_width: number; page_width: number; gap: number; grid_columns: 12 | 16; density: "compact" | "regular" | "comfortable"; hero: Hero; match_list: MatchListStyle; menu: "pill" | "underline" | "block"; logo: "monogram" | "wordmark" | "terminal" | "serif" | "signature" };
  components: { button: "solid" | "outline" | "soft" | "sharp"; table: "lined" | "zebra" | "boxed"; chart: "line" | "area" | "bars"; chart_stroke: number; chart_grid: boolean };
  motion: { level: "none" | "subtle" | "standard"; duration_ms: number };
  mobile: { nav: "tabs" | "drawer" | "top" };
}

export interface DesignPayload {
  default: string;
  order: string[];
  designs: Record<string, { version: number; config: DesignConfig }>;
}

export const DESIGN_COOKIE = "mi_design";
export const PREVIEW_KEY = "preview";

export const FONT_STACKS: Record<string, string> = {
  inter: "'Inter Variable', ui-sans-serif, system-ui, sans-serif",
  manrope: "'Manrope Variable', ui-sans-serif, system-ui, sans-serif",
  "space-grotesk": "'Space Grotesk Variable', ui-sans-serif, system-ui, sans-serif",
  "ibm-plex-sans": "'IBM Plex Sans Variable', ui-sans-serif, system-ui, sans-serif",
  "dm-sans": "'DM Sans Variable', ui-sans-serif, system-ui, sans-serif",
  fraunces: "'Fraunces Variable', ui-serif, Georgia, serif",
  "source-serif": "'Source Serif 4 Variable', ui-serif, Georgia, serif",
  system: "ui-sans-serif, -apple-system, 'Segoe UI', system-ui, 'Helvetica Neue', Arial, sans-serif",
  "jetbrains-mono": "'JetBrains Mono Variable', ui-monospace, Menlo, Consolas, monospace",
  "ibm-plex-mono": "'IBM Plex Mono', ui-monospace, Menlo, Consolas, monospace",
  "system-mono": "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
};

const HEX = /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/;
const KEY = /^[a-z0-9-]{3,32}$/;
const ENUMS = {
  shell: ["topbar", "sidebar", "terminal", "masthead"],
  card: ["flat", "outlined", "elevated", "glass", "notched"],
  shadow: ["none", "soft", "deep", "glow", "neon"],
  density: ["compact", "regular", "comfortable"],
  menu: ["pill", "underline", "block"],
  button: ["solid", "outline", "soft", "sharp"],
  table: ["lined", "zebra", "boxed"],
  chart: ["line", "area", "bars"],
  motion: ["none", "subtle", "standard"],
  nav: ["tabs", "drawer", "top"],
  mode: ["dark", "light"],
} as const;

const num = (v: unknown, lo: number, hi: number): number | null =>
  typeof v === "number" && Number.isFinite(v) && v >= lo && v <= hi ? v : null;
const pick = <T extends string>(v: unknown, allowed: readonly T[]): T | null =>
  typeof v === "string" && (allowed as readonly string[]).includes(v) ? (v as T) : null;

const SHADOWS = {
  none: "none",
  soft: "0 1px 2px color-mix(in srgb, var(--mi-text) 6%, transparent), 0 8px 24px -16px color-mix(in srgb, var(--mi-text) 22%, transparent)",
  deep: "0 1px 0 rgba(255,255,255,0.04) inset, 0 12px 32px -18px rgba(0,0,0,0.8)",
  glow: "0 0 0 1px color-mix(in srgb, var(--mi-gold) 10%, transparent), 0 18px 48px -24px color-mix(in srgb, var(--mi-gold) 35%, transparent)",
  // Neon: ev (camgöbeği) ve deplasman (pembe) renkleriyle iki tonlu parıltı; metin rengine dokunmaz.
  neon: "0 0 0 1px color-mix(in srgb, var(--mi-away) 18%, transparent), 0 10px 28px -16px color-mix(in srgb, var(--mi-away) 55%, transparent), 0 22px 54px -30px color-mix(in srgb, var(--mi-home) 70%, transparent)",
};

/** Bir tasarımın CSS kuralı. ``selector`` doğrulanmış anahtar veya önizleme anahtarıdır. */
export function designCss(key: string, cfg: DesignConfig): string {
  if (!KEY.test(key)) return "";
  const vars: string[] = [];
  const set = (name: string, value: string | null | undefined) => {
    if (value !== null && value !== undefined) vars.push(`${name}:${value}`);
  };
  const c = cfg.colors ?? ({} as DesignConfig["colors"]);
  const color = (name: string, v: unknown) => set(name, typeof v === "string" && HEX.test(v) ? v : null);
  color("--mi-bg", c.bg);
  color("--mi-bg-elevated", c.bg_elevated);
  color("--mi-surface", c.surface);
  color("--mi-surface-2", c.surface_2);
  color("--mi-surface-3", c.surface_3);
  color("--mi-line", c.line);
  color("--mi-line-strong", c.line_strong);
  color("--mi-text", c.text);
  color("--mi-text-2", c.text_2);
  color("--mi-muted", c.muted);
  color("--mi-gold", c.accent);
  color("--mi-accent-text", c.accent_text);
  color("--mi-cobalt", c.data);
  color("--mi-teal", c.positive);
  color("--mi-amber", c.warning);
  color("--mi-red", c.negative);
  color("--mi-home", c.home);
  color("--mi-draw", c.draw);
  color("--mi-away", c.away);
  const t = cfg.typography ?? ({} as DesignConfig["typography"]);
  set("--mi-font", FONT_STACKS[t.font] ?? null);
  set("--mi-font-heading", FONT_STACKS[t.heading_font] ?? null);
  set("--mi-font-mono", FONT_STACKS[t.mono_font] ?? null);
  const base = num(t.base_size, 12, 17);
  set("--mi-base", base === null ? null : `${base}px`);
  const scale = num(t.scale, 1.1, 1.45);
  set("--mi-scale", scale === null ? null : String(scale));
  const hw = num(t.heading_weight, 300, 800);
  set("--mi-heading-weight", hw === null ? null : String(Math.round(hw / 100) * 100));
  const tr = num(t.heading_tracking, -0.05, 0.05);
  set("--mi-heading-tracking", tr === null ? null : `${tr}em`);
  const s = cfg.shape ?? ({} as DesignConfig["shape"]);
  const r = num(s.radius, 0, 28);
  set("--mi-radius", r === null ? null : `${r}px`);
  const rc = num(s.radius_control, 0, 20);
  set("--mi-radius-sm", rc === null ? null : `${rc}px`);
  const bw = num(s.border_width, 0, 2);
  set("--mi-border", bw === null ? null : `${bw}px`);
  const sh = pick(s.shadow, ENUMS.shadow);
  set("--mi-shadow", sh ? SHADOWS[sh] : null);
  const l = cfg.layout ?? ({} as DesignConfig["layout"]);
  const pw = num(l.page_width, 1024, 1600);
  set("--mi-page", pw === null ? null : `${pw}px`);
  const sw = num(l.sidebar_width, 200, 320);
  set("--mi-sidebar", sw === null ? null : `${sw}px`);
  const gap = num(l.gap, 8, 40);
  set("--mi-gap", gap === null ? null : `${gap}px`);
  set("--mi-cols", l.grid_columns === 12 || l.grid_columns === 16 ? String(l.grid_columns) : null);
  const comp = cfg.components ?? ({} as DesignConfig["components"]);
  const cs = num(comp.chart_stroke, 1, 3);
  set("--mi-chart-stroke", cs === null ? null : String(cs));
  const ms = num(cfg.motion?.duration_ms, 0, 600);
  set("--mi-motion", ms === null ? null : `${ms}ms`);
  const mode = pick(cfg.mode, ENUMS.mode);
  set("color-scheme", mode);
  return `[data-design="${key}"]{${vars.join(";")}}`;
}

/** <html> öznitelikleri: CSS varyantları bunlara bağlanır. */
export function designAttrs(key: string, cfg: DesignConfig | null): Record<string, string> {
  if (!cfg) return { "data-design": "signature-black" };
  const out: Record<string, string> = { "data-design": KEY.test(key) ? key : "signature-black" };
  const add = (name: string, v: string | null) => { if (v) out[name] = v; };
  add("data-mode", pick(cfg.mode, ENUMS.mode));
  add("data-shell", pick(cfg.layout?.shell, ENUMS.shell));
  add("data-card", pick(cfg.shape?.card, ENUMS.card));
  add("data-shadow", pick(cfg.shape?.shadow, ENUMS.shadow));
  add("data-density", pick(cfg.layout?.density, ENUMS.density));
  add("data-menu", pick(cfg.layout?.menu, ENUMS.menu));
  add("data-button", pick(cfg.components?.button, ENUMS.button));
  add("data-table", pick(cfg.components?.table, ENUMS.table));
  add("data-chart", pick(cfg.components?.chart, ENUMS.chart));
  add("data-motion", pick(cfg.motion?.level, ENUMS.motion));
  add("data-mobile-nav", pick(cfg.mobile?.nav, ENUMS.nav));
  return out;
}

export function allDesignsCss(payload: DesignPayload | null): string {
  if (!payload) return "";
  return payload.order.map((k) => (payload.designs[k] ? designCss(k, payload.designs[k].config) : "")).join("\n");
}

export function resolveKey(payload: DesignPayload | null, requested: string | undefined | null): string {
  if (!payload) return "signature-black";
  if (requested && payload.designs[requested]) return requested;
  return payload.designs[payload.default] ? payload.default : payload.order[0] ?? "signature-black";
}
