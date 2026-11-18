"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Columns2, Eye, History, Monitor, Pencil, RotateCcw, Smartphone, Star, Tablet, Upload, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PageTitle, can, useAdmin, useGuard } from "@/components/admin";
import { DesignSwatch } from "@/components/DesignSwatch";
import { Badge, Button, Card, CardHeader, ErrorState, FormError, Input, Notice, Skeleton, cx } from "@/components/ui";
import { contrastIssues } from "@/lib/contrast";
import { api, post, put } from "@/lib/api";
import type { DesignConfig } from "@/lib/design";
import { fmtDateTime, trToday } from "@/lib/format";
import type { Prediction } from "@/lib/types";

interface Version { id: number; design_key: string; version: number; status: "draft" | "published" | "archived" | "discarded"; note: string | null; created_at: string; updated_at: string; published_at: string | null; config: DesignConfig }
interface Item { key: string; published: Version | null; draft: Version | null; versions: number }
interface Listing { default: string; items: Item[] }

const DEVICES = [
  { key: "desktop", label: "Masaüstü", icon: Monitor, width: 1440, height: 900 },
  { key: "tablet", label: "Tablet", icon: Tablet, width: 834, height: 1112 },
  { key: "mobile", label: "Mobil", icon: Smartphone, width: 390, height: 844 },
] as const;
type Device = (typeof DEVICES)[number]["key"];

const STATUS = { draft: { tone: "amber", label: "Taslak" }, published: { tone: "teal", label: "Yayında" }, archived: { tone: "neutral", label: "Arşiv" }, discarded: { tone: "neutral", label: "Atıldı" } } as const;

/** Önizlenebilecek gerçek uygulama sayfaları. Maç sayfaları için bugünün yayımlanmış tahmini olan maç seçilir. */
function usePages() {
  const day = trToday();
  const preds = useQuery({ queryKey: ["predictions", day], queryFn: () => api<{ items: Prediction[] }>(`/v1/predictions?date=${day}`) });
  const match = preds.data?.items.find((p) => p.status === "published")?.fixture_id ?? preds.data?.items[0]?.fixture_id;
  return [
    { key: "home", label: "Ana sayfa", path: "/" },
    { key: "dashboard", label: "Dashboard", path: "/panel" },
    { key: "matches", label: "Maç merkezi", path: "/maclar" },
    { key: "match", label: "Maç detayı", path: match ? `/maclar/${match}` : "/maclar" },
    { key: "ai", label: "AI analizi", path: match ? `/maclar/${match}#analiz` : "/performans" },
    { key: "coupons", label: "Kupon merkezi", path: "/kuponlar" },
    { key: "plans", label: "Abonelik", path: "/paketler" },
    { key: "admin", label: "Admin paneli", path: "/yonetim" },
  ];
}

function previewUrl(path: string, target: { key: string } | { versionId: number }) {
  const [base, hash] = path.split("#");
  const q = "versionId" in target ? `taslak=${target.versionId}` : `tasarim=${target.key}`;
  return `${base}${base!.includes("?") ? "&" : "?"}${q}${hash ? `#${hash}` : ""}`;
}

