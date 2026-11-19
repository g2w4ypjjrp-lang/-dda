"use client";

// Sıradaki maçlar ve her maçın en olası seçimi (sunucu, paketin açtığı piyasalardan hesaplar).
// Bugün başlamamış maç kalmadıysa boş sayfa yerine sıradaki maç günü gösterilir. Liste dakikada bir
// kendiliğinden yenilenir; geri sayım canlı akar. Olasılıklar modelin olasılığıdır, oran değildir.

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Flame, Radio } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { dayLabel, fmtTime, pct } from "@/lib/format";
import { Badge, Card, Empty, ErrorState, ProbBar, Skeleton, TeamCrest, cx } from "./ui";

export interface UpcomingItem {
  fixture_id: number;
  prediction_id: number;
  kickoff_at: string;
  kickoff_local: string;
  home: string;
  away: string;
  home_logo: string | null;
  away_logo: string | null;
  competition: { id: number; name: string; logo_url: string | null };
  reliability: "high" | "medium" | "low";
  one_x_two: { home: number; draw: number; away: number };
  favourite: { pick: "1" | "X" | "2"; probability: number };
  pick: { market: string; pick: string; label: string; probability: number };
}
export interface Upcoming {
  days: number;
  today: string;
  next_match_day: string | null;
  markets: string[];
  plan: string;
  items: UpcomingItem[];
  total: number;
  disclaimer: string;
}

const REL = { high: { tone: "teal", label: "Güvenilirlik yüksek" }, medium: { tone: "cobalt", label: "Güvenilirlik orta" }, low: { tone: "neutral", label: "Güvenilirlik düşük" } } as const;
const REL_W = { high: 1, medium: 0.95, low: 0.85 } as const;

export function useUpcoming(days = 7, limit = 60) {
  return useQuery({
    queryKey: ["upcoming", days, limit],
    queryFn: () => api<Upcoming>(`/v1/predictions/upcoming?days=${days}&limit=${limit}`),
    refetchInterval: 60_000,
  });
}

