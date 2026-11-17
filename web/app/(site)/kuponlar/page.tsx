"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Dice5, Info, ListChecks, Save, ShieldAlert, Sparkles, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge, Button, Card, CardHeader, Empty, FormError, Notice, Skeleton, cx } from "@/components/ui";
import { ApiError, api, post } from "@/lib/api";
import { fmtDateTime, fmtTime, pct, sb, shiftDay, trToday } from "@/lib/format";
import { basket, useBasket } from "@/lib/basket";
import { useMe } from "@/lib/hooks";

interface DraftLeg {
  prediction_id: number; fixture_id: number; market: string; pick: string; label: string; probability: number;
  reliability: "high" | "medium" | "low"; home: string; away: string; kickoff_at: string; competition: { name: string };
}
interface Draft {
  profile: "low" | "balanced" | "high" | "manual"; legs: DraftLeg[]; joint_probability: number; one_in: number | null;
  monte_carlo: { runs: { n: number; p: number; std_error: number }[]; converged: boolean; note: string };
  assumption: string; risk: string; odds_note: string; disclaimer: string; params: Record<string, unknown>;
  candidates_considered?: number;
}
interface SavedLeg { position: number; home: string; away: string; kickoff_at: string; label: string; probability: number; result: string; score: { home: number; away: number } | null }
interface Saved { id: number; created_at: string; profile: string; status: string; joint_probability: number; legs: SavedLeg[] }

const PROFILES = [
  { key: "low", label: "Düşük risk", hint: "Seçim olasılığı ≥ %70" },
  { key: "balanced", label: "Dengeli", hint: "Seçim olasılığı %55–78" },
  { key: "high", label: "Yüksek risk", hint: "Seçim olasılığı %38–62" },
] as const;
const MARKETS = [
  { key: "1x2", label: "Maç sonucu" },
  { key: "double_chance", label: "Çifte şans" },
  { key: "total", label: "Alt/Üst" },
  { key: "btts", label: "Karşılıklı gol" },
  { key: "ht_1x2", label: "İlk yarı sonucu" },
  { key: "ht_total", label: "İY alt/üst" },
  { key: "ht_ft", label: "İY/MS" },
];
const REL = { high: { tone: "teal", label: "Yüksek" }, medium: { tone: "gold", label: "Orta" }, low: { tone: "neutral", label: "Düşük" } } as const;
const STATUS = { pending: { tone: "neutral", label: "Bekliyor" }, won: { tone: "teal", label: "Tuttu" }, lost: { tone: "red", label: "Tutmadı" }, void: { tone: "amber", label: "Geçersiz" } } as const;

