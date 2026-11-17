"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PageTitle, can, useAdmin, useGuard } from "@/components/admin";
import { Badge, Button, Card, ErrorState, FormError, Skeleton } from "@/components/ui";
import { api, put } from "@/lib/api";
import { ago } from "@/lib/format";

interface Flag { key: string; enabled: boolean; description: string; message: string | null; updated_at: string }

function FlagRow({ f, editable }: { f: Flag; editable: boolean }) {
  const guard = useGuard();
  const qc = useQueryClient();
  const [message, setMessage] = useState(f.message ?? "");
  const m = useMutation({
    mutationFn: (enabled: boolean) => guard(() => put(`/admin/v1/flags/${f.key}`, { enabled, message: message || null })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "flags"] }),
  });
  return (
    <div className="flex flex-wrap items-start gap-4 px-5 py-4" data-testid={`flag-${f.key}`}>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[13.5px] font-medium">{f.description}<Badge tone={f.enabled ? "teal" : "neutral"}>{f.enabled ? "Açık" : "Kapalı"}</Badge></div>
        <div className="mt-0.5 font-mono text-[11.5px] text-muted">{f.key} · güncellendi {ago(f.updated_at)}</div>
        {editable && (
          <input aria-label={`${f.key} mesajı`} placeholder={f.key === "maintenance_notice" ? "Duyuru metni (zorunlu)" : "Kapalıyken kullanıcıya gösterilecek mesaj (isteğe bağlı)"}
            value={message} onChange={(e) => setMessage(e.target.value)} className="mt-2 h-8 w-full max-w-lg rounded-ctl border border-line bg-bg-elevated px-2 text-[12.5px]" />
        )}
        <FormError error={m.error} />
      </div>
      {editable && (
        <Button size="sm" variant={f.enabled ? "secondary" : "primary"} loading={m.isPending}
          onClick={() => { if (window.confirm(`"${f.description}" ${f.enabled ? "kapatılsın" : "açılsın"} mı? Değişiklik hemen tüm kullanıcılara uygulanır.`)) m.mutate(!f.enabled); }}>
          {f.enabled ? "Kapat" : "Aç"}
        </Button>
      )}
    </div>
  );
}

export default function FeatureFlags() {
  const me = useAdmin();
  const q = useQuery({ queryKey: ["admin", "flags"], queryFn: () => api<{ items: Flag[] }>("/admin/v1/flags") });
  const editable = can(me, "flags.manage");
  return (
    <>
      <PageTitle eyebrow="Platform" title="Özellik Bayrakları" />
      <p className="-mt-3 mb-5 max-w-3xl text-[13px] text-muted">Bayraklar sunucuda uygulanır: kapalı bir özellik ilgili uçları durdurur (arayüzde gizlemek yetmez). Her değişiklik denetim kaydına yazılır{editable ? "" : "; değiştirmek için flags.manage yetkisi gerekir"}.</p>
      {q.isLoading ? <Skeleton className="h-64" /> : q.error ? <Card><ErrorState error={q.error} /></Card> : (
        <Card className="divide-y divide-line">{q.data?.items.map((f) => <FlagRow key={`${f.key}-${f.updated_at}`} f={f} editable={editable} />)}</Card>
      )}
    </>
  );
}
