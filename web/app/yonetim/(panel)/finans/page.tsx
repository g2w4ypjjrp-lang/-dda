"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { useState } from "react";

import { PageTitle, Table, can, useAdmin, useGuard } from "@/components/admin";
import { Badge, Button, Card, CardHeader, Empty, FormError, Input, Notice, Skeleton, Stat } from "@/components/ui";
import { api, post } from "@/lib/api";
import { ORDER_STATUS, fmtDateTime, fmtDay, money } from "@/lib/format";
import type { Order } from "@/lib/types";

interface Summary {
  revenue: Record<string, { gross_minor: number; refunded_minor: number; net_minor: number; orders: number }> | null;
  mrr_minor: Record<string, number> | null;
  arr_minor: Record<string, number> | null;
  arpu_30d_minor: number | null;
  churn_30d: number | null;
  active_subscriptions: { plan: string; source: string; count: number }[];
  payment_events_30d: Record<string, number>;
  orders_in_review: number;
  note: string;
}
type AdminOrder = Order & { email: string; note: string | null; refund_ref: string | null };
interface LicenseRow { id: number; hint: string; plan: string; duration_days: number; max_activations: number; activations_count: number; status: string; redeem_before: string; created_at: string; note: string | null; key?: string }

const first = (m: Record<string, number> | null) => (m ? Object.entries(m).map(([c, v]) => money(v, c)).join(" · ") : "Veri yok");

