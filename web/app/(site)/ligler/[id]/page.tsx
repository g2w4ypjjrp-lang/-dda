"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { FavoriteButton } from "@/components/engage";
import { use } from "react";

import { Card, CardHeader, Empty, ErrorState, Skeleton, TeamCrest, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";

interface Row {
  rank: number; team: { id: number; name: string; logo_url: string | null }; played: number; won: number; drawn: number;
  lost: number; goals_for: number; goals_against: number; goal_diff: number; points: number; form: string | null;
}
interface Standings {
  competition: { id: number; name: string };
  season: { year: number; label: string } | null;
  fetched_at?: string | null;
  groups: { name: string; table: Row[] }[];
}

function Form({ form }: { form: string | null }) {
  if (!form) return <span className="text-muted">—</span>;
  const colors: Record<string, string> = { W: "bg-teal", D: "bg-draw", L: "bg-red" };
  const labels: Record<string, string> = { W: "G", D: "B", L: "M" };
  return (
    <span className="inline-flex gap-1" aria-label={`Form: ${form}`}>
      {form.slice(-5).split("").map((c, i) => (
        <span key={i} className={cx("grid size-4 place-items-center rounded-[4px] text-[9px] font-bold text-bg", colors[c] ?? "bg-surface-3")}>{labels[c] ?? c}</span>
      ))}
    </span>
  );
}

export default function StandingsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const q = useQuery({ queryKey: ["standings", id], queryFn: () => api<Standings>(`/v1/football/competitions/${id}/standings`) });
  return (
    <div className="py-8">
      <Link href="/maclar" className="inline-flex items-center gap-1.5 text-[13px] text-text-2 hover:text-text"><ArrowLeft className="size-4" aria-hidden /> Tüm tahminler</Link>
      {q.isLoading ? (
        <Skeleton className="mt-4 h-96" />
      ) : q.isError || !q.data ? (
        <Card className="mt-4"><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <h1 className="text-[28px] font-semibold tracking-tight">{q.data.competition.name}</h1>
            <FavoriteButton kind="competition" refId={q.data.competition.id} label={q.data.competition.name} />
          </div>
          <p className="mt-1 text-[13px] text-muted">{q.data.season ? `${q.data.season.label} sezonu · güncelleme ${ago(q.data.fetched_at)}` : "Puan durumu henüz alınmadı"}</p>
          {q.data.groups.length === 0 ? (
            <Card className="mt-6"><Empty title="Puan durumu yok">Lig takibe alındığında sağlayıcıdan düzenli olarak çekilir.</Empty></Card>
          ) : (
            q.data.groups.map((g) => (
              <Card key={g.name} className="mt-6 overflow-hidden">
                {g.name && <CardHeader title={g.name} />}
                <div className="overflow-x-auto">
                  <table className="num w-full min-w-[640px] text-[13px]">
                    <thead>
                      <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-muted">
                        <th className="w-10 px-4 py-3 font-medium">#</th>
                        <th className="px-2 py-3 font-medium">Takım</th>
                        {["O", "G", "B", "M", "A", "Y", "AV", "P"].map((h) => <th key={h} className="px-2 py-3 text-right font-medium">{h}</th>)}
                        <th className="px-4 py-3 text-right font-medium">Form</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {g.table.map((r) => (
                        <tr key={r.team.id} className="hover:bg-surface-2">
                          <td className="px-4 py-2.5 text-muted">{r.rank}</td>
                          <td className="px-2 py-2.5"><span className="flex items-center gap-2.5"><TeamCrest name={r.team.name} logo={r.team.logo_url} size={18} /><span className="truncate">{r.team.name}</span></span></td>
                          {[r.played, r.won, r.drawn, r.lost, r.goals_for, r.goals_against, r.goal_diff].map((v, i) => <td key={i} className="px-2 py-2.5 text-right text-text-2">{v}</td>)}
                          <td className="px-2 py-2.5 text-right font-semibold">{r.points}</td>
                          <td className="px-4 py-2.5 text-right"><Form form={r.form} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            ))
          )}
        </>
      )}
    </div>
  );
}
