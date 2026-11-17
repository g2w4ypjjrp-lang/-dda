"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PageTitle, RunStatus, Table, can, useAdmin, useGuard } from "@/components/admin";
import { Badge, Button, Card, CardHeader, Empty, FormError, Input, Notice, Skeleton } from "@/components/ui";
import { api, patch, post } from "@/lib/api";
import { ago, fmtDateTime, trToday } from "@/lib/format";

const JOBS = [
  { key: "fixtures_date", label: "Günün fikstürü", needs: ["date"] },
  { key: "live", label: "Canlı maçlar", needs: [] },
  { key: "upcoming_details", label: "Maç öncesi/sonrası ayrıntılar", needs: [] },
  { key: "standings_active", label: "Takip edilen liglerin puan durumu", needs: [] },
  { key: "standings", label: "Bir ligin puan durumu", needs: ["competition_id"] },
  { key: "season_backfill", label: "Sezon geçmişi yükle", needs: ["competition_id", "season"] },
  { key: "fixture_details", label: "Maç ayrıntısı", needs: ["fixture_id"] },
] as const;

interface Run { id: number; job: string; params: Record<string, unknown>; trigger: string; status: string; started_at: string; requests: number; items: number; message: string | null }
interface Competition { id: number; name: string; country: string | null; is_active: boolean }

export default function DataCenter() {
  const me = useAdmin();
  const qc = useQueryClient();
  const guard = useGuard();
  const manage = can(me, "football.manage");
  const [job, setJob] = useState<(typeof JOBS)[number]["key"]>("fixtures_date");
  const [params, setParams] = useState<Record<string, string>>({ date: trToday() });
  const [q, setQ] = useState("");

  const runs = useQuery({ queryKey: ["admin", "sync-runs"], queryFn: () => api<{ items: Run[] }>("/admin/v1/football/sync-runs?limit=50"), refetchInterval: 20_000 });
  const comps = useQuery({ queryKey: ["admin", "competitions", q], queryFn: () => api<{ items: Competition[] }>(`/v1/football/competitions?active_only=false&q=${encodeURIComponent(q)}`) });
  const trigger = useMutation({
    mutationFn: () => {
      const spec = JOBS.find((j) => j.key === job)!;
      const body: Record<string, unknown> = { job };
      for (const k of spec.needs) body[k] = k === "date" ? params[k] : Number(params[k]);
      return guard(() => post<{ status: string; message: string | null; items: number; requests: number }>("/admin/v1/football/sync", body));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin"] }),
  });
  const toggle = useMutation({
    mutationFn: (c: Competition) => guard(() => patch(`/admin/v1/football/competitions/${c.id}`, { is_active: !c.is_active })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "competitions"] }),
  });
  const spec = JOBS.find((j) => j.key === job)!;

  return (
    <div>
      <PageTitle eyebrow="Futbol Veri Merkezi" title="Veri işleri ve ligler" />
      <div className="grid gap-6 xl:grid-cols-[1fr_1.2fr]">
        <Card>
          <CardHeader eyebrow="Elle çalıştır" title="Senkronizasyon işi" />
          <form className="space-y-4 p-5" onSubmit={(e) => { e.preventDefault(); trigger.mutate(); }}>
            <label className="block">
              <span className="mb-1.5 block text-[13px] font-medium text-text-2">İş</span>
              <select value={job} onChange={(e) => setJob(e.target.value as typeof job)} className="h-11 w-full rounded-ctl border border-line-strong bg-bg-elevated px-3 text-sm">
                {JOBS.map((j) => <option key={j.key} value={j.key}>{j.label}</option>)}
              </select>
            </label>
            {spec.needs.map((k) => (
              <Input
                key={k}
                label={{ date: "Tarih (UTC günü)", competition_id: "Lig kimliği", season: "Sezon (başlangıç yılı)", fixture_id: "Maç kimliği" }[k]}
                name={k}
                type={k === "date" ? "date" : "number"}
                value={params[k] ?? ""}
                onChange={(e) => setParams({ ...params, [k]: e.target.value })}
              />
            ))}
            {trigger.data && (
              <Notice tone={trigger.data.status === "succeeded" ? "teal" : trigger.data.status === "failed" ? "red" : "amber"}>
                {trigger.data.status === "succeeded" ? `Tamamlandı: ${trigger.data.items} kayıt, ${trigger.data.requests} istek.` : trigger.data.message}
              </Notice>
            )}
            <FormError error={trigger.error} />
            <Button type="submit" loading={trigger.isPending} disabled={!manage}>{manage ? "Çalıştır" : "Yetki yok (football.manage)"}</Button>
          </form>
        </Card>

        <Card>
          <CardHeader eyebrow="Kapsam" title="Ligler" action={<Badge>{comps.data?.items.filter((c) => c.is_active).length ?? 0} takipte</Badge>} />
          <div className="p-5 pb-2"><Input label="Ara" name="comp-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Lig adı" /></div>
          <ul className="max-h-[360px] divide-y divide-line overflow-y-auto">
            {comps.isLoading ? <Skeleton className="m-5 h-20" /> : comps.data?.items.length === 0 ? (
              <Empty title="Henüz lig yok">Lig kayıtları ilk fikstür eşitlemesiyle oluşur.</Empty>
            ) : comps.data?.items.map((c) => (
              <li key={c.id} className="flex items-center gap-3 px-5 py-2.5 text-[13px]">
                <span className="flex-1 truncate">{c.name} <span className="text-muted">· {c.country ?? "—"} · #{c.id}</span></span>
                <Button size="sm" variant={c.is_active ? "secondary" : "ghost"} disabled={!manage} loading={toggle.isPending && toggle.variables?.id === c.id} onClick={() => toggle.mutate(c)}>
                  {c.is_active ? "Takipte" : "Takibe al"}
                </Button>
              </li>
            ))}
          </ul>
          <FormError error={toggle.error} />
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader eyebrow="Kayıt" title="Senkronizasyon geçmişi" />
        <div className="mt-3 border-t border-line">
          {runs.isLoading ? <Skeleton className="m-5 h-32" /> : runs.data?.items.length === 0 ? <Empty title="Henüz iş çalışmadı" /> : (
            <Table head={["Durum", "İş", "Tetikleyen", "Başlangıç", "İstek", "Kayıt", "Mesaj"]}>
              {runs.data?.items.map((r) => (
                <tr key={r.id} className="hover:bg-surface-2">
                  <td className="px-4 py-2.5"><RunStatus s={r.status} /></td>
                  <td className="px-4 py-2.5 font-medium">{r.job}</td>
                  <td className="px-4 py-2.5 text-text-2">{r.trigger}</td>
                  <td className="px-4 py-2.5 text-text-2" title={fmtDateTime(r.started_at)}>{ago(r.started_at)}</td>
                  <td className="num px-4 py-2.5">{r.requests}</td>
                  <td className="num px-4 py-2.5">{r.items}</td>
                  <td className="max-w-[320px] truncate px-4 py-2.5 text-muted" title={r.message ?? ""}>{r.message ?? "—"}</td>
                </tr>
              ))}
            </Table>
          )}
        </div>
      </Card>
    </div>
  );
}
