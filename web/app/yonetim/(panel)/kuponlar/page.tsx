"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { PageTitle, Table, can, useAdmin } from "@/components/admin";
import { Badge, Button, Card, CardHeader, Empty, ErrorState, FormError, Skeleton, Stat } from "@/components/ui";
import { api, post } from "@/lib/api";
import { fmtDateTime, pct } from "@/lib/format";

interface Summary {
  counts: Record<string, number>;
  settled: { n: number; mean_predicted: number | null; observed_win_rate: number | null; note?: string } | null;
  items: { id: number; user_id: string | null; created_at: string; profile: string; legs: number; joint_probability: number; status: string }[];
}
const STATUS: Record<string, { tone: "neutral" | "teal" | "red" | "amber"; label: string }> = { pending: { tone: "neutral", label: "Bekliyor" }, won: { tone: "teal", label: "Tuttu" }, lost: { tone: "red", label: "Tutmadı" }, void: { tone: "amber", label: "Geçersiz" } };

export default function CouponAdmin() {
  const me = useAdmin();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "coupons-admin"], queryFn: () => api<Summary>("/admin/v1/coupons?limit=100") });
  const settle = useMutation({
    mutationFn: () => post<{ legs: number; coupons: number }>("/admin/v1/coupons/settle"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "coupons-admin"] }),
  });
  if (q.isLoading) return <><PageTitle eyebrow="Operasyon" title="Kupon Yönetimi" /><Skeleton className="h-96" /></>;
  if (q.error || !q.data) return <><PageTitle eyebrow="Operasyon" title="Kupon Yönetimi" /><Card><ErrorState error={q.error} /></Card></>;
  const d = q.data;
  return (
    <div className="space-y-6">
      <PageTitle eyebrow="Operasyon" title="Kupon Yönetimi">
        {can(me, "coupons.manage") && <Button size="sm" variant="secondary" loading={settle.isPending} onClick={() => settle.mutate()}>Şimdi sonuçlandır</Button>}
      </PageTitle>
      {settle.data && <p className="text-[12.5px] text-teal">{settle.data.legs} seçim, {settle.data.coupons} kupon sonuçlandı.</p>}
      <FormError error={settle.error} />
      <Card className="grid grid-cols-2 gap-6 p-6 md:grid-cols-5">
        {(["pending", "won", "lost", "void"] as const).map((s) => <Stat key={s} label={STATUS[s]!.label} value={d.counts[s] ?? 0} />)}
        <Stat label="Gerçekleşen / beklenen" value={d.settled && d.settled.n ? `${pct(d.settled.observed_win_rate, 1)} / ${pct(d.settled.mean_predicted, 1)}` : "Veri yok"} hint={d.settled?.n ? `${d.settled.n} sonuçlanmış kupon` : "Sonuçlanmış kupon yok"} />
      </Card>
      <Card>
        <CardHeader eyebrow="Kayıtlar (değiştirilemez)" title="Son kuponlar" />
        {d.items.length ? (
          <Table head={["No", "Oluşturma", "Profil", "Seçim", "Olasılık", "Durum"]} minWidth={640}>
            {d.items.map((c) => <tr key={c.id}><td className="num px-4 py-2">#{c.id}</td><td className="px-4 py-2">{fmtDateTime(c.created_at)}</td><td className="px-4 py-2">{c.profile}</td><td className="num px-4 py-2">{c.legs}</td><td className="num px-4 py-2">{pct(c.joint_probability, 1)}</td><td className="px-4 py-2"><Badge tone={STATUS[c.status]?.tone ?? "neutral"}>{STATUS[c.status]?.label ?? c.status}</Badge></td></tr>)}
          </Table>
        ) : <Empty title="Henüz kupon yok" />}
      </Card>
    </div>
  );
}
