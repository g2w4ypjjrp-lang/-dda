"use client";

import { AlertCircle, BadgeCheck, Check, Clock3, Database, Info, Layers, Lock as LockIcon, Plus, Sigma } from "lucide-react";
import Link from "next/link";

import { fmtDateTime, pct } from "@/lib/format";
import { basket, useBasket, type BasketLeg } from "@/lib/basket";
import type { FirstHalf, Lock, Prediction } from "@/lib/types";
import { Badge, Card, CardHeader, Empty, ProbBar, cx } from "./ui";

const COMPONENT_LABELS: Record<string, string> = {
  dixon_coles: "Dixon-Coles",
  poisson: "Poisson",
  elo_logit: "Elo",
  logistic: "Lojistik regresyon",
  gbm: "LightGBM",
};

function Metric({ icon: Icon, label, value, tone, hint }: { icon: typeof Info; label: string; value: string; tone?: "teal" | "gold" | "amber" | "neutral"; hint?: string }) {
  const colors = { teal: "text-teal", gold: "text-gold", amber: "text-amber", neutral: "text-text" };
  return (
    <div className="rounded-ctl border border-line bg-bg-elevated p-3.5">
      <div className="flex items-center gap-1.5 text-[11.5px] text-muted">
        <Icon className="size-3.5" aria-hidden /> {label}
      </div>
      <div className={cx("mt-1.5 text-[15px] font-semibold", colors[tone ?? "neutral"])}>{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-muted">{hint}</div>}
    </div>
  );
}

type Add = ((market: string, pick: string, label: string) => Omit<BasketLeg, "match" | "kickoff_at"> & { match: string; kickoff_at: string }) | null;

/** "Kupona ekle" düğmesi: sepete ekler/çıkarır. Olasılık sunucuda yeniden hesaplanır. */
function AddChip({ add, market, pick, label }: { add: Add; market: string; pick: string; label: string }) {
  useBasket(); // sepet değişince yeniden çiz
  if (!add) return null;
  const leg = add(market, pick, label);
  const on = basket.has(leg);
  return (
    <button
      type="button"
      onClick={() => basket.toggle(leg)}
      aria-pressed={on}
      aria-label={on ? `${label} kupondan çıkar` : `${label} kupona ekle`}
      title={on ? "Kupondan çıkar" : "Kupona ekle"}
      className={cx("grid size-6 shrink-0 place-items-center rounded-full border text-[11px]", on ? "border-gold/60 bg-gold-soft text-gold" : "border-line text-muted hover:border-line-strong hover:text-text")}
    >
      {on ? <Check className="size-3.5" aria-hidden /> : <Plus className="size-3.5" aria-hidden />}
    </button>
  );
}

function MarketRow({ label, value, add, market, pick }: { label: string; value: number; add?: Add; market?: string; pick?: string }) {
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="w-28 shrink-0 text-[12.5px] text-text-2">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
        <div className="h-full rounded-full bg-cobalt" style={{ width: `${value * 100}%` }} />
      </div>
      <span className="num w-12 text-right text-[12.5px] font-semibold">{pct(value)}</span>
      {add !== undefined && market && pick && <AddChip add={add} market={market} pick={pick} label={label} />}
    </div>
  );
}

const HTFT_ORDER = ["1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"];