/** Dakikada bir yeniden çizilir: geri sayım akar. */
function useNow(ms = 30_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

function countdown(iso: string, now: number): string {
  const m = Math.round((new Date(iso).getTime() - now) / 60_000);
  if (m <= 0) return "başlıyor";
  if (m < 60) return `${m} dk sonra`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} sa ${m % 60} dk sonra`;
  return `${Math.floor(h / 24)} gün sonra`;
}

const localDay = (iso: string) => iso.slice(0, 10);

function PickCard({ it, now }: { it: UpcomingItem; now: number }) {
  const day = localDay(it.kickoff_local);
  return (
    <Link href={`/maclar/${it.fixture_id}`} className="mi-card rise group flex flex-col rounded-card border border-line bg-surface p-4 shadow-card">
      <div className="flex items-center justify-between gap-2 text-[11.5px] text-muted">
        <span className="truncate">{it.competition.name}</span>
        <span className="num shrink-0">{dayLabel(day)} · {fmtTime(it.kickoff_at)}</span>
      </div>
      <div className="mt-3 grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        <div className="flex min-w-0 flex-col items-center gap-1.5 text-center">
          <TeamCrest name={it.home} logo={it.home_logo} size={34} />
          <span className="line-clamp-2 text-[13px] font-medium leading-tight text-text">{it.home}</span>
        </div>
        <span className="text-[11px] font-medium text-muted">vs</span>
        <div className="flex min-w-0 flex-col items-center gap-1.5 text-center">
          <TeamCrest name={it.away} logo={it.away_logo} size={34} />
          <span className="line-clamp-2 text-[13px] font-medium leading-tight text-text">{it.away}</span>
        </div>
      </div>
      <div className="mt-4 rounded-ctl border border-line bg-bg-elevated px-3 py-2.5 text-center">
        <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-text-2">En olası seçim</div>
        <div className="mi-neon-num num mt-0.5 text-[30px] font-bold leading-none text-gold">{pct(it.pick.probability)}</div>
        <div className="mt-1 text-[13px] font-semibold text-text">{it.pick.label}</div>
      </div>
      <div className="mt-3"><ProbBar p={it.one_x_two} size="sm" /></div>
      <div className="mt-3 flex items-center justify-between gap-2 text-[11.5px]">
        <Badge tone={REL[it.reliability].tone}>{REL[it.reliability].label}</Badge>
        <span className="num text-text-2">{countdown(it.kickoff_at, now)}</span>
      </div>
    </Link>
  );
}

/** Ana sayfa: sıradaki maçlar ve en güçlü seçimler. */
export function UpcomingPicks() {
  const q = useUpcoming();
  const now = useNow();
  const [mode, setMode] = useState<"soon" | "strong">("soon");
  const d = q.data;
  const items = d?.items ?? [];
  const todayLeft = items.filter((i) => localDay(i.kickoff_local) === d?.today).length;
  const shown = mode === "soon"
    ? items.slice(0, 9)
    : [...items].sort((a, b) => b.pick.probability * REL_W[b.reliability] - a.pick.probability * REL_W[a.reliability]).slice(0, 9);
  const basic = d && !d.markets.includes("total");

  return (
    <section className="mb-8" aria-labelledby="sirdaki-baslik">
      <div className="mi-neon-line mb-5 rounded-full" aria-hidden />
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow mb-1.5 flex items-center gap-2">
            <span className="relative flex size-2" aria-hidden>
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-teal opacity-60" />
              <span className="relative inline-flex size-2 rounded-full bg-teal" />
            </span>
            Canlı güncellenir
          </div>
          <h2 id="sirdaki-baslik" className="text-[24px] font-semibold tracking-tight">
            {!d ? "Sıradaki maçlar" : todayLeft > 0 ? `Bugün ${todayLeft} maç · sıradaki tahminler` : "Sıradaki maçların tahminleri"}
          </h2>
          {d && todayLeft === 0 && d.next_match_day && (
            <p className="mt-1 text-[13px] text-text-2">
              Bugün başlamamış maç kalmadı. Sıradaki maç günü: <strong className="text-text">{dayLabel(d.next_match_day)}</strong>.
            </p>
          )}
        </div>
        <div className="flex gap-1.5" role="tablist" aria-label="Sıralama">
          {([["soon", "En yakın", Radio], ["strong", "En güçlü", Flame]] as const).map(([k, label, Icon]) => (
            <button key={k} type="button" role="tab" aria-selected={mode === k} onClick={() => setMode(k)}
              className={cx("inline-flex h-9 items-center gap-1.5 rounded-ctl px-3.5 text-[12.5px] font-medium", mode === k ? "bg-text text-bg" : "border border-line bg-surface text-text-2 hover:text-text")}>
              <Icon className="size-3.5" aria-hidden />{label}
            </button>
          ))}
        </div>
      </div>

      {q.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-72" />)}</div>
      ) : q.isError ? (
        <Card><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card>
      ) : items.length === 0 ? (
        <Card><Empty title="Önümüzdeki 7 günde yayımlanmış tahmin yok">Takip edilen liglerde yaklaşan maçların tahminleri yazıldıkça burada görünür. Model yeterli veri olmayan maçlarda tahmin vermez.</Empty></Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {shown.map((it) => <PickCard key={it.fixture_id} it={it} now={now} />)}
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-[12px] text-muted">
            <span>
              {d!.total} maçın tahmini hazır.{" "}
              {basic ? "Alt/üst ve karşılıklı gol seçimleri PRO ve ELITE paketlerde hesaba katılır. " : ""}
              Yüzdeler modelin olasılığıdır, bahis oranı değildir.
            </span>
            <span className="flex gap-3">
              <Link href="/kuponlar" className="inline-flex items-center gap-1 font-medium text-gold hover:underline">Bu maçlardan kupon oluştur <ArrowRight className="size-3.5" aria-hidden /></Link>
              <Link href="/maclar" className="inline-flex items-center gap-1 font-medium text-gold hover:underline">Tüm tahminler <ArrowRight className="size-3.5" aria-hidden /></Link>
            </span>
          </div>
        </>
      )}
    </section>
  );
}
