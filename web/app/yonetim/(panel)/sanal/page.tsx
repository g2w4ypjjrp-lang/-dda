"use client";

import { useQuery } from "@tanstack/react-query";

import { PageTitle } from "@/components/admin";
import { Card, ErrorState, Notice, Skeleton, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { pct, sb } from "@/lib/format";

interface Virtual { accounts: number; total_balance_minor: number; tickets: Record<string, number>; settled_staked_minor: number; simulated_roi: number | null; label: string }

export default function VirtualAdmin() {
  const q = useQuery({ queryKey: ["admin", "virtual"], queryFn: () => api<Virtual>("/admin/v1/virtual") });
  if (q.isLoading) return <><PageTitle eyebrow="Operasyon" title="Sanal Finans" /><Skeleton className="h-64" /></>;
  if (q.error || !q.data) return <><PageTitle eyebrow="Operasyon" title="Sanal Finans" /><Card><ErrorState error={q.error} /></Card></>;
  const d = q.data;
  const t = (k: string) => d.tickets[k] ?? 0;
  return (
    <div className="space-y-6">
      <PageTitle eyebrow="Operasyon" title="Sanal Finans" />
      <Notice tone="amber" title={d.label}>Sanal birim (SB) gerçek para değildir; ödeme, çekim veya transfer yoktur. Rakamlar yalnızca simülasyon davranışını izlemek içindir.</Notice>
      <Card className="grid grid-cols-2 gap-6 p-6 md:grid-cols-4">
        <Stat label="Sanal hesap" value={d.accounts} />
        <Stat label="Toplam sanal bakiye" value={sb(d.total_balance_minor)} />
        <Stat label="Bilet (bekleyen / sonuçlanan)" value={`${t("pending")} / ${t("won") + t("lost")}`} hint={`${t("void")} geçersiz`} />
        <Stat label="Simüle ROI" value={d.simulated_roi === null ? "Veri yok" : pct(d.simulated_roi, 1)} hint={d.settled_staked_minor ? `${sb(d.settled_staked_minor)} sonuçlanan tutar` : "Sonuçlanmış bilet yok"} />
      </Card>
    </div>
  );
}
