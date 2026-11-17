"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PageTitle, useGuard } from "@/components/admin";
import { Badge, Button, Card, Empty, ErrorState, FormError, Notice, Skeleton, cx } from "@/components/ui";
import { api, post } from "@/lib/api";
import { ago, fmtDateTime } from "@/lib/format";

interface Approval {
  id: number;
  action: string;
  label: string;
  permission: string;
  target: string;
  summary: string;
  status: "pending" | "executed" | "rejected" | "cancelled" | "expired" | "failed";
  requested_by: string | null;
  requested_at: string;
  expires_at: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  result: Record<string, unknown> | null;
  mine: boolean;
  can_decide: boolean;
}

const STATUS: Record<Approval["status"], { label: string; tone: "amber" | "teal" | "red" | "neutral" }> = {
  pending: { label: "Bekliyor", tone: "amber" },
  executed: { label: "Onaylandı, yürütüldü", tone: "teal" },
  rejected: { label: "Reddedildi", tone: "red" },
  cancelled: { label: "İptal edildi", tone: "neutral" },
  expired: { label: "Süresi doldu", tone: "neutral" },
  failed: { label: "Onaylandı, yürütülemedi", tone: "red" },
};

function Row({ a }: { a: Approval }) {
  const guard = useGuard();
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const done = () => {
    qc.invalidateQueries({ queryKey: ["admin", "approvals"] });
    qc.invalidateQueries({ queryKey: ["admin", "actions"] });
  };
  const approve = useMutation({
    mutationFn: () => guard(() => post(`/admin/v1/approvals/${a.id}/approve`, { note: note.trim() || null, confirm: true })),
    onSettled: done,
  });
  const reject = useMutation({ mutationFn: () => post(`/admin/v1/approvals/${a.id}/reject`, { note: note.trim() }), onSuccess: done });
  const cancel = useMutation({ mutationFn: () => post(`/admin/v1/approvals/${a.id}/cancel`), onSuccess: done });
  const st = STATUS[a.status];
  return (
    <div className="px-5 py-4" data-testid={`approval-${a.id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[12px] text-muted">#{a.id}</span>
        <span className="text-[13.5px] font-medium">{a.label}</span>
        <Badge tone={st.tone}>{st.label}</Badge>
        {a.mine && <Badge tone="cobalt">Sizin talebiniz</Badge>}
      </div>
      <p className="mt-1 text-[13px] text-text-2">{a.summary}</p>
      <div className="mt-1 text-[11.5px] text-muted">
        {a.requested_by ?? "?"} · {fmtDateTime(a.requested_at)} ({ago(a.requested_at)}) · izin: <span className="font-mono">{a.permission}</span>
        {a.status === "pending" && <> · son: {fmtDateTime(a.expires_at)}</>}
      </div>
      {a.decided_at && a.status !== "pending" && (
        <div className="mt-1 text-[11.5px] text-muted">
          Karar: {a.decided_by ?? "sistem (süre doldu)"} · {fmtDateTime(a.decided_at)}
          {a.decision_note && <> · “{a.decision_note}”</>}
          {a.status === "failed" && a.result && <> · neden: {String(a.result.detail ?? a.result.code)}</>}
        </div>
      )}
      {a.status === "pending" && (a.can_decide || a.mine) && (
        <div className="mt-3 space-y-2">
          {a.can_decide && (
            <input aria-label={`#${a.id} karar notu`} value={note} onChange={(e) => setNote(e.target.value)}
              placeholder="Not (reddetmek için zorunlu, en az 5 karakter)"
              className="h-8 w-full max-w-lg rounded-ctl border border-line bg-bg-elevated px-2 text-[12.5px]" />
          )}
          <div className="flex flex-wrap gap-2">
            {a.can_decide && (
              <>
                <Button size="sm" loading={approve.isPending}
                  onClick={() => { if (window.confirm(`#${a.id} onaylansın mı? İşlem hemen yürütülür: ${a.summary}`)) approve.mutate(); }}>Onayla ve yürüt</Button>
                <Button size="sm" variant="danger" disabled={note.trim().length < 5} loading={reject.isPending} onClick={() => reject.mutate()}>Reddet</Button>
              </>
            )}
            {a.mine && <Button size="sm" variant="ghost" loading={cancel.isPending} onClick={() => cancel.mutate()}>Talebi iptal et</Button>}
          </div>
          {a.mine && !a.can_decide && <p className="text-[11.5px] text-muted">Kendi talebinizi onaylayamazsınız; aynı izne sahip başka bir yönetici karar vermeli.</p>}
          <FormError error={approve.error ?? reject.error ?? cancel.error} />
        </div>
      )}
    </div>
  );
}

export default function Approvals() {
  const [tab, setTab] = useState<"pending" | "closed">("pending");
  const q = useQuery({
    queryKey: ["admin", "approvals", tab],
    queryFn: () => api<{ dual_control: boolean; items: Approval[] }>(`/admin/v1/approvals?status=${tab}`),
    // Başka sayfada açılan talep hemen görünsün: önbellekten değil, her açılışta sunucudan.
    staleTime: 0,
    refetchOnMount: "always",
    refetchInterval: 30_000,
  });
  return (
    <>
      <PageTitle eyebrow="Genel" title="Onaylar (dört göz)">
        <div className="flex gap-1 rounded-ctl border border-line p-0.5" role="tablist">
          {(["pending", "closed"] as const).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
              className={cx("rounded-[6px] px-3 py-1 text-[12.5px]", tab === t ? "bg-bg-elevated font-medium" : "text-muted")}>
              {t === "pending" ? "Bekleyen" : "Karara bağlanan"}
            </button>
          ))}
        </div>
      </PageTitle>
      <p className="-mt-3 mb-5 max-w-3xl text-[13px] text-muted">
        Kural açıkken iade, incelemedeki sipariş kararı, yönetici rolü değişikliği ve kuralın kapatılması hemen yürütülmez;
        aynı izne sahip <b>başka</b> bir yönetici onaylayınca, o anki durum yeniden denetlenerek yürütülür. Talepler 24 saatte düşer ve
        karara bağlandıktan sonra değiştirilemez.
      </p>
      {q.data && !q.data.dual_control && (
        <div className="mb-4"><Notice tone="neutral" title="Dört göz kuralı kapalı">Kritik işlemler tek yöneticiyle yürütülüyor. Açmak için Özellik Bayrakları → dual_control (en az iki yetkili yönetici gerekir).</Notice></div>
      )}
      {q.isLoading ? <Skeleton className="h-48" /> : q.error ? <Card><ErrorState error={q.error} /></Card> : !q.data?.items.length ? (
        <Card><Empty title={tab === "pending" ? "Bekleyen onay talebi yok" : "Karara bağlanmış talep yok"} /></Card>
      ) : (
        <Card className="divide-y divide-line">{q.data.items.map((a) => <Row key={`${a.id}-${a.status}`} a={a} />)}</Card>
      )}
    </>
  );
}
