"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, Crown, Minus, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge, Button, Card, CardHeader, ErrorState, FormError, Input, Notice, Skeleton, cx } from "@/components/ui";
import { api, post } from "@/lib/api";
import { money } from "@/lib/format";
import { useMe } from "@/lib/hooks";
import type { BillingMe, Order, PlanInfo, PlansResponse } from "@/lib/types";

type Period = "monthly" | "yearly";

const ROWS: { key: string; label: string; fmt?: (v: boolean | number) => string }[] = [
  { key: "predictions.markets", label: "Tüm piyasalar ve doğru skor olasılıkları" },
  { key: "predictions.uncertainty", label: "Belirsizlik aralıkları" },
  { key: "predictions.components", label: "Model karşılaştırması (bileşenler)" },
  { key: "coupons.enabled", label: "Kupon oluşturucu" },
  { key: "coupons.daily_generate", label: "Günlük kupon üretimi", fmt: (v) => (v ? String(v) : "—") },
  { key: "coupons.max_legs", label: "Kupondaki en fazla maç", fmt: (v) => (v ? String(v) : "—") },
  { key: "virtual.enabled", label: "Sanal portföy simülasyonu" },
  { key: "virtual.kelly", label: "Kesirli Kelly ile sanal simülasyon" },
  { key: "history.days", label: "Kupon geçmişi", fmt: (v) => (Number(v) >= 3650 ? "Sınırsız" : `${v} gün`) },
];

function Cell({ value, fmt }: { value: boolean | number | undefined; fmt?: (v: boolean | number) => string }) {
  if (value === undefined) return <span className="text-muted">—</span>;
  if (fmt) return <span className="num">{fmt(value)}</span>;
  return value ? <Check className="mx-auto size-4 text-teal" aria-label="Var" /> : <Minus className="mx-auto size-4 text-muted" aria-label="Yok" />;
}

function CheckoutForm({ plan, period, onCancel }: { plan: PlanInfo; period: Period; onCancel: () => void }) {
  const [buyer, setBuyer] = useState({ full_name: "", phone: "", address: "", city: "" });
  const [terms, setTerms] = useState(false);
  const [distance, setDistance] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const price = plan.prices[period]!;
  const set = (k: keyof typeof buyer) => (e: React.ChangeEvent<HTMLInputElement>) => setBuyer({ ...buyer, [k]: e.target.value });
  return (
    <form
      className="space-y-3 p-5"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          const r = await post<{ order: Order; redirect_url: string }>("/v1/billing/checkout", {
            plan: plan.code, period, buyer, accept_terms: terms, accept_distance_sales: distance,
          });
          window.location.assign(r.redirect_url);
        } catch (err) {
          setError(err);
          setBusy(false);
        }
      }}
    >
      <div className="text-[13px] text-text-2">
        {plan.name} · {period === "monthly" ? "Aylık" : "Yıllık"} · <strong className="num text-text">{money(price.amount_minor, price.currency)}</strong>
      </div>
      <Input label="Ad soyad (fatura)" name="full_name" autoComplete="name" required minLength={3} value={buyer.full_name} onChange={set("full_name")} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Telefon" name="phone" autoComplete="tel" value={buyer.phone} onChange={set("phone")} />
        <Input label="Şehir" name="city" autoComplete="address-level2" value={buyer.city} onChange={set("city")} />
      </div>
      <Input label="Adres" name="address" autoComplete="street-address" value={buyer.address} onChange={set("address")} />
      <label className="flex items-start gap-2 text-[12.5px] text-text-2">
        <input type="checkbox" className="mt-0.5 accent-[var(--mi-gold)]" checked={terms} onChange={(e) => setTerms(e.target.checked)} />
        <span>Kullanım koşullarını ve bunun bir analiz/sanal simülasyon hizmeti olduğunu (gerçek bahis, kazanç veya para çekme içermediğini) kabul ediyorum.</span>
      </label>
      <label className="flex items-start gap-2 text-[12.5px] text-text-2">
        <input type="checkbox" className="mt-0.5 accent-[var(--mi-gold)]" checked={distance} onChange={(e) => setDistance(e.target.checked)} />
        <span>Ön bilgilendirme formunu ve mesafeli satış sözleşmesini okudum; hizmetin ödeme sonrası hemen başlatılmasını onaylıyorum.</span>
      </label>
      <FormError error={error} />
      <div className="flex gap-2">
        <Button type="submit" loading={busy} disabled={!terms || !distance || buyer.full_name.trim().length < 3}>Ödemeye geç</Button>
        <Button type="button" variant="ghost" onClick={onCancel}>Vazgeç</Button>
      </div>
    </form>
  );
}