function Licenses() {
  const me = useAdmin();
  const guard = useGuard();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["admin", "billing", "licenses"], queryFn: () => api<{ items: LicenseRow[] }>("/admin/v1/billing/licenses?limit=100") });
  const [f, setF] = useState({ plan: "PRO", duration_days: "30", count: "1", max_activations: "1", note: "" });
  const [issued, setIssued] = useState<LicenseRow[] | null>(null);
  const create = useMutation({
    mutationFn: () => guard(() => post<{ items: LicenseRow[] }>("/admin/v1/billing/licenses", {
      plan: f.plan, duration_days: Number(f.duration_days), count: Number(f.count), max_activations: Number(f.max_activations), note: f.note || null,
    })),
    onSuccess: (r) => { setIssued(r.items); qc.invalidateQueries({ queryKey: ["admin", "billing", "licenses"] }); },
  });
  const revoke = useMutation({
    mutationFn: (id: number) => guard(() => post(`/admin/v1/billing/licenses/${id}/revoke`)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "billing", "licenses"] }),
  });
  const manage = can(me, "licenses.manage");
  return (
    <Card className="mt-6">
      <CardHeader eyebrow="Lisans" title="Lisans anahtarları" />
      {manage && (
        <form className="grid gap-3 p-5 sm:grid-cols-6 sm:items-end" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <label className="block text-[12.5px]">
            <span className="mb-1.5 block font-medium text-text-2">Paket</span>
            <select className="h-10 w-full rounded-ctl border border-line bg-bg-elevated px-2" value={f.plan} onChange={(e) => setF({ ...f, plan: e.target.value })}><option>PRO</option><option>ELITE</option></select>
          </label>
          <Input label="Süre (gün)" name="lic-days" inputMode="numeric" value={f.duration_days} onChange={(e) => setF({ ...f, duration_days: e.target.value })} />
          <Input label="Adet" name="lic-count" inputMode="numeric" value={f.count} onChange={(e) => setF({ ...f, count: e.target.value })} />
          <Input label="Kullanım hakkı" name="lic-max" inputMode="numeric" value={f.max_activations} onChange={(e) => setF({ ...f, max_activations: e.target.value })} />
          <Input label="Not" name="lic-note" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
          <Button type="submit" loading={create.isPending}>Üret</Button>
        </form>
      )}
      <div className="px-5"><FormError error={create.error ?? revoke.error} /></div>
      {issued && (
        <div className="mx-5 mb-5"><Notice tone="amber" title="Anahtarlar yalnızca şimdi gösterilir">
          <ul className="num mt-2 space-y-1 font-mono text-[12.5px]" data-testid="issued-keys">
            {issued.map((l) => <li key={l.id}>{l.key}</li>)}
          </ul>
          <Button size="sm" variant="ghost" className="mt-2" onClick={() => navigator.clipboard?.writeText(issued.map((l) => l.key).join("\n"))}><Copy className="size-3.5" aria-hidden />Kopyala</Button>
        </Notice></div>
      )}
      {list.isLoading ? <Skeleton className="m-5 h-20" /> : !list.data?.items.length ? <Empty title="Henüz lisans üretilmedi" /> : (
        <Table head={["Anahtar", "Paket", "Süre", "Kullanım", "Son kullanma", "Durum", ""]}>
          {list.data.items.map((l) => (
            <tr key={l.id}>
              <td className="num px-4 py-2.5 font-mono">{l.hint}</td>
              <td className="px-4 py-2.5">{l.plan}</td>
              <td className="px-4 py-2.5">{l.duration_days} gün</td>
              <td className="num px-4 py-2.5">{l.activations_count}/{l.max_activations}</td>
              <td className="px-4 py-2.5">{fmtDay(l.redeem_before)}</td>
              <td className="px-4 py-2.5"><Badge tone={l.status === "active" ? "teal" : "red"}>{l.status === "active" ? "Etkin" : "İptal"}</Badge></td>
              <td className="px-4 py-2.5 text-right">{manage && l.status === "active" && <Button size="sm" variant="ghost" onClick={() => revoke.mutate(l.id)}>İptal et</Button>}</td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

export default function FinancePage() {
  const me = useAdmin();
  const guard = useGuard();
  const qc = useQueryClient();
  const summary = useQuery({ queryKey: ["admin", "billing", "summary"], queryFn: () => api<Summary>("/admin/v1/billing/summary") });
  const orders = useQuery({ queryKey: ["admin", "billing", "orders"], queryFn: () => api<{ items: AdminOrder[] }>("/admin/v1/billing/orders?limit=100") });
  const refund = useMutation({
    mutationFn: (n: number) => guard(() => post(`/admin/v1/billing/orders/${n}/refund`)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "billing"] }),
  });
  const s = summary.data;
  const rev = s?.revenue ? Object.entries(s.revenue) : [];
  return (
    <>
      <PageTitle eyebrow="Gelir" title="Finans & Lisanslar" />
      <Card className="grid grid-cols-2 gap-6 p-6 md:grid-cols-4">
        {summary.isLoading ? <Skeleton className="col-span-4 h-16" /> : s && (
          <>
            <Stat label="Net gelir (tüm zamanlar)" value={rev.length ? rev.map(([c, v]) => money(v.net_minor, c)).join(" · ") : "Veri yok"} hint={rev.length ? `${rev.reduce((a, [, v]) => a + v.orders, 0)} sipariş` : "Canlı ödeme yok"} />
            <Stat label="MRR" value={first(s.mrr_minor)} hint={s.arr_minor ? `ARR ${first(s.arr_minor)}` : undefined} />
            <Stat label="ARPU (30 gün)" value={s.arpu_30d_minor === null ? "Veri yok" : money(s.arpu_30d_minor)} />
            <Stat label="Kayıp oranı (30 gün)" value={s.churn_30d === null ? "Veri yok" : `%${(s.churn_30d * 100).toFixed(1)}`} />
          </>
        )}
      </Card>
      {s && (
        <div className="mt-3 flex flex-wrap gap-2 text-[12px] text-muted">
          <span>{s.note}</span>
          {s.orders_in_review > 0 && <Badge tone="amber">{s.orders_in_review} sipariş incelemede</Badge>}
          {Object.entries(s.payment_events_30d).map(([k, v]) => <Badge key={k} tone={k === "invalid_signature" ? "red" : "neutral"}>{k}: {v}</Badge>)}
        </div>
      )}
      <Card className="mt-6">
        <CardHeader eyebrow="Kayıtlar" title="Siparişler" />
        {orders.isLoading ? <Skeleton className="m-5 h-24" /> : !orders.data?.items.length ? <Empty title="Henüz sipariş yok" /> : (
          <Table head={["No", "Kullanıcı", "Paket", "Tutar", "Durum", "Tarih", ""]} minWidth={820}>
            {orders.data.items.map((o) => (
              <tr key={o.id}>
                <td className="num px-4 py-2.5">#{o.number}</td>
                <td className="px-4 py-2.5">{o.email}</td>
                <td className="px-4 py-2.5">{o.plan} · {o.period === "monthly" ? "aylık" : "yıllık"}</td>
                <td className="num px-4 py-2.5">{money(o.amount_minor, o.currency)}{o.test_mode && <span className="text-muted"> (test)</span>}</td>
                <td className="px-4 py-2.5" title={o.note ?? undefined}><Badge tone={o.status === "paid" ? "teal" : o.status === "review" ? "amber" : o.status === "failed" ? "red" : "neutral"}>{ORDER_STATUS[o.status]}</Badge></td>
                <td className="px-4 py-2.5">{fmtDateTime(o.created_at)}</td>
                <td className="px-4 py-2.5 text-right">
                  {can(me, "finance.refund") && o.status === "paid" && (
                    <Button size="sm" variant="ghost" loading={refund.isPending && refund.variables === o.number}
                      onClick={() => { if (window.confirm(`#${o.number} siparişi iade edilsin mi? Abonelik sona erer.`)) refund.mutate(o.number); }}>İade</Button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        )}
        <div className="px-5 pb-4"><FormError error={refund.error} /></div>
      </Card>
      {can(me, "licenses.read") && <Licenses />}
    </>
  );
}