function FirstHalfSection({ fh, add, homeName, awayName }: { fh: FirstHalf; add: Add; homeName: string; awayName: string }) {
  if (!fh.available) {
    return (
      <div className="rounded-ctl border border-line bg-bg-elevated px-4 py-3 text-[12.5px] text-text-2" data-testid="first-half-unavailable">
        <div className="mb-1 flex items-center gap-2 font-medium"><Clock3 className="size-3.5 text-amber" aria-hidden />İlk yarı tahmini yayımlanmadı</div>
        <ul className="list-disc pl-5 text-[12px] text-muted">{fh.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
      </div>
    );
  }
  const x = fh["1x2"];
  return (
    <div className="space-y-4" data-testid="first-half">
      <div className="flex items-baseline justify-between">
        <div className="eyebrow">İlk yarı</div>
        {fh.test?.n ? <span className="text-[11px] text-muted">Testte {fh.test.n} maç · log loss {fh.test.log_loss?.toFixed(3)} (temel {fh.test.baseline_log_loss?.toFixed(3)})</span> : null}
      </div>
      <div>
        <div className="mb-2 grid grid-cols-3 text-[12px] text-text-2">
          <span className="truncate">{homeName}</span><span className="text-center">Beraberlik</span><span className="truncate text-right">{awayName}</span>
        </div>
        <ProbBar p={x} size="sm" />
        {add && (
          <div className="mt-2 flex justify-between">
            <AddChip add={add} market="ht_1x2" pick="home" label="İlk yarı: 1" />
            <AddChip add={add} market="ht_1x2" pick="draw" label="İlk yarı: X" />
            <AddChip add={add} market="ht_1x2" pick="away" label="İlk yarı: 2" />
          </div>
        )}
      </div>
      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <MarketRow label="İY 0.5 Üst" value={fh.over_under["0.5"]?.over ?? 0} add={add} market="ht_total" pick="over_0.5" />
          <MarketRow label="İY 1.5 Üst" value={fh.over_under["1.5"]?.over ?? 0} add={add} market="ht_total" pick="over_1.5" />
          <MarketRow label="İY KG Var" value={fh.btts.yes} />
          <p className="mt-1 text-[11px] text-muted">İY beklenen gol: {fh.expected_goals.home.toFixed(2)} – {fh.expected_goals.away.toFixed(2)}</p>
        </div>
        <div>
          <div className="mb-2 text-[12px] text-text-2">İY / MS</div>
          <div className="grid grid-cols-3 gap-1.5">
            {HTFT_ORDER.map((k) => (
              <div key={k} className="flex items-center justify-between gap-1 rounded-ctl border border-line bg-bg-elevated px-2 py-1.5">
                <span className="num text-[12px] font-medium">{k}</span>
                <span className="num text-[11px] text-muted">{pct(fh.ht_ft[k], 1)}</span>
                <AddChip add={add} market="ht_ft" pick={k} label={`İY/MS: ${k}`} />
              </div>
            ))}
          </div>
        </div>
      </div>
      <p className="text-[11px] leading-relaxed text-muted">
        İlk yarı olasılıkları tam maç skor dağılımından, her golün ilk yarıya düşme payıyla (ev %{(fh.split.home * 100).toFixed(0)}, deplasman %{(fh.split.away * 100).toFixed(0)}) türetilir; tam maç tahminiyle tutarlıdır.
      </p>
    </div>
  );
}

/** Paket kilidi: içerik sunucudan hiç gelmez; yalnızca neyin kilitli olduğu ve hangi paket gerektiği gösterilir. */
export function LockedBox({ lock, className }: { lock: Lock; className?: string }) {
  return (
    <div className={cx("flex flex-col items-start gap-2 rounded-ctl border border-dashed border-line-strong bg-bg-elevated p-4", className)} data-testid="locked">
      <div className="flex items-center gap-2 text-[12.5px] font-medium text-text-2">
        <LockIcon className="size-3.5 text-gold" aria-hidden /> {lock.label}
      </div>
      <p className="text-[11.5px] text-muted">{lock.required_plan} paketinde açılır.</p>
      <Link href="/paketler" className="text-[12px] font-medium text-gold hover:underline">Paketleri incele →</Link>
    </div>
  );
}

// Özellik üretimi takım başına son 40 maçı tutar; 40 "en az 40" demektir.
const hist = (n: number | undefined) => (n === undefined ? "0" : n >= 40 ? "40+" : String(n));

export function PredictionPanel({ prediction, homeName, awayName, canAdd = false }: { prediction: Prediction | null | undefined; homeName: string; awayName: string; canAdd?: boolean }) {
  if (!prediction) {
    return (
      <Card>
        <CardHeader eyebrow="AI Analizi" title="Bu maç için henüz analiz yok" />
        <Empty title="Model bu maçı henüz değerlendirmedi">
          Tahminler, lig için eğitilmiş ve test edilmiş bir model olduğunda maçtan önce üretilir.
        </Empty>
      </Card>
    );
  }
  if (prediction.status === "abstained" || !prediction.probabilities) {
    return (
      <Card>
        <CardHeader eyebrow="AI Analizi" title="Model bu maç için tahmin vermedi" action={<Badge tone="amber">Çekimser</Badge>} />
        <div className="space-y-2 p-5">
          <p className="text-[13px] text-muted">Belirsizliği gizlemek yerine nedenini gösteriyoruz:</p>
          <ul className="space-y-2">
            {prediction.abstain_reasons.map((r) => (
              <li key={r.code} className="flex items-start gap-2 rounded-ctl border border-line bg-bg-elevated px-3.5 py-2.5 text-[13px] text-text-2">
                <AlertCircle className="mt-0.5 size-4 shrink-0 text-amber" aria-hidden /> {r.message}
              </li>
            ))}
          </ul>
        </div>
      </Card>
    );
  }

  const p = prediction.probabilities;
  const x = p["1x2"];
  const interval = prediction.uncertainty.interval_1x2;
  const rel = prediction.reliability;
  const dq = prediction.data_quality;
  const agreement = prediction.model_agreement;
  const locked = new Map((prediction.access?.locked ?? []).map((l) => [l.key, l]));
  const marketsLock = locked.get("predictions.markets");
  // Kupon oluşturucu PRO'da: FREE kullanıcıya (ve oturumsuz ziyaretçiye) ekleme düğmesi gösterilmez.
  const add: Add =
    canAdd && prediction.access?.plan !== "FREE"
      ? (market, pick, label) => ({ prediction_id: prediction.id, fixture_id: prediction.fixture_id, market, pick, label, match: `${homeName} – ${awayName}`, kickoff_at: prediction.kickoff_at })
      : null;

  return (
    <Card>
      <CardHeader
        eyebrow="AI Analizi"
        title="Olasılık dağılımı"
        action={<span className="text-[11.5px] text-muted">Üretildi: {fmtDateTime(prediction.created_at)}</span>}
      />
      <div className="space-y-6 p-5">
        <div>
          <div className="mb-3 grid grid-cols-3 text-[12.5px] text-text-2">
            <span className="truncate">{homeName}</span>
            <span className="text-center">Beraberlik</span>
            <span className="truncate text-right">{awayName}</span>
          </div>
          <ProbBar p={x} />
          {add && (
            <div className="mt-2 flex justify-between">
              <AddChip add={add} market="1x2" pick="home" label="Maç sonucu: 1" />
              <AddChip add={add} market="1x2" pick="draw" label="Maç sonucu: X" />
              <AddChip add={add} market="1x2" pick="away" label="Maç sonucu: 2" />
            </div>
          )}
          {interval && (
            <p className="num mt-3 text-[11.5px] text-muted">
              Aralık (%10–%90): 1 {pct(interval.home[0])}–{pct(interval.home[1])} · X {pct(interval.draw[0])}–{pct(interval.draw[1])} · 2{" "}
              {pct(interval.away[0])}–{pct(interval.away[1])}
            </p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
          <Metric icon={BadgeCheck} label="Model güvenilirliği" value={rel.label} tone={rel.level === "high" ? "teal" : rel.level === "medium" ? "gold" : "amber"} hint="Test dönemi kalibrasyonu" />
          <Metric icon={Database} label="Veri kalitesi" value={`${hist(dq.home_history)} / ${hist(dq.away_history)} maç`} hint={dq.lineups_known ? "İlk 11 açıklandı" : "İlk 11 bekleniyor"} />
          <Metric icon={Layers} label="Modeller arası uyum" value={agreement === null ? "—" : agreement <= 0.08 ? "İyi" : agreement <= 0.15 ? "Orta" : "Zayıf"} hint={agreement === null ? undefined : `En büyük fark ${pct(agreement)}`} />
          <Metric icon={Sigma} label="Beklenen gol" value={p.expected_goals ? `${p.expected_goals.home.toFixed(2)} – ${p.expected_goals.away.toFixed(2)}` : "Kilitli"} hint={p.expected_goals ? "Skor modeline göre" : "PRO paketinde"} />
        </div>

        {p.double_chance && p.over_under && p.btts && p.correct_score ? (
        <div className="grid gap-6 md:grid-cols-2">
          <div>
            <div className="eyebrow mb-2">Piyasalar</div>
            <MarketRow label="Çifte şans 1X" value={p.double_chance["1X"]} add={add} market="double_chance" pick="1X" />
            <MarketRow label="Çifte şans X2" value={p.double_chance.X2} add={add} market="double_chance" pick="X2" />
            <MarketRow label="2.5 Üst" value={p.over_under["2.5"]?.over ?? 0} add={add} market="total" pick="over_2.5" />
            <MarketRow label="1.5 Üst" value={p.over_under["1.5"]?.over ?? 0} add={add} market="total" pick="over_1.5" />
            <MarketRow label="KG Var" value={p.btts.yes} add={add} market="btts" pick="yes" />
          </div>
          <div>
            <div className="eyebrow mb-2">En olası skorlar</div>
            <div className="grid grid-cols-5 gap-1.5">
              {p.correct_score.slice(0, 10).map((s) => (
                <div key={`${s.home}-${s.away}`} className="rounded-ctl border border-line bg-bg-elevated px-1 py-2 text-center">
                  <div className="num text-[13px] font-semibold">{s.home}–{s.away}</div>
                  <div className="num text-[10.5px] text-muted">{pct(s.p, 1)}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
        ) : marketsLock ? (
          <LockedBox lock={marketsLock} />
        ) : null}

        {Object.keys(prediction.components).length > 0 && (
          <details className="rounded-ctl border border-line bg-bg-elevated px-4 py-3">
            <summary className="cursor-pointer text-[12.5px] font-medium text-text-2">Model açıklaması ve bileşenler</summary>
            <div className="mt-3 space-y-3">
              {Object.entries(prediction.components).map(([name, probs]) => (
                <div key={name}>
                  <div className="mb-1.5 flex justify-between text-[12px] text-text-2">
                    <span>{COMPONENT_LABELS[name] ?? name}</span>
                    <span className="text-muted">ağırlık {pct(prediction.model.components[name] ?? 0)}</span>
                  </div>
                  <ProbBar p={probs} size="sm" labels={false} />
                </div>
              ))}
              {prediction.uncertainty.label && <p className="text-[11.5px] text-muted">{prediction.uncertainty.label}.</p>}
              <p className="text-[11.5px] text-muted">
                Model sürümü #{prediction.model.version_id} · Eğitim verisi: {fmtDateTime(prediction.model.trained_until)} tarihine kadar.
              </p>
            </div>
          </details>
        )}

        {p.first_half && <FirstHalfSection fh={p.first_half} add={add} homeName={homeName} awayName={awayName} />}

        {locked.has("predictions.components") && Object.keys(prediction.components).length === 0 && (
          <LockedBox lock={locked.get("predictions.components")!} />
        )}

        <p className="flex items-start gap-2 text-[11.5px] leading-relaxed text-muted">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {prediction.disclaimer}
        </p>
      </div>
    </Card>
  );
}