/** Ölçeklenmiş cihaz çerçevesi: sayfa gerçek genişliğinde işlenir, kutuya sığacak şekilde küçültülür. */
function DeviceFrame({ src, device, title, frameRef, onLoad }: { src: string; device: Device; title: string; frameRef?: React.Ref<HTMLIFrameElement>; onLoad?: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.5);
  const d = DEVICES.find((x) => x.key === device)!;
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setScale(Math.min(1, el.clientWidth / d.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [d.width]);
  return (
    <div ref={box} className="w-full">
      <div className="mx-auto overflow-hidden rounded-[12px] border border-line-strong bg-bg" style={{ width: d.width * scale, height: d.height * scale }}>
        <iframe
          ref={frameRef}
          title={title}
          src={src}
          onLoad={onLoad}
          style={{ width: d.width, height: d.height, transform: `scale(${scale})`, transformOrigin: "0 0", border: 0 }}
        />
      </div>
    </div>
  );
}

function PreviewBar({ pages, page, setPage, device, setDevice }: { pages: ReturnType<typeof usePages>; page: string; setPage: (p: string) => void; device: Device; setDevice: (d: Device) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select aria-label="Önizlenecek sayfa" value={page} onChange={(e) => setPage(e.target.value)} className="h-9 rounded-ctl border border-line-strong bg-bg-elevated px-2 text-[13px]">
        {pages.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
      </select>
      <div className="inline-flex rounded-ctl border border-line p-0.5" role="group" aria-label="Cihaz">
        {DEVICES.map((d) => (
          <button key={d.key} type="button" aria-pressed={device === d.key} title={d.label} onClick={() => setDevice(d.key)}
            className={cx("grid size-8 place-items-center rounded-[6px]", device === d.key ? "bg-surface-3 text-text" : "text-muted hover:text-text")}>
            <d.icon className="size-4" aria-hidden /><span className="sr-only">{d.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/* --- Tam ekran önizleme ve karşılaştırma ---------------------------------------------------------- */

function PreviewModal({ targets, onClose, listing }: { targets: ({ key: string } | { versionId: number })[]; onClose: () => void; listing: Listing }) {
  const pages = usePages();
  const [page, setPage] = useState("home");
  const [device, setDevice] = useState<Device>(targets.length > 1 ? "mobile" : "desktop");
  const path = pages.find((p) => p.key === page)?.path ?? "/";
  const name = (t: { key: string } | { versionId: number }) =>
    "key" in t ? listing.items.find((i) => i.key === t.key)?.published?.config.name ?? t.key : `Sürüm #${t.versionId}`;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div role="dialog" aria-modal="true" aria-label="Tasarım önizlemesi" className="fixed inset-0 z-50 flex flex-col bg-bg">
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2.5">
        <div className="text-[13px] font-semibold">{targets.map(name).join("  ↔  ")}</div>
        <div className="ml-auto"><PreviewBar pages={pages} page={page} setPage={setPage} device={device} setDevice={setDevice} /></div>
        <Button size="sm" variant="ghost" onClick={onClose}><X className="size-4" aria-hidden />Kapat</Button>
      </div>
      <div className={cx("grid flex-1 gap-4 overflow-auto p-4", targets.length > 1 && "md:grid-cols-2")}>
        {targets.map((t, i) => (
          <div key={i} className="min-w-0">
            {targets.length > 1 && <div className="mb-2 text-center text-[12px] text-muted">{name(t)}</div>}
            <DeviceFrame src={previewUrl(path, t)} device={device} title={`${name(t)} önizlemesi`} />
          </div>
        ))}
      </div>
    </div>
  );
}

/* --- Düzenleyici ----------------------------------------------------------------------------------- */

const COLOR_LABELS: Record<keyof DesignConfig["colors"], string> = {
  bg: "Arka plan", bg_elevated: "Arka plan (yükseltilmiş)", surface: "Yüzey", surface_2: "Yüzey 2", surface_3: "Yüzey 3",
  line: "Çizgi", line_strong: "Çizgi (güçlü)", text: "Metin", text_2: "Metin 2", muted: "Soluk metin",
  accent: "Vurgu", accent_text: "Vurgu üzerindeki metin", data: "Veri", positive: "Olumlu", warning: "Uyarı",
  negative: "Olumsuz", home: "Ev sahibi (1)", draw: "Beraberlik (X)", away: "Deplasman (2)",
};
const FONTS = ["inter", "manrope", "space-grotesk", "ibm-plex-sans", "dm-sans", "fraunces", "source-serif", "system"];
const MONOS = ["jetbrains-mono", "ibm-plex-mono", "system-mono"];
const HEX = /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/;

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="grid grid-cols-[1fr_auto] items-center gap-3 py-1 text-[12.5px]"><span className="text-text-2">{label}</span>{children}</label>;
}

function Select<T extends string | number>({ value, options, onChange, label }: { value: T; options: readonly T[]; onChange: (v: T) => void; label: string }) {
  return (
    <select aria-label={label} value={String(value)} onChange={(e) => onChange((typeof value === "number" ? Number(e.target.value) : e.target.value) as T)} className="h-8 w-40 rounded-ctl border border-line-strong bg-bg-elevated px-2 text-[12.5px]">
      {options.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
    </select>
  );
}

function Range({ value, min, max, step = 1, unit = "", onChange, label }: { value: number; min: number; max: number; step?: number; unit?: string; onChange: (v: number) => void; label: string }) {
  return (
    <span className="flex w-40 items-center gap-2">
      <input aria-label={label} type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full accent-[var(--mi-gold)]" />
      <span className="num w-12 text-right text-[11.5px] text-muted">{value}{unit}</span>
    </span>
  );
}

function ColorInput({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <span className="flex w-40 items-center gap-2">
      <input aria-label={`${label} seçici`} type="color" value={value.slice(0, 7)} onChange={(e) => onChange(e.target.value + value.slice(7))} className="size-8 shrink-0 cursor-pointer rounded border border-line bg-transparent" />
      <input aria-label={label} value={text} onChange={(e) => { setText(e.target.value); if (HEX.test(e.target.value)) onChange(e.target.value); }}
        className={cx("num h-8 w-full rounded-ctl border bg-bg-elevated px-2 font-mono text-[11.5px]", HEX.test(text) ? "border-line-strong" : "border-red")} />
    </span>
  );
}

function Editor({ item, onClose }: { item: Item; onClose: () => void }) {
  const me = useAdmin();
  const guard = useGuard();
  const qc = useQueryClient();
  const pages = usePages();
  const [page, setPage] = useState("home");
  const [device, setDevice] = useState<Device>("desktop");
  const [draft, setDraft] = useState<Version | null>(item.draft);
  const [config, setConfig] = useState<DesignConfig | null>(item.draft?.config ?? null);
  const [note, setNote] = useState(item.draft?.note ?? "");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const frame = useRef<HTMLIFrameElement>(null);
  const editable = can(me, "design.edit");
  const refresh = () => qc.invalidateQueries({ queryKey: ["admin", "design"] });

  const create = useMutation({
    mutationFn: () => post<Version>(`/admin/v1/design/${item.key}/drafts`, {}),
    onSuccess: (v) => { setDraft(v); setConfig(v.config); refresh(); },
  });
  const save = useMutation({
    mutationFn: () => put<Version>(`/admin/v1/design/versions/${draft!.id}`, { config: config!, note: note || null }),
    onSuccess: (v) => { setDraft(v); refresh(); },
  });
  const publish = useMutation({
    mutationFn: async () => {
      await put(`/admin/v1/design/versions/${draft!.id}`, { config: config!, note: note || null });
      return guard(() => post<Version>(`/admin/v1/design/versions/${draft!.id}/publish`, { confirm: true, note: note || null }));
    },
    onSuccess: () => { setConfirmOpen(false); refresh(); onClose(); },
  });
  const discard = useMutation({
    mutationFn: () => post(`/admin/v1/design/versions/${draft!.id}/discard`),
    onSuccess: () => { refresh(); onClose(); },
  });

  // Değişiklikler kaydedilmeden önizleme çerçevesine canlı gönderilir (yalnızca aynı köken).
  const pushPreview = useCallback(() => {
    if (config) frame.current?.contentWindow?.postMessage({ type: "mi-design-preview", config }, window.location.origin);
  }, [config]);
  useEffect(() => { const t = setTimeout(pushPreview, 120); return () => clearTimeout(t); }, [pushPreview]);

  const issues = config ? contrastIssues(config.colors as unknown as Record<string, string>) : [];
  const base = item.published?.config;
  const changed = useMemo(() => {
    if (!config || !base) return 0;
    let n = 0;
    for (const sec of ["colors", "typography", "shape", "layout", "components", "motion", "mobile"] as const) {
      const a = base[sec] as Record<string, unknown>, b = config[sec] as Record<string, unknown>;
      for (const k of Object.keys(b)) if (a[k] !== b[k]) n++;
    }
    return n + (config.mode !== base.mode ? 1 : 0);
  }, [config, base]);

  const upd = <S extends keyof DesignConfig>(sec: S, key: string, value: unknown) =>
    setConfig((c) => (c ? { ...c, [sec]: { ...(c[sec] as object), [key]: value } } : c));

  const path = pages.find((p) => p.key === page)?.path ?? "/";
  const src = draft ? previewUrl(path, { versionId: draft.id }) : previewUrl(path, { key: item.key });

  return (
    <div role="dialog" aria-modal="true" aria-label={`${item.published?.config.name ?? item.key} düzenleyici`} className="fixed inset-0 z-50 flex flex-col bg-bg">
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2.5">
        <Pencil className="size-4 text-gold" aria-hidden />
        <div className="text-[13px] font-semibold">{item.published?.config.name ?? item.key}</div>
        {draft && <Badge tone="amber">Taslak v{draft.version}</Badge>}
        {changed > 0 && <span className="text-[12px] text-muted">{changed} değişiklik (yayındakine göre)</span>}
        <div className="ml-auto"><PreviewBar pages={pages} page={page} setPage={setPage} device={device} setDevice={setDevice} /></div>
        <Button size="sm" variant="ghost" onClick={onClose}><X className="size-4" aria-hidden />Kapat</Button>
      </div>
      <div className="grid min-h-0 flex-1 lg:grid-cols-[360px_1fr]">
        <div className="min-h-0 overflow-y-auto border-r border-line p-4">
          {!draft ? (
            <div className="space-y-3">
              <p className="text-[13px] text-text-2">Yayındaki sürüm değiştirilemez. Düzenlemek için yayındaki sürümden bir taslak oluşturun.</p>
              {editable ? <Button onClick={() => create.mutate()} loading={create.isPending}>Taslak oluştur</Button> : <Notice tone="amber">Taslak oluşturma yetkiniz yok (design.edit).</Notice>}
              <FormError error={create.error} />
            </div>
          ) : config && (
            <div className="space-y-5">
              <section>
                <div className="eyebrow mb-2">Genel</div>
                <Field label="Mod"><Select label="Mod" value={config.mode} options={["dark", "light"] as const} onChange={(v) => setConfig({ ...config, mode: v })} /></Field>
                <Input label="Sürüm notu" name="note" value={note} onChange={(e) => setNote(e.target.value)} />
              </section>
              <section>
                <div className="eyebrow mb-2">Renk paleti</div>
                {(Object.keys(COLOR_LABELS) as (keyof DesignConfig["colors"])[]).map((k) => (
                  <Field key={k} label={COLOR_LABELS[k]}><ColorInput label={COLOR_LABELS[k]} value={config.colors[k]} onChange={(v) => upd("colors", k, v)} /></Field>
                ))}
              </section>
              <section>
                <div className="eyebrow mb-2">Tipografi</div>
                <Field label="Metin fontu"><Select label="Metin fontu" value={config.typography.font} options={FONTS} onChange={(v) => upd("typography", "font", v)} /></Field>
                <Field label="Başlık fontu"><Select label="Başlık fontu" value={config.typography.heading_font} options={FONTS} onChange={(v) => upd("typography", "heading_font", v)} /></Field>
                <Field label="Rakam/mono font"><Select label="Mono font" value={config.typography.mono_font} options={MONOS} onChange={(v) => upd("typography", "mono_font", v)} /></Field>
                <Field label="Temel boyut"><Range label="Temel boyut" value={config.typography.base_size} min={12} max={17} unit="px" onChange={(v) => upd("typography", "base_size", v)} /></Field>
                <Field label="Ölçek"><Range label="Ölçek" value={config.typography.scale} min={1.1} max={1.45} step={0.01} onChange={(v) => upd("typography", "scale", v)} /></Field>
                <Field label="Başlık ağırlığı"><Range label="Başlık ağırlığı" value={config.typography.heading_weight} min={300} max={800} step={100} onChange={(v) => upd("typography", "heading_weight", v)} /></Field>
                <Field label="Başlık harf aralığı"><Range label="Başlık harf aralığı" value={config.typography.heading_tracking} min={-0.05} max={0.05} step={0.005} unit="em" onChange={(v) => upd("typography", "heading_tracking", v)} /></Field>
              </section>
              <section>
                <div className="eyebrow mb-2">Kart geometrisi</div>
                <Field label="Kart"><Select label="Kart" value={config.shape.card} options={["flat", "outlined", "elevated", "glass", "notched"] as const} onChange={(v) => upd("shape", "card", v)} /></Field>
                <Field label="Köşe yarıçapı"><Range label="Köşe yarıçapı" value={config.shape.radius} min={0} max={28} unit="px" onChange={(v) => upd("shape", "radius", v)} /></Field>
                <Field label="Kontrol yarıçapı"><Range label="Kontrol yarıçapı" value={config.shape.radius_control} min={0} max={20} unit="px" onChange={(v) => upd("shape", "radius_control", v)} /></Field>
                <Field label="Kenarlık"><Range label="Kenarlık" value={config.shape.border_width} min={0} max={2} unit="px" onChange={(v) => upd("shape", "border_width", v)} /></Field>
                <Field label="Gölge"><Select label="Gölge" value={config.shape.shadow} options={["none", "soft", "deep", "glow"] as const} onChange={(v) => upd("shape", "shadow", v)} /></Field>
              </section>
              <section>
                <div className="eyebrow mb-2">Yerleşim</div>
                <Field label="Menü / kabuk"><Select label="Kabuk" value={config.layout.shell} options={["topbar", "sidebar", "terminal", "masthead"] as const} onChange={(v) => upd("layout", "shell", v)} /></Field>
                <Field label="Menü stili"><Select label="Menü stili" value={config.layout.menu} options={["pill", "underline", "block"] as const} onChange={(v) => upd("layout", "menu", v)} /></Field>
                <Field label="Kenar çubuğu genişliği"><Range label="Kenar çubuğu genişliği" value={config.layout.sidebar_width} min={200} max={320} unit="px" onChange={(v) => upd("layout", "sidebar_width", v)} /></Field>
                <Field label="Sayfa genişliği"><Range label="Sayfa genişliği" value={config.layout.page_width} min={1024} max={1600} step={8} unit="px" onChange={(v) => upd("layout", "page_width", v)} /></Field>
                <Field label="Izgara aralığı"><Range label="Izgara aralığı" value={config.layout.gap} min={8} max={40} unit="px" onChange={(v) => upd("layout", "gap", v)} /></Field>
                <Field label="Izgara sütunu"><Select label="Izgara sütunu" value={config.layout.grid_columns} options={[12, 16] as const} onChange={(v) => upd("layout", "grid_columns", v)} /></Field>
                <Field label="Veri yoğunluğu"><Select label="Veri yoğunluğu" value={config.layout.density} options={["compact", "regular", "comfortable"] as const} onChange={(v) => upd("layout", "density", v)} /></Field>
                <Field label="Ana sayfa kompozisyonu"><Select label="Ana sayfa" value={config.layout.hero} options={["signature", "swiss", "terminal", "editorial", "atelier", "architectural", "institutional", "obsidian", "lab", "brand"] as const} onChange={(v) => upd("layout", "hero", v)} /></Field>
                <Field label="Maç listesi"><Select label="Maç listesi" value={config.layout.match_list} options={["rows", "cards", "table"] as const} onChange={(v) => upd("layout", "match_list", v)} /></Field>
                <Field label="Logo"><Select label="Logo" value={config.layout.logo} options={["monogram", "wordmark", "terminal", "serif", "signature"] as const} onChange={(v) => upd("layout", "logo", v)} /></Field>
              </section>
              <section>
                <div className="eyebrow mb-2">Bileşenler</div>
                <Field label="Butonlar"><Select label="Butonlar" value={config.components.button} options={["solid", "outline", "soft", "sharp"] as const} onChange={(v) => upd("components", "button", v)} /></Field>
                <Field label="Tablolar"><Select label="Tablolar" value={config.components.table} options={["lined", "zebra", "boxed"] as const} onChange={(v) => upd("components", "table", v)} /></Field>
                <Field label="Grafik stili"><Select label="Grafik stili" value={config.components.chart} options={["line", "area", "bars"] as const} onChange={(v) => upd("components", "chart", v)} /></Field>
                <Field label="Grafik çizgi kalınlığı"><Range label="Grafik çizgi kalınlığı" value={config.components.chart_stroke} min={1} max={3} step={0.25} onChange={(v) => upd("components", "chart_stroke", v)} /></Field>
                <Field label="Grafik ızgarası"><input aria-label="Grafik ızgarası" type="checkbox" checked={config.components.chart_grid} onChange={(e) => upd("components", "chart_grid", e.target.checked)} className="accent-[var(--mi-gold)]" /></Field>
              </section>
              <section>
                <div className="eyebrow mb-2">Animasyon ve mobil</div>
                <Field label="Animasyon"><Select label="Animasyon" value={config.motion.level} options={["none", "subtle", "standard"] as const} onChange={(v) => upd("motion", "level", v)} /></Field>
                <Field label="Süre"><Range label="Animasyon süresi" value={config.motion.duration_ms} min={0} max={600} step={20} unit="ms" onChange={(v) => upd("motion", "duration_ms", v)} /></Field>
                <Field label="Mobil navigasyon"><Select label="Mobil navigasyon" value={config.mobile.nav} options={["tabs", "drawer", "top"] as const} onChange={(v) => upd("mobile", "nav", v)} /></Field>
              </section>
              <div className="sticky bottom-0 -mx-4 space-y-2 border-t border-line bg-bg p-4">
                {issues.length > 0 && (
                  <div role="alert" data-testid="contrast-issues" className="max-h-32 overflow-y-auto rounded-ctl border border-red/40 bg-red-soft p-2 text-[11.5px] text-text">
                    <div className="font-semibold">Erişilebilirlik: {issues.length} renk çifti WCAG AA kontrastının altında; bu hâliyle yayımlanamaz.</div>
                    <ul className="mt-1 list-disc pl-4">{issues.slice(0, 6).map((i) => <li key={`${i.foreground}-${i.background}`}>{i.message}</li>)}</ul>
                  </div>
                )}
                <FormError error={save.error ?? publish.error ?? discard.error} />
                {save.isSuccess && !save.isPending && <p className="text-[12px] text-teal">Taslak kaydedildi.</p>}
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="secondary" disabled={!editable} loading={save.isPending} onClick={() => save.mutate()}>Taslağı kaydet</Button>
                  {can(me, "design.publish") && <Button size="sm" disabled={issues.length > 0} onClick={() => setConfirmOpen(true)}><Upload className="size-4" aria-hidden />Yayınla</Button>}
                  <Button size="sm" variant="ghost" disabled={!editable} loading={discard.isPending} onClick={() => discard.mutate()}>Taslağı at</Button>
                </div>
                <p className="text-[11px] text-muted">Önizleme değişiklikleri anında gösterir; kaydedilmeden yayına çıkmaz.</p>
              </div>
            </div>
          )}
        </div>
        <div className="min-h-0 overflow-auto bg-bg-elevated p-4">
          <DeviceFrame frameRef={frame} src={src} device={device} title="Canlı önizleme" onLoad={() => setTimeout(pushPreview, 600)} />
        </div>
      </div>
      {confirmOpen && config && (
        <div role="dialog" aria-modal="true" aria-labelledby="publish-title" className="fixed inset-0 z-[60] grid place-items-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-card border border-line-strong bg-surface p-6 shadow-card">
            <h2 id="publish-title" className="text-lg font-semibold">Yayınlamayı onaylayın</h2>
            <p className="mt-2 text-[13px] text-text-2">
              <strong>{config.name}</strong> taslak v{draft?.version} yayına alınacak; bu tasarımı kullanan tüm sayfalar ve kullanıcılar yeni sürümü görecek.
              Şu anki sürüm arşive alınır ve gerektiğinde geri dönülebilir. Yayın sonrası sürüm değiştirilemez.
            </p>
            <p className="mt-2 text-[12px] text-muted">{changed} değişiklik · Kritik işlem: parola ve doğrulama kodu istenebilir.</p>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setConfirmOpen(false)}>Vazgeç</Button>
              <Button loading={publish.isPending} onClick={() => publish.mutate()}>Onaylıyorum, yayınla</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* --- Sürüm geçmişi -------------------------------------------------------------------------------- */

function HistoryPanel({ item, onPreview, onClose }: { item: Item; onPreview: (versionId: number) => void; onClose: () => void }) {
  const me = useAdmin();
  const guard = useGuard();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "design", "history", item.key], queryFn: () => api<{ items: Version[] }>(`/admin/v1/design/${item.key}/versions`) });
  const rollback = useMutation({
    mutationFn: (id: number) => guard(() => post<Version>(`/admin/v1/design/versions/${id}/rollback`, { confirm: true })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "design"] }),
  });
  return (
    <Card className="mt-4">
      <CardHeader eyebrow="Sürüm geçmişi" title={item.published?.config.name ?? item.key} action={<Button size="sm" variant="ghost" onClick={onClose}><X className="size-4" aria-hidden />Kapat</Button>} />
      <ul className="divide-y divide-line border-t border-line">
        {q.isLoading && <Skeleton className="m-4 h-16" />}
        {q.data?.items.map((v) => (
          <li key={v.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-[12.5px]">
            <span className="num w-10 font-semibold">v{v.version}</span>
            <Badge tone={STATUS[v.status].tone}>{STATUS[v.status].label}</Badge>
            <span className="min-w-0 flex-1 truncate text-text-2">{v.note ?? "—"}</span>
            <span className="text-muted">{fmtDateTime(v.published_at ?? v.updated_at)}</span>
            <Button size="sm" variant="ghost" onClick={() => onPreview(v.id)}><Eye className="size-3.5" aria-hidden />Önizle</Button>
            {v.status === "archived" && can(me, "design.publish") && (
              <Button size="sm" variant="secondary" loading={rollback.isPending && rollback.variables === v.id}
                onClick={() => { if (window.confirm(`v${v.version} yapılandırması yeni sürüm olarak yayımlansın mı?`)) rollback.mutate(v.id); }}>
                <RotateCcw className="size-3.5" aria-hidden />Bu sürüme dön
              </Button>
            )}
          </li>
        ))}
      </ul>
      <div className="px-5 pb-4"><FormError error={rollback.error} /></div>
    </Card>
  );
}

/* --- Galeri --------------------------------------------------------------------------------------- */

export default function DesignStudio() {
  const me = useAdmin();
  const guard = useGuard();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "design"], queryFn: () => api<Listing>("/admin/v1/design") });
  const [preview, setPreview] = useState<({ key: string } | { versionId: number })[] | null>(null);
  const [compare, setCompare] = useState<string[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [history, setHistory] = useState<string | null>(null);
  const setDefault = useMutation({
    mutationFn: (key: string) => guard(() => put("/admin/v1/design/default", { design_key: key, confirm: true })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "design"] }),
  });

  if (q.isLoading) return <><PageTitle eyebrow="Tasarım" title="Design Studio" /><Skeleton className="h-96" /></>;
  if (q.error || !q.data) return <><PageTitle eyebrow="Tasarım" title="Design Studio" /><Card><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card></>;
  const listing = q.data;
  const editItem = listing.items.find((i) => i.key === editing);
  const historyItem = listing.items.find((i) => i.key === history);

  return (
    <>
      <PageTitle eyebrow="Tasarım" title="Design Studio">
        <div className="flex items-center gap-2">
          {compare.length > 0 && <span className="text-[12px] text-muted">{compare.length}/2 seçildi</span>}
          <Button size="sm" variant="secondary" disabled={compare.length !== 2} onClick={() => setPreview(compare.map((key) => ({ key })))}>
            <Columns2 className="size-4" aria-hidden />Karşılaştır
          </Button>
        </div>
      </PageTitle>
      <p className="-mt-3 mb-5 max-w-3xl text-[13px] text-muted">
        On tasarım gerçek uygulama bileşenleriyle çalışır: önizlemeler canlı sayfalardır. Yayındaki sürüm değiştirilemez; düzenleme taslakta yapılır,
        onayla yayımlanır ve sürüm geçmişinden geri alınabilir. Kullanıcılar Panelim → Görünüm'den tasarım seçebilir; seçmeyenler site varsayılanını görür.
      </p>
      <FormError error={setDefault.error} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        {listing.items.map((item) => {
          const cfg = item.published?.config;
          if (!cfg) return null;
          const isDefault = listing.default === item.key;
          return (
            <Card key={item.key} className="flex flex-col p-3" as="article">
              <DesignSwatch designKey={item.key} config={cfg} />
              <div className="flex flex-1 flex-col gap-2 px-1 pt-3">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-[14px] font-semibold">{cfg.name}</h3>
                  <label className="flex items-center gap-1 text-[11px] text-muted" title="Karşılaştırmaya ekle">
                    <input type="checkbox" className="accent-[var(--mi-gold)]" checked={compare.includes(item.key)} disabled={!compare.includes(item.key) && compare.length >= 2}
                      onChange={(e) => setCompare(e.target.checked ? [...compare, item.key] : compare.filter((k) => k !== item.key))} aria-label={`${cfg.name} karşılaştırmaya ekle`} />
                    Karşılaştır
                  </label>
                </div>
                <p className="text-[12px] leading-relaxed text-muted">{cfg.tagline}</p>
                <div className="flex flex-wrap gap-1.5">
                  {isDefault && <Badge tone="gold"><Star className="size-3" aria-hidden />Varsayılan</Badge>}
                  <Badge tone="teal">v{item.published!.version} yayında</Badge>
                  {item.draft && <Badge tone="amber">Taslak v{item.draft.version}</Badge>}
                  <Badge>{cfg.layout.shell} · {cfg.layout.match_list}</Badge>
                </div>
                <div className="mt-auto flex flex-wrap gap-1.5 pt-2">
                  <Button size="sm" variant="secondary" onClick={() => setPreview([{ key: item.key }])}><Eye className="size-3.5" aria-hidden />Önizle</Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(item.key)}><Pencil className="size-3.5" aria-hidden />Düzenle</Button>
                  <Button size="sm" variant="ghost" onClick={() => setHistory(item.key)}><History className="size-3.5" aria-hidden />Geçmiş</Button>
                  {!isDefault && can(me, "design.publish") && (
                    <Button size="sm" variant="ghost" loading={setDefault.isPending && setDefault.variables === item.key}
                      onClick={() => { if (window.confirm(`${cfg.name} site varsayılanı yapılsın mı? Tasarım seçmemiş tüm ziyaretçiler bunu görecek.`)) setDefault.mutate(item.key); }}>
                      <Star className="size-3.5" aria-hidden />Varsayılan yap
                    </Button>
                  )}
                </div>
              </div>
            </Card>
          );
        })}
      </div>
      {historyItem && <HistoryPanel item={historyItem} onPreview={(id) => setPreview([{ versionId: id }])} onClose={() => setHistory(null)} />}
      {preview && <PreviewModal targets={preview} listing={listing} onClose={() => setPreview(null)} />}
      {editItem && <Editor key={editItem.key} item={editItem} onClose={() => setEditing(null)} />}
    </>
  );
}