function VirtualTicket({ couponId, probability }: { couponId: number; probability: number }) {
  const qc = useQueryClient();
  const [source, setSource] = useState<"model_fair" | "user_entered">("model_fair");
  const [odds, setOdds] = useState("");
  const place = useMutation({
    mutationFn: () => post<{ ticket: { stake_minor: number; odds: number } }>("/v1/virtual/tickets", {
      coupon_id: couponId, odds_source: source, ...(source === "user_entered" ? { odds } : {}),
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["virtual"] }),
  });
  if (place.data) {
    return (
      <Notice tone="teal">
        Sanal bilet açıldı: {sb(place.data.ticket.stake_minor)}, oran {place.data.ticket.odds.toFixed(2)}.{" "}
        <Link href="/sanal" className="font-medium text-gold hover:underline">Sanal Portföy</Link>
      </Notice>
    );
  }
  const noAccount = place.error instanceof ApiError && place.error.code === "no_account";
  return (
    <div className="space-y-3 rounded-ctl border border-line bg-bg-elevated p-4">
      <div className="text-[13px] font-medium">Sanal bilet aç <span className="text-muted">(gerçek para değildir)</span></div>
      <div className="flex flex-wrap gap-4 text-[12.5px]">
        <label className="flex items-center gap-2"><input type="radio" checked={source === "model_fair"} onChange={() => setSource("model_fair")} className="accent-[var(--mi-gold)]" />Model adil oranı ({(1 / probability).toFixed(2)})</label>
        <label className="flex items-center gap-2"><input type="radio" checked={source === "user_entered"} onChange={() => setSource("user_entered")} className="accent-[var(--mi-gold)]" />Kendi oranım</label>
        {source === "user_entered" && (
          <input aria-label="Oran" inputMode="decimal" placeholder="ör. 2.40" value={odds} onChange={(e) => setOdds(e.target.value.replace(",", "."))} className="num h-8 w-24 rounded-ctl border border-line-strong bg-bg px-2 text-sm" />
        )}
      </div>
      <p className="text-[11.5px] text-muted">
        {source === "model_fair" ? "Model adil oranı piyasa oranı değildir; model iyi kalibre ise beklenen sanal kâr sıfırdır." : "Girdiğiniz oran doğrulanmaz; EV bu orana göre hesaplanır."} Tutar, Sanal Portföy ayarlarınıza göre sunucuda hesaplanır.
      </p>
      {noAccount ? (
        <Notice tone="amber">Önce <Link href="/sanal" className="font-medium text-gold hover:underline">sanal portföy</Link> açın.</Notice>
      ) : <FormError error={place.error} />}
      <Button size="sm" variant="secondary" loading={place.isPending} disabled={source === "user_entered" && !odds} onClick={() => place.mutate()}>Sanal bilet aç</Button>
    </div>
  );
}

function DraftCard({ d, eyebrow, title, note, onSaved }: { d: Draft; eyebrow: string; title: string; note?: string; onSaved?: () => void }) {
  const qc = useQueryClient();
  const [saved, setSaved] = useState<number | null>(null);
  const save = useMutation({
    mutationFn: () => post<Saved>("/v1/coupons", { profile: d.profile, params: d.params ?? {}, legs: d.legs.map((l) => ({ prediction_id: l.prediction_id, market: l.market, pick: l.pick })) }),
    onSuccess: (c) => { setSaved(c.id); onSaved?.(); qc.invalidateQueries({ queryKey: ["coupons"] }); },
  });
  return (
    <Card className="rise">
      <CardHeader eyebrow={eyebrow} title={title} action={note ? <span className="text-[11.5px] text-muted">{note}</span> : undefined} />
      <ul className="mt-3 divide-y divide-line border-y border-line">
        {d.legs.map((l) => (
          <li key={`${l.prediction_id}-${l.market}-${l.pick}`} className="grid grid-cols-[1fr_auto] items-center gap-3 px-5 py-3">
            <div className="min-w-0">
              <Link href={`/maclar/${l.fixture_id}`} className="block truncate text-[13.5px] font-medium hover:text-gold">{l.home} – {l.away}</Link>
              <div className="text-[11.5px] text-muted">{l.competition.name} · {fmtTime(l.kickoff_at)}</div>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[12.5px] text-text-2">{l.label}</span>
              <Badge tone={REL[l.reliability].tone}>{REL[l.reliability].label}</Badge>
              <span className="num w-12 text-right text-[14px] font-semibold">{pct(l.probability)}</span>
            </div>
          </li>
        ))}
      </ul>
      <div className="grid gap-5 p-5 sm:grid-cols-[auto_1fr]">
        <div className="rounded-ctl border border-line bg-bg-elevated px-5 py-4 text-center">
          <div className="eyebrow mb-1">Birleşik olasılık</div>
          <div className="num text-3xl font-semibold text-gold">{pct(d.joint_probability, 1)}</div>
          {d.one_in && <div className="mt-1 text-[11.5px] text-muted">≈ her {d.one_in.toFixed(1)} kupondan 1</div>}
        </div>
        <div className="space-y-2 text-[12.5px] leading-relaxed text-text-2">
          <p>{d.risk}</p>
          <p className="flex flex-wrap items-center gap-2 text-[11.5px] text-muted">
            {d.monte_carlo.converged && <Badge tone="teal"><CheckCircle2 className="size-3" aria-hidden />Simülasyon doğruladı</Badge>}
            {d.monte_carlo.runs.map((r) => <span key={r.n} className="num">{r.n.toLocaleString("tr-TR")} sim: {pct(r.p, 1)} ± {pct(r.std_error, 2)}</span>)}
          </p>
          <p className="text-[11.5px] text-muted">{d.assumption}</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3 border-t border-line px-5 py-4">
        <Button onClick={() => save.mutate()} loading={save.isPending} disabled={saved !== null}>
          <Save className="size-4" aria-hidden />{saved ? "Kaydedildi" : "Kuponu kaydet"}
        </Button>
        <span className="text-[11.5px] text-muted">Kayıtlı kupon değiştirilemez; sonuçlar maçlar bitince işlenir.</span>
        <FormError error={save.error} />
      </div>
      {saved && <div className="border-t border-line px-5 py-4"><VirtualTicket couponId={saved} probability={d.joint_probability} /></div>}
      <div className="space-y-1.5 border-t border-line bg-bg-elevated px-5 py-3 text-[11.5px] text-muted">
        <p className="flex items-start gap-2"><Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />{d.odds_note}</p>
        <p className="flex items-start gap-2"><Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />{d.disclaimer}</p>
      </div>
    </Card>
  );
}