export default function PlansPage() {
  const { data: me } = useMe();
  const q = useQuery({ queryKey: ["billing", "plans"], queryFn: () => api<PlansResponse>("/v1/billing/plans") });
  const mine = useQuery({ queryKey: ["billing", "me"], queryFn: () => api<BillingMe>("/v1/billing/me"), enabled: !!me });
  const [period, setPeriod] = useState<Period>("monthly");
  const [buying, setBuying] = useState<PlanInfo | null>(null);

  if (q.isLoading) return <div className="space-y-4 py-8"><Skeleton className="h-24" /><Skeleton className="h-96" /></div>;
  if (q.error || !q.data) return <Card className="mt-8"><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card>;
  const { plans, sales, note } = q.data;
  const current = mine.data?.plan ?? "FREE";

  return (
    <div className="py-8">
      <div className="eyebrow mb-2">Paketler</div>
      <h1 className="text-[28px] font-semibold tracking-tight">Analiz derinliğinizi seçin</h1>
      <p className="mt-2 max-w-2xl text-[13.5px] text-text-2">{note}</p>

      {!sales.open && (
        <div className="mt-5"><Notice tone="amber" title="Satış henüz açılmadı">Ödeme altyapısı yayına alınmadı. Ücretli paketler lisans anahtarıyla veya destek ekibi tarafından tanımlanabilir.</Notice></div>
      )}
      {sales.open && sales.test_mode && (
        <div className="mt-5"><Notice tone="amber" title="Test modu">Ödeme sağlayıcısı test modunda: gerçek ödeme alınmaz.</Notice></div>
      )}

      <div className="mt-6 inline-flex rounded-ctl border border-line bg-bg-elevated p-1" role="tablist" aria-label="Ödeme dönemi">
        {(["monthly", "yearly"] as const).map((p) => (
          <button key={p} type="button" role="tab" aria-selected={period === p} onClick={() => setPeriod(p)}
            className={cx("rounded-[6px] px-4 py-1.5 text-[12.5px] font-medium", period === p ? "bg-surface-2 text-text" : "text-muted hover:text-text")}>
            {p === "monthly" ? "Aylık" : "Yıllık"}
          </button>
        ))}
      </div>

      <div className="mt-5 grid gap-5 md:grid-cols-3">
        {plans.map((plan) => {
          const price = plan.prices[period];
          const isCurrent = current === plan.code;
          const canBuy = plan.code !== "FREE" && sales.open && !!price;
          return (
            <Card key={plan.code} className={cx("flex flex-col", plan.code === "PRO" && "border-gold/40")}>
              <div className="p-6" data-testid={`plan-${plan.code}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {plan.code !== "FREE" && <Crown className={cx("size-4", plan.code === "ELITE" ? "text-gold" : "text-cobalt")} aria-hidden />}
                    <h2 className="text-[17px] font-semibold">{plan.name}</h2>
                  </div>
                  {isCurrent && <Badge tone="teal">Mevcut paketiniz</Badge>}
                </div>
                <p className="mt-1 text-[12.5px] text-muted">{plan.tagline}</p>
                <div className="mt-5 min-h-[44px]">
                  {plan.code === "FREE" ? (
                    <div className="text-[26px] font-semibold">Ücretsiz</div>
                  ) : price ? (
                    <div><span className="num text-[26px] font-semibold">{money(price.amount_minor, price.currency)}</span><span className="text-[12.5px] text-muted"> / {period === "monthly" ? "ay" : "yıl"}</span></div>
                  ) : (
                    <div className="text-[15px] font-medium text-text-2">Fiyat yakında</div>
                  )}
                </div>
                <div className="mt-5">
                  {plan.code === "FREE" ? (
                    me ? null : <Link href="/kayit" className="inline-flex h-9 items-center rounded-ctl border border-line-strong px-3.5 text-[13px] font-medium hover:bg-surface-2">Ücretsiz hesap aç</Link>
                  ) : !canBuy ? (
                    <Button variant="secondary" disabled>Satışa kapalı</Button>
                  ) : !me ? (
                    <Link href="/giris?next=/paketler" className="inline-flex h-9 items-center rounded-ctl bg-gold px-3.5 text-[13px] font-semibold text-[#14110a]">Giriş yapıp satın al</Link>
                  ) : !me.email_verified ? (
                    <p className="text-[12px] text-amber">Satın almak için önce e-posta adresinizi doğrulayın.</p>
                  ) : (
                    <Button onClick={() => setBuying(plan)}>{isCurrent ? "Süreyi uzat" : `${plan.name} satın al`}</Button>
                  )}
                </div>
              </div>
              {buying?.code === plan.code && price && <div className="border-t border-line"><CheckoutForm plan={plan} period={period} onCancel={() => setBuying(null)} /></div>}
            </Card>
          );
        })}
      </div>

      <Card className="mt-8">
        <CardHeader eyebrow="Karşılaştırma" title="Paket hakları" />
        <div className="overflow-x-auto">
          <table className="mt-3 w-full min-w-[560px] text-[12.5px]">
            <thead>
              <tr className="border-y border-line text-[11px] uppercase tracking-wide text-muted">
                <th className="px-5 py-2.5 text-left font-medium">Özellik</th>
                {plans.map((p) => <th key={p.code} className="px-3 py-2.5 text-center font-medium">{p.name}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {ROWS.map((r) => (
                <tr key={r.key}>
                  <td className="px-5 py-2.5 text-text-2">{r.label}</td>
                  {plans.map((p) => <td key={p.code} className="px-3 py-2.5 text-center"><Cell value={p.entitlements[r.key]} fmt={r.fmt} /></td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="flex items-start gap-2 p-5 text-[11.5px] text-muted">
          <ShieldCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          Haklar sunucuda uygulanır ve yönetim panelinden güncellenebilir; tablo her zaman güncel değerleri gösterir. Lisans anahtarınız varsa Panelim sayfasından kullanabilirsiniz.
        </p>
      </Card>
    </div>
  );
}
