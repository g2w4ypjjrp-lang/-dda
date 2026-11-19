"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { DataStatusBanner, LiveCount, MatchList, groupByCompetition } from "@/components/match";
import { Card, Empty, ErrorState, Skeleton, TeamCrest, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { dayLabel, shiftDay, trToday } from "@/lib/format";
import type { FixtureList, Prediction } from "@/lib/types";

const FILTERS = [
  { key: "all", label: "Tümü" },
  { key: "live", label: "Canlı" },
  { key: "upcoming", label: "Başlamadı" },
  { key: "finished", label: "Bitti" },
] as const;

export default function MatchCenterPage() {
  const today = trToday();
  const [day, setDay] = useState(today);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const [competition, setCompetition] = useState<number | null>(null);

  const fixtures = useQuery({
    queryKey: ["fixtures", day],
    queryFn: () => api<FixtureList>(`/v1/football/fixtures?date=${day}`),
    refetchInterval: (q) => (q.state.data?.items.some((f) => f.status === "live" || f.status === "halftime") ? 30_000 : 120_000),
  });
  const predictions = useQuery({
    queryKey: ["predictions", day],
    queryFn: () => api<{ items: Prediction[] }>(`/v1/predictions?date=${day}`),
  });
  const byFixture = new Map((predictions.data?.items ?? []).map((p) => [p.fixture_id, p]));

  const all = fixtures.data?.items ?? [];
  const visible = all.filter((f) => {
    if (competition && f.competition.id !== competition) return false;
    if (filter === "live") return f.status === "live" || f.status === "halftime";
    if (filter === "upcoming") return f.status === "scheduled" || f.status === "tbd";
    if (filter === "finished") return f.status === "finished";
    return true;
  });
  const groups = groupByCompetition(visible);
  const competitions = groupByCompetition(all);
  const days = [-2, -1, 0, 1, 2, 3, 4].map((d) => shiftDay(today, d));

  return (
    <div className="py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow mb-2">Tahminler</div>
          <h1 className="text-[28px] font-semibold tracking-tight">Maçlar ve analizler</h1>
        </div>
        <LiveCount items={all} />
      </div>

      {/* Gün seçici */}
      <div className="mt-6 flex items-center gap-2">
        <button type="button" aria-label="Önceki gün" onClick={() => setDay(shiftDay(day, -1))} className="grid size-9 shrink-0 place-items-center rounded-ctl border border-line bg-surface text-text-2 hover:text-text">
          <ChevronLeft className="size-4" aria-hidden />
        </button>
        <div className="flex flex-1 gap-1.5 overflow-x-auto [scrollbar-width:none]" role="tablist" aria-label="Gün">
          {days.map((d) => (
            <button
              key={d}
              type="button"
              role="tab"
              aria-selected={d === day}
              onClick={() => setDay(d)}
              className={cx(
                "h-9 shrink-0 rounded-ctl px-3.5 text-[12.5px] font-medium transition-colors",
                d === day ? "bg-text text-bg" : "border border-line bg-surface text-text-2 hover:text-text",
              )}
            >
              {d === today ? "Bugün" : dayLabel(d)}
            </button>
          ))}
        </div>
        <button type="button" aria-label="Sonraki gün" onClick={() => setDay(shiftDay(day, 1))} className="grid size-9 shrink-0 place-items-center rounded-ctl border border-line bg-surface text-text-2 hover:text-text">
          <ChevronRight className="size-4" aria-hidden />
        </button>
      </div>

      {/* Filtreler */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            aria-pressed={filter === f.key}
            onClick={() => setFilter(f.key)}
            className={cx("h-8 rounded-full px-3 text-[12.5px] font-medium", filter === f.key ? "bg-gold-soft text-gold" : "text-text-2 hover:bg-surface-2")}
          >
            {f.label}
          </button>
        ))}
        {competitions.length > 1 && (
          <select
            aria-label="Lig"
            value={competition ?? ""}
            onChange={(e) => setCompetition(e.target.value ? Number(e.target.value) : null)}
            className="ml-auto h-8 rounded-ctl border border-line bg-surface px-2 text-[12.5px] text-text-2"
          >
            <option value="">Tüm ligler</option>
            {competitions.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        )}
      </div>

      <div className="mt-6 space-y-4">
        <DataStatusBanner status={fixtures.data} items={fixtures.data?.items} />
        {fixtures.isLoading ? (
          <Card className="space-y-3 p-5">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-12" />)}</Card>
        ) : fixtures.isError ? (
          <Card><ErrorState error={fixtures.error} onRetry={() => fixtures.refetch()} /></Card>
        ) : groups.length === 0 ? (
          <Card><Empty title="Bu gün için maç bulunamadı">Başka bir gün veya filtre seçin.</Empty></Card>
        ) : (
          groups.map((g) => (
            <Card key={g.id} className="overflow-hidden">
              <Link href={`/ligler/${g.id}`} className="flex items-center gap-2.5 border-b border-line bg-bg-elevated px-5 py-3 hover:bg-surface-2">
                <TeamCrest name={g.name} logo={g.logo} size={18} />
                <span className="text-[13px] font-semibold">{g.name}</span>
                <span className="ml-auto text-[11.5px] text-muted">{g.items.length} maç · Puan durumu</span>
              </Link>
              <MatchList fixtures={g.items} byFixture={byFixture} columns={3} />
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
