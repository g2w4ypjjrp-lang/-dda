"use client";

import { useQuery } from "@tanstack/react-query";

import { PageTitle, Table, can, useAdmin } from "@/components/admin";
import { Badge, Card, CardHeader, Empty, ErrorState, Skeleton, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, fmtDateTime, pct } from "@/lib/format";

interface Window { minutes: number; requests: number; errors_5xx: number; error_rate: number | null; avg_ms: number | null; max_ms: number | null }
interface Health {
  status: string; checked_at: string; environment: string;
  components: Record<string, { status: string; detail?: string; latency_ms?: number; depth?: number; last_heartbeat?: string; provider?: string; test_mode?: boolean; schema?: string; error?: string; window?: Window; last_5m?: Window; last_run?: { job: string; status: string; at: string; message: string | null } | null }>;
  host: { scope: string; cpu: { cores: number; load_1m: number; load_pct: number } | null; memory: { total_bytes: number; used_pct: number } | null; disk: { total_bytes: number; used_pct: number } };
  costs: { note: string };
}
interface Err { ts: number; method: string; path: string; status: number; request_id: string }

const TONE: Record<string, "teal" | "amber" | "red" | "neutral"> = { ok: "teal", degraded: "amber", down: "red", not_configured: "neutral", unknown: "neutral" };
const LABEL: Record<string, string> = { ok: "Çalışıyor", degraded: "Sorunlu", down: "Çalışmıyor", not_configured: "Bağlı değil", unknown: "Bilinmiyor" };
const NAMES: Record<string, string> = { database: "PostgreSQL", redis: "Redis", queue: "Kuyruk", workers: "İşçiler (Celery)", scheduler: "Zamanlayıcı (beat)", football_api: "Futbol API", payment_api: "Ödeme API", backend: "Backend (API)" };
const gb = (b: number) => `${(b / 1024 ** 3).toFixed(1)} GB`;

function detail(c: Health["components"][string]) {
  const parts: string[] = [];
  if (c.latency_ms !== undefined) parts.push(`${c.latency_ms} ms`);
  if (c.schema) parts.push(`şema ${c.schema}`);
  if (c.depth !== undefined) parts.push(`${c.depth} iş bekliyor`);
  if (c.last_heartbeat) parts.push(`son kalp atışı ${ago(c.last_heartbeat)}`);
  if (c.provider) parts.push(c.provider + (c.test_mode ? " (test)" : ""));
  if (c.last_run) parts.push(`son iş ${c.last_run.job}: ${c.last_run.status} ${ago(c.last_run.at)}`);
  if (c.error) parts.push(c.error);
  if (c.detail) parts.push(c.detail);
  return parts.join(" · ") || "—";
}