/** Maç sayfalarından "Kupona ekle" ile seçilenler. Olasılık sunucuda yeniden hesaplanır. */
function Basket() {
  const legs = useBasket();
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  const key = legs.map((l) => `${l.prediction_id}:${l.market}:${l.pick}`).join("|");
  const preview = useQuery({
    queryKey: ["coupon-preview", key],
    queryFn: () => post<Draft>("/v1/coupons/preview", { profile: "manual", legs: legs.map((l) => ({ prediction_id: l.prediction_id, market: l.market, pick: l.pick })) }),
    enabled: ready && legs.length > 0,
    retry: false,
  });
  if (!ready || legs.length === 0) return null;
  return (
    <div className="space-y-3" data-testid="basket">
      <Card>
        <CardHeader eyebrow="Seçimlerim" title={`Kupona eklenenler (${legs.length})`}
          action={<Button size="sm" variant="ghost" onClick={() => basket.clear()}><Trash2 className="size-3.5" aria-hidden />Temizle</Button>} />
        <ul className="mt-3 divide-y divide-line border-t border-line">
          {legs.map((l) => (
            <li key={`${l.prediction_id}-${l.market}-${l.pick}`} className="flex items-center gap-3 px-5 py-2.5 text-[12.5px]">
              <ListChecks className="size-4 shrink-0 text-muted" aria-hidden />
              <Link href={`/maclar/${l.fixture_id}`} className="min-w-0 flex-1 truncate hover:text-gold">{l.match}</Link>
              <span className="text-text-2">{l.label}</span>
              <button type="button" aria-label={`${l.label} kaldır`} onClick={() => basket.remove(l)} className="text-muted hover:text-text"><X className="size-4" aria-hidden /></button>
            </li>
          ))}
        </ul>
        {preview.isLoading && <Skeleton className="m-5 h-16" />}
        {preview.isError && (
          <div className="space-y-2 p-5">
            <FormError error={preview.error} />
            {preview.error instanceof ApiError && ["stale_prediction", "kickoff_passed", "abstained", "market_unavailable"].includes(preview.error.code) && (
              <p className="text-[12px] text-muted">Bu seçimi kaldırıp maç sayfasından yeniden ekleyin.</p>
            )}
          </div>
        )}
      </Card>
      {preview.data && (
        <DraftCard key={key} d={preview.data} eyebrow={`Kendi kuponum · ${preview.data.legs.length} seçim`} title="Seçimlerimin birleşik olasılığı" />
      )}
    </div>
  );
}

