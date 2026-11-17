"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, Info, Siren } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageTitle, can, useAdmin, useGuard } from "@/components/admin";
import { Badge, Button, Card, Empty, ErrorState, FormError, Input, Skeleton, cx } from "@/components/ui";
import { api, post } from "@/lib/api";
import { ago, fmtDateTime } from "@/lib/format";

interface Issue { key: string; category: string; severity: "critical" | "warning" | "info"; title: string; detail: string; link: string | null; at: string | null; acked: { at: string; note: string | null } | null }

const CATEGORY: Record<string, string> = {
  errors: "Kritik hatalar", payments: "Ödeme sorunları", data: "Veri güncelleme / API", models: "Model uyarıları",
  tasks: "Başarısız görevler", pending: "Bekleyen işlemler",
};
const ICON = { critical: Siren, warning: AlertTriangle, info: Info } as const;
const TONE = { critical: "red", warning: "amber", info: "neutral" } as const;
const SEV = { critical: "Kritik", warning: "Uyarı", info: "Bilgi" } as const;

function ReviewOrder({ number, onDone }: { number: number; onDone: () => void }) {
  const guard = useGuard();
  const [note, setNote] = useState("");
  const resolve = useMutation({
    mutationFn: (action: "approve" | "refund") => guard(() => post(`/admin/v1/billing/orders/${number}/resolve`, { action, note, confirm: true })),
    onSuccess: onDone,
  });
  return (
    <div className="mt-3 space-y-2 rounded-ctl border border-line bg-bg-elevated p-3">
      <Input label="Karar notu (zorunlu)" name={`note-${number}`} value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={note.trim().length < 5} loading={resolve.isPending && resolve.variables === "approve"}
          onClick={() => { if (window.confirm(`#${number}: ödeme doğrulandı, abonelik verilsin mi?`)) resolve.mutate("approve"); }}>Onayla ve abonelik ver</Button>
        <Button size="sm" variant="danger" disabled={note.trim().length < 5} loading={resolve.isPending && resolve.variables === "refund"}
          onClick={() => { if (window.confirm(`#${number}: ödeme sağlayıcı üzerinden iade edilsin mi?`)) resolve.mutate("refund"); }}>İade et</Button>
      </div>
      <FormError error={resolve.error} />
    </div>
  );
}

export default function ActionCenter() {
  const me = useAdmin();
  const qc = useQueryClient();
  const [showAcked, setShowAcked] = useState(false);
  const q = useQuery({ queryKey: ["admin", "actions", showAcked], queryFn: () => api<{ items: Issue[] }>(`/admin/v1/actions${showAcked ? "?include_acked=true" : ""}`), refetchInterval: 30_000 });
  const ack = useMutation({
    mutationFn: (key: string) => post("/admin/v1/actions/ack", { key }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "actions"] }),
  });
  const items = q.data?.items ?? [];
  const groups = Object.keys(CATEGORY).map((c) => ({ c, items: items.filter((i) => i.category === c) })).filter((g) => g.items.length);

  return (
    <>
      <PageTitle eyebrow="Operasyon" title="Action Center">
        <label className="flex items-center gap-2 text-[12.5px] text-text-2">
          <input type="checkbox" className="accent-[var(--mi-gold)]" checked={showAcked} onChange={(e) => setShowAcked(e.target.checked)} />Görülenleri de göster
        </label>
      </PageTitle>
      <p className="-mt-3 mb-5 max-w-3xl text-[13px] text-muted">Uyarılar her açılışta gerçek kayıtlardan hesaplanır ve yetkinize göre süzülür. "Görüldü", yalnızca o sorunu gizler; aynı türden yeni bir sorun yeniden görünür.</p>
      {q.isLoading ? <Skeleton className="h-64" /> : q.error ? <Card><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card> : groups.length === 0 ? (
        <Card><Empty title="Dikkat gerektiren bir şey yok" icon={<Check className="size-5" aria-hidden />}>Yeni bir sorun oluştuğunda burada görünür.</Empty></Card>
      ) : (
        <div className="space-y-6">
          {groups.map((g) => (
            <section key={g.c}>
              <h2 className="eyebrow mb-2">{CATEGORY[g.c]}</h2>
              <Card className="divide-y divide-line">
                {g.items.map((i) => {
                  const Icon = ICON[i.severity];
                  const order = i.key.startsWith("order_review:") ? Number(i.key.split(":")[1]) : null;
                  return (
                    <div key={i.key} className={cx("px-5 py-4", i.acked && "opacity-60")} data-testid={`issue-${i.key}`}>
                      <div className="flex flex-wrap items-start gap-3">
                        <Icon className={cx("mt-0.5 size-4 shrink-0", i.severity === "critical" ? "text-red" : i.severity === "warning" ? "text-amber" : "text-muted")} aria-hidden />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2 text-[13.5px] font-medium">{i.title}<Badge tone={TONE[i.severity]}>{SEV[i.severity]}</Badge></div>
                          <p className="mt-1 text-[12.5px] text-text-2">{i.detail}</p>
                          <div className="mt-1 text-[11.5px] text-muted">
                            {i.at && <span title={fmtDateTime(i.at)}>{ago(i.at)} · </span>}
                            {i.acked ? `Görüldü ${ago(i.acked.at)}${i.acked.note ? ` — ${i.acked.note}` : ""}` : null}
                          </div>
                          {order && can(me, "finance.refund") && <ReviewOrder number={order} onDone={() => qc.invalidateQueries({ queryKey: ["admin", "actions"] })} />}
                        </div>
                        <div className="flex shrink-0 gap-2">
                          {i.link && <Link href={i.link} className="inline-flex h-8 items-center rounded-ctl border border-line px-3 text-[12.5px] text-text-2 hover:text-text">Git</Link>}
                          {!i.acked && <Button size="sm" variant="ghost" loading={ack.isPending && ack.variables === i.key} onClick={() => ack.mutate(i.key)}>Görüldü</Button>}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </Card>
            </section>
          ))}
        </div>
      )}
      <FormError error={ack.error} />
    </>
  );
}
