"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, MapPin, UserRound } from "lucide-react";
import Link from "next/link";
import { use, useState } from "react";

import { StatusPill } from "@/components/match";
import { PredictionPanel } from "@/components/prediction";
import { Badge, Card, CardHeader, Empty, ErrorState, Skeleton, TeamCrest, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { ago, fmtDate, fmtTime } from "@/lib/format";
import { useMe } from "@/lib/hooks";
import type { FixtureDetail, Prediction, TeamStats } from "@/lib/types";

const STAT_ROWS: { key: keyof TeamStats; label: string; pct?: boolean; dec?: boolean }[] = [
  { key: "xg", label: "Gol beklentisi (xG)", dec: true },
  { key: "possession_pct", label: "Topla oynama", pct: true },
  { key: "shots_total", label: "Şut" },
  { key: "shots_on_target", label: "İsabetli şut" },
  { key: "corners", label: "Korner" },
  { key: "passes_total", label: "Pas" },
  { key: "passes_accurate", label: "İsabetli pas" },
  { key: "fouls", label: "Faul" },
  { key: "yellow_cards", label: "Sarı kart" },
  { key: "red_cards", label: "Kırmızı kart" },
  { key: "offsides", label: "Ofsayt" },
  { key: "goalkeeper_saves", label: "Kaleci kurtarışı" },
];

const TABS = ["AI Analizi", "İstatistikler", "Kadrolar"] as const;

function StatsCompare({ detail }: { detail: FixtureDetail }) {
  const h = detail.team_stats.home;
  const a = detail.team_stats.away;
  if (!h || !a) {
    return <Empty title="İstatistik henüz yok">Maç başladıktan veya bittikten sonra sağlayıcıdan alınır.</Empty>;
  }
  return (
    <div className="space-y-4 p-5">
      {STAT_ROWS.map((r) => {
        const hv = h[r.key] as number | null | undefined;
        const av = a[r.key] as number | null | undefined;
        if (hv == null && av == null) return null;
        const total = (hv ?? 0) + (av ?? 0) || 1;
        const fmt = (v: number | null | undefined) => (v == null ? "—" : r.dec ? v.toFixed(2) : r.pct ? `%${Math.round(v)}` : String(v));
        return (
          <div key={r.key}>
            <div className="num mb-1.5 flex items-center justify-between text-[12.5px]">
              <span className="font-semibold">{fmt(hv)}</span>
              <span className="text-muted">{r.label}</span>
              <span className="font-semibold">{fmt(av)}</span>
            </div>
            <div className="flex h-1.5 gap-1">
              <div className="flex flex-1 justify-end overflow-hidden rounded-full bg-surface-3">
                <div className="h-full rounded-full bg-home" style={{ width: `${((hv ?? 0) / total) * 100}%` }} />
              </div>
              <div className="flex-1 overflow-hidden rounded-full bg-surface-3">
                <div className="h-full rounded-full bg-away" style={{ width: `${((av ?? 0) / total) * 100}%` }} />
              </div>
            </div>
          </div>
        );
      })}
      <p className="text-[11px] text-muted">Güncelleme: {ago(h.fetched_at)}</p>
    </div>
  );
}

function Lineups({ detail }: { detail: FixtureDetail }) {
  const sides = (["home", "away"] as const).filter((s) => detail.lineups[s]);
  return (
    <div className="grid gap-6 p-5 md:grid-cols-2">
      {sides.length === 0 && <div className="md:col-span-2"><Empty title="Kadrolar henüz açıklanmadı">İlk 11'ler genellikle maçtan yaklaşık bir saat önce gelir.</Empty></div>}
      {sides.map((s) => {
        const l = detail.lineups[s]!;
        return (
          <div key={s}>
            <div className="mb-3 flex items-center justify-between">
              <span className="text-[13px] font-semibold">{s === "home" ? detail.home.name : detail.away.name}</span>
              <Badge>{l.formation ?? "—"}</Badge>
            </div>
            <ul className="space-y-1">
              {l.players.map((p) => (
                <li key={p.id} className={cx("flex items-center gap-3 rounded-ctl px-2 py-1.5 text-[13px]", !p.starter && "text-muted")}>
                  <span className="num w-6 text-right text-[12px] text-muted">{p.number ?? ""}</span>
                  <span className="flex-1 truncate">{p.name}</span>
                  <span className="text-[11px] text-muted">{p.starter ? p.position : "Yedek"}</span>
                </li>
              ))}
            </ul>
            {l.coach && <p className="mt-3 flex items-center gap-1.5 text-[12px] text-muted"><UserRound className="size-3.5" aria-hidden />{l.coach}</p>}
          </div>
        );
      })}
      {detail.absences.length > 0 && (
        <div className="md:col-span-2">
          <div className="eyebrow mb-2">Eksikler</div>
          <ul className="grid gap-2 sm:grid-cols-2">
            {detail.absences.map((a) => (
              <li key={`${a.side}-${a.player}`} className="flex items-center justify-between rounded-ctl border border-line bg-bg-elevated px-3 py-2 text-[12.5px]">
                <span className="truncate">{a.player} <span className="text-muted">· {a.side === "home" ? detail.home.name : detail.away.name}</span></span>
                <Badge tone={a.category === "suspension" ? "red" : a.status === "questionable" ? "amber" : "neutral"}>
                  {a.category === "suspension" ? "Cezalı" : a.status === "questionable" ? "Şüpheli" : "Sakat"}
                </Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function MatchDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [tab, setTab] = useState<(typeof TABS)[number]>("AI Analizi");
  const { data: me } = useMe();
  const detail = useQuery({
    queryKey: ["fixture", id],
    queryFn: () => api<FixtureDetail>(`/v1/football/fixtures/${id}`),
    refetchInterval: (q) => (q.state.data && ["live", "halftime"].includes(q.state.data.status) ? 30_000 : false),
  });
  const prediction = useQuery({
    queryKey: ["prediction", id, me?.id ?? null],
    queryFn: async () => {
      try {
        return await api<Prediction>(`/v1/predictions/fixtures/${id}`);
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
  });

  if (detail.isLoading) {
    return <div className="space-y-4 py-8"><Skeleton className="h-48" /><Skeleton className="h-80" /></div>;
  }
  if (detail.isError || !detail.data) {
    return <Card className="mt-8"><ErrorState error={detail.error} onRetry={() => detail.refetch()} /></Card>;
  }
  const d = detail.data;
  const score = d.score.current;

  return (
    <div className="py-8">
      <Link href="/maclar" className="inline-flex items-center gap-1.5 text-[13px] text-text-2 hover:text-text">
        <ArrowLeft className="size-4" aria-hidden /> Maç Merkezi
      </Link>

      <Card className="mt-4 overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-bg-elevated px-5 py-3 text-[12.5px] text-text-2">
          <Link href={`/ligler/${d.competition.id}`} className="font-medium hover:text-text">{d.competition.name} · {d.season.label}{d.round ? ` · ${d.round}` : ""}</Link>
          <span>{fmtDate(d.kickoff_at)} · {fmtTime(d.kickoff_at)}</span>
        </div>
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-4 px-5 py-8 sm:px-10">
          {[d.home, null, d.away].map((t, i) =>
            t ? (
              <div key={t.id} className={cx("flex flex-col items-center gap-3 text-center")}>
                <TeamCrest name={t.name} logo={t.logo_url} size={56} />
                <span className="text-[15px] font-semibold sm:text-lg">{t.name}</span>
                <span className="text-[11px] text-muted">{i === 0 ? "Ev sahibi" : "Deplasman"}</span>
              </div>
            ) : (
              <div key="score" className="flex flex-col items-center gap-2">
                <div className="num text-4xl font-semibold tracking-tight sm:text-5xl">
                  {score ? `${score.home} – ${score.away}` : "vs"}
                </div>
                <StatusPill fixture={d} />
                {d.score.halftime && <span className="num text-[11.5px] text-muted">İY {d.score.halftime.home}–{d.score.halftime.away}</span>}
                {d.score.penalties && <span className="num text-[11.5px] text-muted">Pen. {d.score.penalties.home}–{d.score.penalties.away}</span>}
              </div>
            ),
          )}
        </div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-line px-5 py-3 text-[11.5px] text-muted">
          {d.venue && <span className="inline-flex items-center gap-1"><MapPin className="size-3.5" aria-hidden />{d.venue.name}{d.venue.city ? `, ${d.venue.city}` : ""}</span>}
          {d.referee && <span>Hakem: {d.referee}</span>}
          <span>Kaynak: {d.source.provider_label}</span>
          <span className={d.freshness.stale ? "text-amber" : undefined}>Güncelleme: {ago(d.freshness.fetched_at)}{d.freshness.stale ? " (gecikmeli)" : ""}</span>
          <span>Veri tamlığı: {d.completeness.score}/100</span>
        </div>
      </Card>

      <div role="tablist" aria-label="Maç bölümleri" className="mt-6 flex gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={cx("-mb-px border-b-2 px-4 py-2.5 text-[13px] font-medium", tab === t ? "border-gold text-text" : "border-transparent text-text-2 hover:text-text")}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="mt-5" role="tabpanel">
        {tab === "AI Analizi" &&
          (prediction.isLoading ? <Skeleton className="h-96" /> : <PredictionPanel prediction={prediction.data} homeName={d.home.name} awayName={d.away.name} canAdd={!!me} />)}
        {tab === "İstatistikler" && (
          <Card>
            <CardHeader eyebrow="Karşılaştırma" title="Takım istatistikleri" />
            <StatsCompare detail={d} />
          </Card>
        )}
        {tab === "Kadrolar" && (
          <Card>
            <CardHeader eyebrow="Kadro" title="İlk 11, yedekler ve eksikler" />
            <Lineups detail={d} />
          </Card>
        )}
      </div>

      {d.completeness.issues.length > 0 && (
        <p className="mt-4 text-[11.5px] text-muted">Eksik veri: {d.completeness.issues.map((i) => i.message).join(" · ")}</p>
      )}
    </div>
  );
}