function History() {
  const q = useQuery({ queryKey: ["coupons"], queryFn: () => api<{ items: Saved[] }>("/v1/coupons") });
  return (
    <Card>
      <CardHeader eyebrow="Geçmiş" title="Kuponlarım" action={<span className="text-[11.5px] text-muted">Kayıtlar değiştirilemez</span>} />
      <div className="mt-3 divide-y divide-line border-t border-line">
        {q.isLoading ? <Skeleton className="m-5 h-24" /> : !q.data?.items.length ? (
          <Empty title="Henüz kayıtlı kupon yok">Oluşturduğunuz kuponu kaydettiğinizde maç sonuçlarıyla birlikte burada izlenir.</Empty>
        ) : q.data.items.map((c) => (
          <details key={c.id} className="group px-5 py-3.5">
            <summary className="flex cursor-pointer list-none items-center gap-3 text-[13px]">
              <Badge tone={STATUS[c.status as keyof typeof STATUS]?.tone ?? "neutral"}>{STATUS[c.status as keyof typeof STATUS]?.label ?? c.status}</Badge>
              <span className="font-medium">{c.legs.length} seçim</span>
              <span className="num text-text-2">Olasılık {pct(c.joint_probability, 1)}</span>
              <span className="ml-auto text-[11.5px] text-muted">{fmtDateTime(c.created_at)}</span>
            </summary>
            <ul className="mt-3 space-y-1.5">
              {c.legs.map((l) => (
                <li key={l.position} className="flex items-center gap-3 rounded-ctl bg-bg-elevated px-3 py-2 text-[12.5px]">
                  <span className="min-w-0 flex-1 truncate">{l.home} – {l.away}</span>
                  <span className="text-text-2">{l.label}</span>
                  <span className="num w-12 text-right">{pct(l.probability)}</span>
                  {l.score && <span className="num text-muted">{l.score.home}–{l.score.away}</span>}
                  <Badge tone={STATUS[l.result as keyof typeof STATUS]?.tone ?? "neutral"}>{STATUS[l.result as keyof typeof STATUS]?.label ?? l.result}</Badge>
                </li>
              ))}
            </ul>
          </details>
        ))}
      </div>
    </Card>
  );
}

