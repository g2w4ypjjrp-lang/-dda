"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PageTitle, Table, can, useAdmin, useGuard } from "@/components/admin";
import { Badge, Button, Card, CardHeader, Empty, FormError, Input, Notice, Skeleton } from "@/components/ui";
import { api, del, post, put } from "@/lib/api";
import { SUB_SOURCE, SUB_STATUS, fmtDay, money } from "@/lib/format";
import type { PlanInfo, Sales, SubscriptionInfo } from "@/lib/types";

interface AdminPlans { plans: PlanInfo[]; entitlement_keys: Record<string, "bool" | "int">; labels: Record<string, string>; sales: Sales }

function PlanEditor({ plan, keys }: { plan: PlanInfo; keys: AdminPlans["entitlement_keys"] }) {
  const me = useAdmin();
  const guard = useGuard();
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Record<string, boolean | number>>({});
  const [price, setPrice] = useState<Record<string, string>>({});
  const editable = can(me, "subscriptions.manage");
  const refresh = () => qc.invalidateQueries({ queryKey: ["admin", "billing"] });
  const save = useMutation({
    mutationFn: () => guard(() => put(`/admin/v1/billing/plans/${plan.code}/entitlements`, { values: draft })),
    onSuccess: () => { setDraft({}); refresh(); },
  });
  const setP = useMutation({
    mutationFn: (period: string) => guard(() => put(`/admin/v1/billing/plans/${plan.code}/prices`, { period, amount_minor: Math.round(Number((price[period] ?? "").replace(",", ".")) * 100) })),
    onSuccess: () => { setPrice({}); refresh(); },
  });
  const close = useMutation({
    mutationFn: (period: string) => guard(() => del(`/admin/v1/billing/plans/${plan.code}/prices/${period}`)),
    onSuccess: refresh,
  });
  const value = (k: string) => (k in draft ? draft[k] : plan.entitlements[k]);
  return (
    <Card>
      <CardHeader eyebrow={plan.tagline} title={plan.name} />
      <div className="space-y-4 p-5 text-[12.5px]">
        {plan.code !== "FREE" && (
          <div className="space-y-2">
            <div className="eyebrow">Fiyat</div>
            {(["monthly", "yearly"] as const).map((period) => {
              const p = plan.prices[period];
              return (
                <div key={period} className="flex flex-wrap items-end gap-2">
                  <span className="w-12 text-muted">{period === "monthly" ? "Aylık" : "Yıllık"}</span>
                  <span className="num w-24">{p ? money(p.amount_minor, p.currency) : "Satışa kapalı"}</span>
                  {editable && (
                    <>
                      <div className="w-28"><Input label="Yeni (₺)" name={`${plan.code}-${period}`} inputMode="decimal" value={price[period] ?? ""} onChange={(e) => setPrice({ ...price, [period]: e.target.value })} /></div>
                      <Button size="sm" variant="secondary" disabled={!(Number((price[period] ?? "").replace(",", ".")) >= 1)} loading={setP.isPending && setP.variables === period} onClick={() => setP.mutate(period)}>Kaydet</Button>
                      {p && <Button size="sm" variant="ghost" loading={close.isPending && close.variables === period} onClick={() => close.mutate(period)}>Satışı kapat</Button>}
                    </>
                  )}
                </div>
              );
            })}
            <FormError error={setP.error ?? close.error} />
          </div>
        )}
        <div className="space-y-1.5">
          <div className="eyebrow">Haklar</div>
          {Object.entries(keys).map(([k, kind]) => (
            <div key={k} className="flex items-center justify-between gap-3">
              <span className="text-text-2">{k}</span>
              {kind === "bool" ? (
                <input type="checkbox" aria-label={k} className="accent-[var(--mi-gold)]" disabled={!editable} checked={!!value(k)} onChange={(e) => setDraft({ ...draft, [k]: e.target.checked })} />
              ) : (
                <input type="number" aria-label={k} min={0} disabled={!editable} value={Number(value(k) ?? 0)} onChange={(e) => setDraft({ ...draft, [k]: Number(e.target.value) })}
                  className="num w-20 rounded-ctl border border-line bg-bg-elevated px-2 py-1 text-right" />
              )}
            </div>
          ))}
          {Object.keys(draft).length > 0 && <Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>Hakları kaydet</Button>}
          <FormError error={save.error} />
        </div>
      </div>
    </Card>
  );
}