export default function SystemHealth() {
  const me = useAdmin();
  const q = useQuery({ queryKey: ["admin", "health"], queryFn: () => api<Health>("/admin/v1/health"), refetchInterval: 30_000 });
  const errors = useQuery({ queryKey: ["admin", "errors"], queryFn: () => api<{ items: Err[] }>("/admin/v1/health/errors?limit=50"), enabled: can(me, "logs.read"), refetchInterval: 30_000 });
  const settings = useQuery({ queryKey: ["admin", "settings"], queryFn: () => api<Record<string, unknown>>("/admin/v1/settings"), enabled: can(me, "settings.read") });
  if (q.isLoading) return <><PageTitle eyebrow="Platform" title="Sistem Sağlığı" /><Skeleton className="h-96" /></>;
  if (q.error || !q.data) return <><PageTitle eyebrow="Platform" title="Sistem Sağlığı" /><Card><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card></>;
  const h = q.data;
  const be = h.components.backend;
  return (
    <div className="space-y-6">
      <PageTitle eyebrow="Platform" title="Sistem Sağlığı"><Badge tone={TONE[h.status]}>{LABEL[h.status] ?? h.status}</Badge></PageTitle>
      <Card className="grid grid-cols-2 gap-6 p-6 md:grid-cols-5">
        <Stat label="Frontend" value="Çalışıyor" hint="Bu sayfayı sunuyor" tone="teal" />
        <Stat label="İstek (60 dk)" value={be?.window?.requests ?? "—"} hint={be?.last_5m ? `${be.last_5m.requests} son 5 dk` : undefined} />
        <Stat label="Hata oranı (5xx)" value={be?.window?.error_rate === null || be?.window?.error_rate === undefined ? "Veri yok" : pct(be.window.error_rate, 2)} tone={be?.window?.errors_5xx ? "red" : undefined} />
        <Stat label="Ort. yanıt süresi" value={be?.window?.avg_ms == null ? "Veri yok" : `${be.window.avg_ms} ms`} hint={be?.window?.max_ms != null ? `en uzun ${be.window.max_ms} ms` : undefined} />
        <Stat label="Ortam" value={h.environment} hint={`Kontrol ${ago(h.checked_at)}`} />
      </Card>
      <Card>
        <CardHeader eyebrow="Bileşenler" title="Servis durumu" />
        <Table head={["Bileşen", "Durum", "Ayrıntı"]} minWidth={640}>
          {Object.entries(h.components).filter(([k]) => k !== "backend").map(([k, c]) => (
            <tr key={k}><td className="px-4 py-2.5 font-medium">{NAMES[k] ?? k}</td><td className="px-4 py-2.5"><Badge tone={TONE[c.status]}>{LABEL[c.status] ?? c.status}</Badge></td><td className="px-4 py-2.5 text-text-2">{detail(c)}</td></tr>
          ))}
        </Table>
      </Card>
      <Card>
        <CardHeader eyebrow={h.host.scope} title="Kaynaklar" />
        <div className="grid grid-cols-2 gap-6 p-5 md:grid-cols-4">
          <Stat label="CPU yükü" value={h.host.cpu ? `%${h.host.cpu.load_pct}` : "Veri yok"} hint={h.host.cpu ? `${h.host.cpu.cores} çekirdek · 1 dk ort. ${h.host.cpu.load_1m}` : undefined} />
          <Stat label="RAM" value={h.host.memory ? `%${h.host.memory.used_pct}` : "Veri yok"} hint={h.host.memory ? gb(h.host.memory.total_bytes) : undefined} />
          <Stat label="Disk" value={`%${h.host.disk.used_pct}`} hint={gb(h.host.disk.total_bytes)} />
          <Stat label="API / sunucu maliyeti" value="Veri yok" hint={h.costs.note} />
        </div>
      </Card>
      {can(me, "logs.read") && (
        <Card>
          <CardHeader eyebrow="Log Merkezi" title="Son sunucu hataları (5xx)" />
          {errors.data?.items.length ? (
            <Table head={["Zaman", "İstek", "Durum", "İstek kimliği"]} minWidth={640}>
              {errors.data.items.map((e, i) => (
                <tr key={i}><td className="px-4 py-2">{fmtDateTime(new Date(e.ts * 1000).toISOString())}</td><td className="px-4 py-2 font-mono">{e.method} {e.path}</td><td className="px-4 py-2"><Badge tone="red">{e.status}</Badge></td><td className="px-4 py-2 font-mono text-muted">{e.request_id}</td></tr>
              ))}
            </Table>
          ) : <Empty title="Kayıtlı sunucu hatası yok">Son 200 hata tutulur; istek gövdesi ve kullanıcı bilgisi yazılmaz.</Empty>}
        </Card>
      )}
      {settings.data && (
        <Card>
          <CardHeader eyebrow="Sistem Ayarları" title="Yapılandırma (salt okunur)" />
          <dl className="grid gap-x-6 gap-y-2 p-5 text-[12.5px] sm:grid-cols-2">
            {Object.entries(settings.data).filter(([k]) => k !== "note").map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3 border-b border-line py-1.5"><dt className="text-muted">{k}</dt><dd className="truncate font-mono">{Array.isArray(v) ? v.join(", ") : String(v)}</dd></div>
            ))}
          </dl>
          <p className="px-5 pb-4 text-[11.5px] text-muted">{String(settings.data.note)}</p>
        </Card>
      )}
    </div>
  );
}