export default function CouponCenter() {
  const { data: me, isLoading } = useMe();
  const today = trToday();
  const [day, setDay] = useState(today);
  const [profile, setProfile] = useState<Draft["profile"]>("balanced");
  const [size, setSize] = useState(3);
  const [markets, setMarkets] = useState<string[]>([]);
  const generate = useMutation({
    mutationFn: () => post<Draft>("/v1/coupons/generate", { date: day, profile, size, ...(markets.length ? { markets } : {}) }),
  });
  const d = generate.data;

  return (
    <div className="py-8">
      <div className="eyebrow mb-2">Kupon Merkezi</div>
      <h1 className="text-[28px] font-semibold tracking-tight">Model tabanlı kupon oluşturucu</h1>
      <p className="mt-2 max-w-2xl text-[13.5px] leading-relaxed text-muted">
        Seçimler yalnızca yayımlanmış ve test edilmiş tahminlerden gelir. Birleşik olasılık; aynı maçtaki seçimler için
        ortak skor dağılımından, farklı maçlar için birlikte hesaplanır ve Monte Carlo simülasyonuyla doğrulanır.
        Sanal analizdir; gerçek bahis yapılmaz.
      </p>

      {isLoading ? <Skeleton className="mt-6 h-40" /> : !me ? (
        <Card className="mt-6"><Empty title="Kupon oluşturmak için giriş yapın" icon={<ShieldAlert className="size-5" aria-hidden />}>
          <Link href="/giris?next=/kuponlar" className="font-medium text-gold hover:underline">Giriş yapın</Link> veya <Link href="/kayit" className="font-medium text-gold hover:underline">ücretsiz hesap açın</Link>.
        </Empty></Card>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[360px_1fr]">
          <Card className="h-fit">
            <CardHeader eyebrow="Ayarlar" title="Kupon profili" />
            <form className="space-y-5 p-5" onSubmit={(e) => { e.preventDefault(); generate.mutate(); }}>
              <fieldset>
                <legend className="mb-2 text-[13px] font-medium text-text-2">Gün</legend>
                <div className="flex gap-2">
                  {[today, shiftDay(today, 1)].map((x, i) => (
                    <button key={x} type="button" aria-pressed={day === x} onClick={() => setDay(x)} className={cx("h-9 flex-1 rounded-ctl text-[12.5px] font-medium", day === x ? "bg-text text-bg" : "border border-line text-text-2")}>
                      {i === 0 ? "Bugün" : "Yarın"}
                    </button>
                  ))}
                </div>
              </fieldset>
              <fieldset>
                <legend className="mb-2 text-[13px] font-medium text-text-2">Risk profili</legend>
                <div className="space-y-2">
                  {PROFILES.map((p) => (
                    <label key={p.key} className={cx("flex cursor-pointer items-center justify-between rounded-ctl border px-3.5 py-2.5 text-[13px]", profile === p.key ? "border-gold/60 bg-gold-soft" : "border-line")}>
                      <span className="flex items-center gap-2.5">
                        <input type="radio" name="profile" value={p.key} checked={profile === p.key} onChange={() => setProfile(p.key)} className="accent-[var(--mi-gold)]" />
                        {p.label}
                      </span>
                      <span className="text-[11.5px] text-muted">{p.hint}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <label className="block">
                <span className="mb-2 block text-[13px] font-medium text-text-2">Maç sayısı</span>
                <select value={size} onChange={(e) => setSize(Number(e.target.value))} className="h-10 w-full rounded-ctl border border-line-strong bg-bg-elevated px-3 text-sm">
                  {[1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n} maç</option>)}
                </select>
              </label>
              <fieldset>
                <legend className="mb-2 text-[13px] font-medium text-text-2">Piyasalar <span className="text-muted">(boş = tümü)</span></legend>
                <div className="flex flex-wrap gap-2">
                  {MARKETS.map((m) => (
                    <button key={m.key} type="button" aria-pressed={markets.includes(m.key)} onClick={() => setMarkets(markets.includes(m.key) ? markets.filter((x) => x !== m.key) : [...markets, m.key])}
                      className={cx("h-8 rounded-full px-3 text-[12px] font-medium", markets.includes(m.key) ? "bg-gold-soft text-gold" : "border border-line text-text-2")}>
                      {m.label}
                    </button>
                  ))}
                </div>
              </fieldset>
              <Button type="submit" className="w-full" loading={generate.isPending}><Sparkles className="size-4" aria-hidden />Kupon oluştur</Button>
            </form>
          </Card>

          <div className="space-y-6">
            <Basket />
            {generate.isError ? (
              <Card><div className="p-5"><FormError error={generate.error} /></div></Card>
            ) : !d ? (
              <Card><Empty title="Profil seçip kupon oluşturun" icon={<Dice5 className="size-5" aria-hidden />}>Model, seçtiğiniz olasılık bandına uyan ve güvenilirliği yeterli maçlardan en olası seçimleri önerir. Kendi seçimlerinizi maç sayfasındaki <strong className="text-text">+</strong> düğmeleriyle de ekleyebilirsiniz.</Empty></Card>
            ) : (
              <DraftCard key={generate.submittedAt} d={d} eyebrow={`${PROFILES.find((p) => p.key === d.profile)?.label} · ${d.legs.length} maç`} title="Önerilen kupon" note={`${d.candidates_considered} uygun maç tarandı`} />
            )}
            <History />
          </div>
        </div>
      )}
    </div>
  );
}
