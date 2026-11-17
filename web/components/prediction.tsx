"use client";

import { AlertCircle, BadgeCheck, Database, Info, Layers, Sigma } from "lucide-react";

import { fmtDateTime, pct } from "@/lib/format";
import type { Prediction } from "@/lib/types";
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

function MarketRow({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="w-28 shrink-0 text-[12.5px] text-text-2">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
        <div className="h-full rounded-full bg-cobalt" style={{ width: `${value * 100}%` }} />
      </div>
      <span className="num w-12 text-right text-[12.5px] font-semibold">{pct(value)}</span>
    </div>
  );
}

// Özellik üretimi takım başına son 40 maçı tutar; 40 "en az 40" demektir.
const hist = (n: number | undefined) => (n === undefined ? "0" : n >= 40 ? "40+" : String(n));

export function PredictionPanel({ prediction, homeName, awayName }: { prediction: Prediction | null | undefined; homeName: string; awayName: string }) {
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
          <Metric icon={Sigma} label="Beklenen gol" value={`${p.expected_goals.home.toFixed(2)} – ${p.expected_goals.away.toFixed(2)}`} hint="Skor modeline göre" />
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          <div>
            <div className="eyebrow mb-2">Piyasalar</div>
            <MarketRow label="Çifte şans 1X" value={p.double_chance["1X"]} />
            <MarketRow label="Çifte şans X2" value={p.double_chance.X2} />
            <MarketRow label="2.5 Üst" value={p.over_under["2.5"]?.over ?? 0} />
            <MarketRow label="1.5 Üst" value={p.over_under["1.5"]?.over ?? 0} />
            <MarketRow label="KG Var" value={p.btts.yes} />
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

        <p className="flex items-start gap-2 text-[11.5px] leading-relaxed text-muted">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {prediction.disclaimer}
        </p>
      </div>
    </Card>
  );
}
