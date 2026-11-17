"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { AlertTriangle } from "lucide-react";

import { PageTitle, RunStatus, can, useAdmin } from "@/components/admin";
import { Badge, Card, CardHeader, Empty, Skeleton, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, num, trToday } from "@/lib/format";

interface FootballStatus {
  data_status: string; provider: string; provider_label: string; last_successful_sync_at: string | null;
  capabilities: string[]; budget: { daily: number; minute: number; reserve_pct: number; used_today: number };
  provider_reported: { daily_remaining: number | null; last_error: string | null } | null;
  fixture_counts: Record<string, number>; active_competitions: number;
}
interface SyncRun { id: number; job: string; status: string; started_at: string; requests: number; items: number; message: string | null }
interface ModelBrief { id: number; scope_key: string; status: string; trained_until: string; test: { n: number | null; log_loss: number | null; ece: number | null } }


export default function CommandCenter() {
  const me = useAdmin();
  const football = useQuery({ queryKey: ["admin", "football-status"], queryFn: () => api<FootballStatus>("/admin/v1/football/status"), enabled: can(me, "football.read"), refetchInterval: 30_000 });
  const runs = useQuery({ queryKey: ["admin", "sync-runs", "recent"], queryFn: () => api<{ items: SyncRun[] }>("/admin/v1/football/sync-runs?limit=8"), enabled: can(me, "football.read"), refetchInterval: 30_000 });
  const users = useQuery({ queryKey: ["admin", "users-total"], queryFn: () => api<{ total: number }>("/admin/v1/users?page_size=1"), enabled: can(me, "users.read") });
  const models = useQuery({ queryKey: ["admin", "models"], queryFn: () => api<{ items: ModelBrief[] }>("/admin/v1/models"), enabled: can(me, "models.read") });
  const coupons = useQuery({ queryKey: ["admin", "coupons"], queryFn: () => api<{ counts: Record<string, number>; settled: { n: number; mean_predicted: number; observed_win_rate: number } | null }>("/admin/v1/coupons?limit=1"), enabled: can(me, "coupons.read") });
  const today = useQuery({ queryKey: ["fixtures", trToday()], queryFn: () => api<{ items: { status: string }[] }>(`/v1/football/fixtures?date=${trToday()}`) });

  const failed = runs.data?.items.filter((r) => r.status === "failed") ?? [];
  const champions = models.data?.items.filter((m) => m.status === "champion") ?? [];
  const live = today.data?.items.filter((f) => f.status === "live" || f.status === "halftime").length ?? 0;

  return (
    <div>
      <PageTitle eyebrow="Command Center" title="Platform durumu" />

      {(failed.length > 0 || football.data?.data_status === "no_provider") && (
        <Card className="mb-6 border-amber/30">
          <CardHeader eyebrow="Action Center" title="Dikkat gerektirenler" />
          <ul className="space-y-2 p-5 text-[13px]">
            {football.data?.data_status === "no_provider" && (
              <li className="flex gap-2"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber" aria-hidden />Futbol veri sağlayıcısı yapılandırılmamış (MI_FOOTBALL_PROVIDER / MI_FOOTBALL_API_KEY).</li>
            )}
            {failed.map((r) => (
              <li key={r.id} className="flex gap-2"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-red" aria-hidden />Veri işi başarısız: {r.job} — {r.message}</li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="p-5">
          {users.isLoading ? <Skeleton className="h-14" /> : <Stat label="Kullanıcı" value={users.data?.total ?? "—"} hint={can(me, "users.read") ? undefined : "Yetki yok"} />}
        </Card>
        <Card className="p-5"><Stat label="Bugünkü maç" value={today.data?.items.length ?? "—"} hint={`${live} canlı`} /></Card>
        <Card className="p-5"><Stat label="Şampiyon model" value={can(me, "models.read") ? champions.length : "—"} hint={champions[0] ? `Test log loss ${num(champions[0].test.log_loss, 3)}` : "Henüz eğitilmedi"} /></Card>
        <Card className="p-5"><Stat label="Takip edilen lig" value={football.data?.active_competitions ?? "—"} /></Card>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader eyebrow="Futbol operasyonları" title="Son veri işleri" action={<Link href="/yonetim/veri" className="text-[12.5px] text-gold hover:underline">Veri Merkezi</Link>} />
          <ul className="mt-3 divide-y divide-line border-t border-line">
            {!can(me, "football.read") ? <Empty title="Bu bölüm için yetkiniz yok" /> : runs.data?.items.length === 0 ? <Empty title="Henüz veri işi çalışmadı" /> : runs.data?.items.map((r) => (
              <li key={r.id} className="flex items-center gap-3 px-5 py-2.5 text-[12.5px]">
                <RunStatus s={r.status} />
                <span className="font-medium">{r.job}</span>
                <span className="truncate text-muted">{r.message ?? `${r.items} kayıt`}</span>
                <span className="ml-auto shrink-0 text-[11px] text-muted">{ago(r.started_at)}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <CardHeader eyebrow="Sağlayıcı" title={football.data?.provider_label ?? "Veri sağlayıcı"} />
          {football.data ? (
            <div className="grid grid-cols-2 gap-5 p-5">
              <Stat label="Bugünkü istek" value={`${football.data.budget.used_today}/${football.data.budget.daily}`} hint={`Rezerv %${football.data.budget.reserve_pct}`} />
              <Stat label="Sağlayıcıda kalan" value={football.data.provider_reported?.daily_remaining ?? "—"} />
              <Stat label="Son eşitleme" value={<span className="text-base">{ago(football.data.last_successful_sync_at)}</span>} />
              <Stat label="Yetenekler" value={<span className="text-base">{football.data.capabilities.length || "—"}</span>} hint={football.data.capabilities.join(", ")} />
            </div>
          ) : <Skeleton className="m-5 h-28" />}
        </Card>
      </div>

      {can(me, "coupons.read") && (
        <Card className="mt-6">
          <CardHeader eyebrow="Kuponlar" title="Kupon geçmişi" />
          <div className="grid grid-cols-2 gap-6 p-5 md:grid-cols-5">
            <Stat label="Bekleyen" value={coupons.data?.counts.pending ?? 0} />
            <Stat label="Tutan" value={coupons.data?.counts.won ?? 0} />
            <Stat label="Tutmayan" value={coupons.data?.counts.lost ?? 0} />
            <Stat label="Beklenen olasılık" value={coupons.data?.settled ? `%${(coupons.data.settled.mean_predicted * 100).toFixed(1)}` : "—"} hint="sonuçlananların ortalaması" />
            <Stat label="Gerçekleşen" value={coupons.data?.settled ? `%${(coupons.data.settled.observed_win_rate * 100).toFixed(1)}` : "—"} hint={coupons.data?.settled ? `${coupons.data.settled.n} kupon` : "henüz sonuç yok"} />
          </div>
        </Card>
      )}

      <Card className="mt-6">
        <CardHeader eyebrow="İşletme" title="Gelir ve abonelik metrikleri" />
        <Empty title="Ödeme altyapısı henüz bağlı değil">
          MRR, ARR, churn ve ARPU yalnızca gerçek ödeme kayıtlarından hesaplanacak (Faz 6). Veri olmadan sıfır veya tahmini rakam gösterilmez.
        </Empty>
      </Card>
    </div>
  );
}