function GrantForm() {
  const guard = useGuard();
  const qc = useQueryClient();
  const [f, setF] = useState({ email: "", plan: "PRO", days: "30", note: "" });
  const grant = useMutation({
    mutationFn: () => guard(() => post("/admin/v1/billing/subscriptions/grant", { ...f, days: Number(f.days), note: f.note || null })),
    onSuccess: () => { setF({ ...f, email: "", note: "" }); qc.invalidateQueries({ queryKey: ["admin", "billing"] }); },
  });
  return (
    <Card>
      <CardHeader eyebrow="Destek" title="Ödemesiz abonelik tanımla" />
      <form className="grid gap-3 p-5 sm:grid-cols-[2fr_1fr_1fr_2fr_auto] sm:items-end" onSubmit={(e) => { e.preventDefault(); grant.mutate(); }}>
        <Input label="E-posta" name="grant-email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        <label className="block text-[12.5px]">
          <span className="mb-1.5 block font-medium text-text-2">Paket</span>
          <select className="h-10 w-full rounded-ctl border border-line bg-bg-elevated px-2" value={f.plan} onChange={(e) => setF({ ...f, plan: e.target.value })}>
            <option>PRO</option><option>ELITE</option>
          </select>
        </label>
        <Input label="Gün" name="grant-days" inputMode="numeric" value={f.days} onChange={(e) => setF({ ...f, days: e.target.value })} />
        <Input label="Not" name="grant-note" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
        <Button type="submit" loading={grant.isPending} disabled={!f.email.includes("@") || !(Number(f.days) >= 1)}>Tanımla</Button>
      </form>
      <div className="px-5 pb-5"><FormError error={grant.error} />{grant.isSuccess && <p className="text-[12.5px] text-teal">Abonelik tanımlandı ve denetim kaydına yazıldı.</p>}</div>
    </Card>
  );
}

export default function SubscriptionsAdminPage() {
  const me = useAdmin();
  const guard = useGuard();
  const qc = useQueryClient();
  const plans = useQuery({ queryKey: ["admin", "billing", "plans"], queryFn: () => api<AdminPlans>("/admin/v1/billing/plans") });
  const subs = useQuery({ queryKey: ["admin", "billing", "subs"], queryFn: () => api<{ items: (SubscriptionInfo & { email: string })[] }>("/admin/v1/billing/subscriptions?limit=100") });
  const revoke = useMutation({
    mutationFn: (id: number) => guard(() => post(`/admin/v1/billing/subscriptions/${id}/revoke`)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "billing"] }),
  });
  return (
    <>
      <PageTitle eyebrow="Gelir" title="Paketler & Abonelikler" />
      {plans.data && !plans.data.sales.open && <div className="mb-5"><Notice tone="amber" title="Satış kapalı">Ödeme sağlayıcısı bağlı değil (MI_PAYMENT_PROVIDER=none). Canlı ödeme M-G5 onayı ile açılır.</Notice></div>}
      {plans.data?.sales.open && plans.data.sales.test_mode && <div className="mb-5"><Notice tone="amber" title="Test modu">Sağlayıcı: {plans.data.sales.provider}. Gerçek ödeme alınmaz.</Notice></div>}
      <div className="grid gap-5 lg:grid-cols-3">
        {plans.isLoading && <Skeleton className="h-64" />}
        {plans.data?.plans.map((p) => <PlanEditor key={p.code} plan={p} keys={plans.data.entitlement_keys} />)}
      </div>
      {can(me, "subscriptions.manage") && <div className="mt-6"><GrantForm /></div>}
      <Card className="mt-6">
        <CardHeader eyebrow="Kayıtlar" title="Abonelikler" />
        {subs.isLoading ? <Skeleton className="m-5 h-24" /> : !subs.data?.items.length ? <Empty title="Henüz abonelik yok" /> : (
          <Table head={["Kullanıcı", "Paket", "Kaynak", "Durum", "Bitiş", ""]}>
            {subs.data.items.map((s) => (
              <tr key={s.id}>
                <td className="px-4 py-2.5">{s.email}</td>
                <td className="px-4 py-2.5">{s.plan}</td>
                <td className="px-4 py-2.5">{SUB_SOURCE[s.source]}</td>
                <td className="px-4 py-2.5"><Badge tone={s.in_effect ? "teal" : "neutral"}>{SUB_STATUS[s.status]}</Badge></td>
                <td className="px-4 py-2.5">{fmtDay(s.current_period_end)}</td>
                <td className="px-4 py-2.5 text-right">
                  {can(me, "subscriptions.manage") && (s.status === "active" || s.status === "canceled") && (
                    <Button size="sm" variant="ghost" loading={revoke.isPending && revoke.variables === s.id} onClick={() => revoke.mutate(s.id)}>Sonlandır</Button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        )}
        <div className="px-5 pb-4"><FormError error={revoke.error} /></div>
      </Card>
    </>
  );
}
