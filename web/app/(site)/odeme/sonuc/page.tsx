"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Clock, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Card, ErrorState, Notice, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { ORDER_STATUS, money } from "@/lib/format";
import type { Order } from "@/lib/types";

export default function PaymentResultPage() {
  const [params, setParams] = useState<{ id: string | null; error: string | null } | null>(null);
  useEffect(() => {
    const s = new URLSearchParams(window.location.search);
    setParams({ id: s.get("siparis"), error: s.get("hata") });
  }, []);
  // Sağlayıcı bildirimi tarayıcı yönlendirmesinden sonra gelebilir: sonuçlanana kadar kısa aralıkla sorgulanır.
  const q = useQuery({
    queryKey: ["order", params?.id],
    queryFn: () => api<Order>(`/v1/billing/orders/${params!.id}`),
    enabled: !!params?.id,
    refetchInterval: (query) => (query.state.data?.status === "pending" && query.state.dataUpdateCount < 20 ? 3000 : false),
  });
  const o = q.data;
  const Icon = o?.status === "paid" ? CheckCircle2 : o?.status === "pending" || o?.status === "review" ? Clock : XCircle;
  const tone = o?.status === "paid" ? "text-teal" : o?.status === "pending" || o?.status === "review" ? "text-amber" : "text-red";

  return (
    <div className="mx-auto max-w-lg py-12">
      <Card>
        <div className="space-y-5 p-6">
          <h1 className="text-[18px] font-semibold">Ödeme sonucu</h1>
          {params?.error && <Notice tone="red" title="Ödeme doğrulanamadı">Sağlayıcıdan onay alınamadı. Kartınızdan çekim yapıldıysa sipariş incelemeye alınır; destek ile iletişime geçin.</Notice>}
          {params && !params.id && !params.error && <p className="text-[13px] text-muted">Sipariş bilgisi bulunamadı.</p>}
          {q.isLoading && <Skeleton className="h-20" />}
          {q.error ? <ErrorState error={q.error} /> : null}
          {o && (
            <>
              <div className={`flex items-center gap-2 text-[15px] font-semibold ${tone}`} data-testid="order-status">
                <Icon className="size-5" aria-hidden /> {ORDER_STATUS[o.status] ?? o.status}
              </div>
              <dl className="grid grid-cols-2 gap-y-2 text-[13px]">
                <dt className="text-muted">Sipariş</dt><dd className="num">#{o.number}</dd>
                <dt className="text-muted">Paket</dt><dd>{o.plan} · {o.period === "monthly" ? "Aylık" : "Yıllık"}</dd>
                <dt className="text-muted">Tutar</dt><dd className="num">{money(o.amount_minor, o.currency)}{o.test_mode ? " (test)" : ""}</dd>
              </dl>
              {o.status === "paid" && <p className="text-[13px] text-text-2">Paketiniz etkinleştirildi.</p>}
              {o.status === "pending" && <p className="text-[13px] text-muted">Sağlayıcının onayı bekleniyor; sayfa kendiliğinden güncellenir.</p>}
              {o.status === "review" && <p className="text-[13px] text-muted">Ödeme bilgilerinde uyuşmazlık var; ekibimiz inceleyecek.</p>}
            </>
          )}
          <div className="flex gap-3 text-[13px]">
            <Link href="/panel" className="font-medium text-gold hover:underline">Panelime git</Link>
            <Link href="/paketler" className="text-text-2 hover:text-text">Paketler</Link>
          </div>
        </div>
      </Card>
    </div>
  );
}
