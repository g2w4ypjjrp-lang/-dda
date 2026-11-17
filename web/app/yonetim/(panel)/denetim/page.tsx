"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";

import { PageTitle, Table } from "@/components/admin";
import { Button, Card, Empty, Input, Notice, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

interface Entry { id: number; occurred_at: string; actor_type: string; actor_id: string | null; action: string; target_type: string | null; target_id: string | null; ip: string | null; details: Record<string, unknown> }

export default function AuditPage() {
  const [action, setAction] = useState("");
  const [before, setBefore] = useState<number | null>(null);
  const list = useQuery({
    queryKey: ["admin", "audit", action, before],
    queryFn: () => api<{ items: Entry[]; next_before_id: number | null }>(`/admin/v1/audit?limit=50${action ? `&action=${encodeURIComponent(action)}` : ""}${before ? `&before_id=${before}` : ""}`),
  });
  const verify = useMutation({ mutationFn: () => api<{ intact: boolean; first_broken_id: number | null; entries: number }>("/admin/v1/audit/verify") });
  return (
    <div>
      <PageTitle eyebrow="Güvenlik" title="Denetim kaydı">
        <Button variant="secondary" size="sm" loading={verify.isPending} onClick={() => verify.mutate()}><ShieldCheck className="size-4" aria-hidden />Zinciri doğrula</Button>
      </PageTitle>
      {verify.data && (
        <div className="mb-4">
          <Notice tone={verify.data.intact ? "teal" : "red"} title={verify.data.intact ? "Zincir sağlam" : "Zincir kırık!"}>
            {verify.data.intact ? `${verify.data.entries} kaydın hash zinciri doğrulandı; hiçbir kayıt değiştirilmemiş veya silinmemiş.` : `${verify.data.first_broken_id} numaralı kayıtta değişiklik tespit edildi.`}
          </Notice>
        </div>
      )}
      <Card>
        <div className="p-5"><Input label="Eylem öneki" name="action" placeholder="ör. admin. veya auth.login" value={action} onChange={(e) => { setAction(e.target.value); setBefore(null); }} /></div>
        <div className="border-t border-line">
          {list.isLoading ? <Skeleton className="m-5 h-40" /> : list.data?.items.length === 0 ? <Empty title="Kayıt yok" /> : (
            <Table head={["#", "Zaman", "Aktör", "Eylem", "Hedef", "IP", "Ayrıntı"]} minWidth={900}>
              {list.data?.items.map((e) => (
                <tr key={e.id} className="align-top hover:bg-surface-2">
                  <td className="num px-4 py-2.5 text-muted">{e.id}</td>
                  <td className="px-4 py-2.5 text-text-2">{fmtDateTime(e.occurred_at)}</td>
                  <td className="px-4 py-2.5">{e.actor_type}<div className="max-w-[140px] truncate text-[11px] text-muted">{e.actor_id}</div></td>
                  <td className="px-4 py-2.5 font-medium">{e.action}</td>
                  <td className="px-4 py-2.5 text-text-2">{e.target_type ?? "—"}<div className="max-w-[140px] truncate text-[11px] text-muted">{e.target_id}</div></td>
                  <td className="px-4 py-2.5 text-text-2">{e.ip ?? "—"}</td>
                  <td className="max-w-[280px] px-4 py-2.5"><code className="block truncate text-[11px] text-muted" title={JSON.stringify(e.details)}>{JSON.stringify(e.details)}</code></td>
                </tr>
              ))}
            </Table>
          )}
        </div>
        <div className="flex justify-end gap-2 p-4">
          {before && <Button size="sm" variant="ghost" onClick={() => setBefore(null)}>En yeniye dön</Button>}
          {list.data?.next_before_id && <Button size="sm" variant="ghost" onClick={() => setBefore(list.data!.next_before_id)}>Daha eski</Button>}
        </div>
      </Card>
    </div>
  );
}
