"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button, Card, ErrorState, FormError, Notice, Skeleton } from "@/components/ui";
import { api, post } from "@/lib/api";
import { money } from "@/lib/format";
import type { Order } from "@/lib/types";

/** Yalnızca geliştirme/test: ödeme simülatörü. Sunucu üretim ortamında bu uçları kapatır. */
export default function TestPaymentPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  useEffect(() => setToken(new URLSearchParams(window.location.search).get("oturum") ?? ""), []);
  const q = useQuery({
    queryKey: ["sim", token],
    queryFn: () => api<{ order: Order }>(`/v1/billing/simulator/session?token=${encodeURIComponent(token!)}`),
    enabled: !!token,
    retry: false,
  });
  const complete = useMutation({
    mutationFn: (outcome: "success" | "fail") => post<{ result: string; order: Order }>("/v1/billing/simulator/complete", { token: token!, outcome }),
    onSuccess: (r) => router.push(`/odeme/sonuc?siparis=${r.order.id}`),
  });

  return (
    <div className="mx-auto max-w-lg py-12">
      <Card>
        <div className="space-y-5 p-6">
          <div className="flex items-center gap-2">
            <FlaskConical className="size-5 text-amber" aria-hidden />
            <h1 className="text-[18px] font-semibold">Test ödeme sayfası</h1>
          </div>
          <Notice tone="amber" title="TEST MODU — gerçek ödeme alınmaz">
            Bu sayfa ödeme akışını denemek içindir. Kart bilgisi istenmez; sonuç aşağıdan seçilir ve imzalı test bildirimi olarak işlenir.
          </Notice>
          {token === "" && <p className="text-[13px] text-muted">Ödeme oturumu bulunamadı.</p>}
          {q.isLoading && <Skeleton className="h-20" />}
          {q.error ? <ErrorState error={q.error} /> : null}
          {q.data && (
            <>
              <dl className="grid grid-cols-2 gap-y-2 text-[13px]">
                <dt className="text-muted">Sipariş</dt><dd className="num">#{q.data.order.number}</dd>
                <dt className="text-muted">Paket</dt><dd>{q.data.order.plan} · {q.data.order.period === "monthly" ? "Aylık" : "Yıllık"}</dd>
                <dt className="text-muted">Tutar</dt><dd className="num font-semibold">{money(q.data.order.amount_minor, q.data.order.currency)}</dd>
              </dl>
              <FormError error={complete.error} />
              <div className="flex gap-2">
                <Button loading={complete.isPending && complete.variables === "success"} onClick={() => complete.mutate("success")}>Başarılı ödeme</Button>
                <Button variant="secondary" loading={complete.isPending && complete.variables === "fail"} onClick={() => complete.mutate("fail")}>Başarısız ödeme</Button>
              </div>
            </>
          )}
        </div>
      </Card>
    </div>
  );
}
