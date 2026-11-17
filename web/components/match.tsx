"use client";

import Link from "next/link";
import { Clock, DatabaseZap, Radio } from "lucide-react";

import { ago, fmtTime } from "@/lib/format";
import type { DataStatus, Fixture, Prediction } from "@/lib/types";
import { Badge, Notice, ProbBar, TeamCrest, cx } from "./ui";

const STATUS_LABEL: Record<string, string> = {
  tbd: "Saat belli değil",
  scheduled: "Başlamadı",
  live: "Canlı",
  halftime: "Devre arası",
  finished: "Bitti",
  postponed: "Ertelendi",
  suspended: "Durduruldu",
  cancelled: "İptal",
  abandoned: "Yarıda kaldı",
  awarded: "Hükmen",
};

export function StatusPill({ fixture }: { fixture: Fixture }) {
  const s = fixture.status;
  if (s === "live" || s === "halftime") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-teal">
        <span className="live-dot size-1.5 rounded-full bg-teal" aria-hidden />
        {s === "halftime" ? "İY" : `${fixture.minute ?? ""}'`}
      </span>
    );
  }
  if (s === "scheduled" || s === "tbd") {
    return <span className="num text-[13px] font-medium text-text-2">{s === "tbd" ? "—" : fmtTime(fixture.kickoff_at)}</span>;
  }
  return <span className="text-[11px] font-medium uppercase tracking-wide text-muted">{STATUS_LABEL[s] ?? s}</span>;
}

export function FreshnessBadge({ fixture }: { fixture: Fixture }) {
  if (!fixture.freshness.stale) return null;
  return (
    <Badge tone="amber" className="whitespace-nowrap">
      <Clock className="size-3" aria-hidden /> {ago(fixture.freshness.fetched_at)}
    </Badge>
  );
}

export function MatchRow({ fixture, prediction }: { fixture: Fixture; prediction?: Prediction }) {
  const score = fixture.score.current;
  const started = !["scheduled", "tbd", "postponed", "cancelled"].includes(fixture.status);
  return (
    <Link
      href={`/maclar/${fixture.id}`}
      className="group grid grid-cols-[52px_1fr_auto] items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-2 sm:grid-cols-[64px_1fr_auto_180px] sm:px-5"
    >
      <StatusPill fixture={fixture} />
      <div className="min-w-0 space-y-1.5">
        {[fixture.home, fixture.away].map((t, i) => (
          <div key={t.id} className="flex items-center gap-2.5">
            <TeamCrest name={t.name} logo={t.logo_url} size={20} />
            <span className={cx("truncate text-[13.5px]", score && ((i === 0 && score.home > score.away) || (i === 1 && score.away > score.home)) ? "font-semibold text-text" : "text-text-2")}>
              {t.name}
            </span>
          </div>
        ))}
      </div>
      <div className="num flex flex-col items-end gap-1.5 text-[14px] font-semibold">
        {started && score ? (
          <>
            <span>{score.home}</span>
            <span>{score.away}</span>
          </>
        ) : (
          <FreshnessBadge fixture={fixture} />
        )}
      </div>
      <div className="col-span-3 sm:col-span-1">
        {prediction?.status === "published" && prediction.probabilities ? (
          <ProbBar p={prediction.probabilities["1x2"]} size="sm" />
        ) : prediction?.status === "abstained" ? (
          <span className="text-[11px] text-muted">AI tahmin vermedi · {prediction.abstain_reasons[0]?.message}</span>
        ) : null}
      </div>
    </Link>
  );
}

export function groupByCompetition(items: Fixture[]) {
  const groups = new Map<number, { name: string; logo: string | null; items: Fixture[] }>();
  for (const f of items) {
    const g = groups.get(f.competition.id) ?? { name: f.competition.name, logo: f.competition.logo_url, items: [] };
    g.items.push(f);
    groups.set(f.competition.id, g);
  }
  return [...groups.entries()].map(([id, g]) => ({ id, ...g }));
}

export function DataStatusBanner({ status, items }: { status?: DataStatus; items?: Fixture[] }) {
  if (items?.some((f) => f.source.provider === "demo")) {
    return (
      <Notice tone="amber" title="Test ortamı: kurgusal demo verisi">
        Bu ortamdaki maçlar, skorlar ve tahminler sistemin çalıştığını göstermek için üretilmiş demo verisidir; gerçek
        değildir. Üretim ortamında yalnızca lisanslı sağlayıcı verisi gösterilir.
      </Notice>
    );
  }
  if (!status || status.data_status === "ok") return null;
  return (
    <Notice tone="amber" title="Canlı futbol verisi henüz bağlanmadı">
      <span className="inline-flex items-start gap-2">
        <DatabaseZap className="mt-0.5 size-4 shrink-0 text-amber" aria-hidden />
        <span>
          Lisanslı veri sağlayıcısı yapılandırıldığında maçlar, skorlar ve istatistikler burada görünecek. Gerçek veri
          gelmeden örnek veya uydurma maç gösterilmez.
        </span>
      </span>
    </Notice>
  );
}

export function LiveCount({ items }: { items: Fixture[] }) {
  const n = items.filter((f) => f.status === "live" || f.status === "halftime").length;
  if (!n) return null;
  return (
    <Badge tone="teal">
      <Radio className="size-3" aria-hidden /> {n} canlı
    </Badge>
  );
}
