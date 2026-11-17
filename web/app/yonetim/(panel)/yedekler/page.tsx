"use client";

import { useQuery } from "@tanstack/react-query";

import { PageTitle, Table } from "@/components/admin";
import { Badge, Card, CardHeader, Empty, ErrorState, Notice, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, fmtDateTime } from "@/lib/format";

interface Verify {
  ok?: boolean;
  sha256_ok?: boolean;
  file_present?: boolean;
  archive_ok?: boolean;
  restore_tested?: boolean;
  restore_ok?: boolean;
  reason?: string;
  error?: string;
  tables?: number;
  alembic_version?: string;
  audit_chain_intact?: boolean;
  rows?: Record<string, number>;
}
interface BackupRow {
  id: number;
  created_at: string;
  file_name: string;
  size_bytes: number | null;
  sha256: string | null;
  status: "ok" | "failed" | "pruned";
  duration_ms: number | null;
  error: string | null;
  verified_at: string | null;
  verify_ok: boolean | null;
  verify: Verify | null;
  trigger: "cli" | "schedule";
}

const size = (b: number | null) =>
  b === null ? "—" : b >= 1 << 30 ? `${(b / (1 << 30)).toFixed(2)} GB` : b >= 1 << 20 ? `${(b / (1 << 20)).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;

function VerifyCell({ r }: { r: BackupRow }) {
  if (r.status === "failed") return <span className="text-[12px] text-red">{r.error?.slice(0, 120)}</span>;
  if (r.verify_ok === null || !r.verify) return <span className="text-muted">Doğrulanmadı</span>;
  const v = r.verify;
  const detail = !v.file_present ? "dosya yok"
    : !v.sha256_ok ? "özet tutmuyor (dosya bozuk/değişmiş)"
    : !v.restore_tested ? (v.reason ?? "geri yükleme denenmedi")
    : !v.restore_ok ? `geri yüklenemedi: ${v.error ?? ""}`
    : `${v.tables} tablo · şema ${v.alembic_version} · denetim zinciri ${v.audit_chain_intact ? "sağlam" : "KIRIK"}`;
  return (
    <span className="text-[12px]">
      <Badge tone={r.verify_ok ? "teal" : "red"}>{r.verify_ok ? "Geri yüklendi, sağlam" : "Başarısız"}</Badge>
      <span className="ml-2 text-muted">{detail} · {ago(r.verified_at)}</span>
    </span>
  );
}

export default function Backups() {
  const q = useQuery({
    queryKey: ["admin", "backups"],
    queryFn: () => api<{ configured: boolean; keep: number; schedule: string; items: BackupRow[] }>("/admin/v1/backups"),
  });
  const d = q.data;
  const lastOk = d?.items.find((r) => r.status !== "failed");
  return (
    <>
      <PageTitle eyebrow="Platform" title="Yedekler" />
      <p className="-mt-3 mb-5 max-w-3xl text-[13px] text-muted">
        Her yedek alındıktan sonra geçici bir veritabanına gerçekten geri yüklenir ve orada şema sürümü, tablolar ve denetim
        kaydının hash zinciri denetlenir. Yedek almak ve geri yüklemek yalnızca sunucuda komut satırından yapılır (panelden
        veritabanı üzerine yazılamaz).
      </p>
      {q.isLoading ? <Skeleton className="h-48" /> : q.error ? <Card><ErrorState error={q.error} /></Card> : d && (
        <>
          {!d.configured ? (
            <Notice tone="amber" title="Yedekleme yapılandırılmamış">
              MI_BACKUP_DIR ayarlanmadan yedek alınmaz. Üretimde bu dizin ayrı bir diske veya bölgeye eşitlenmelidir.
            </Notice>
          ) : (
            <Card className="grid grid-cols-1 gap-4 p-5 text-[13px] sm:grid-cols-3">
              <div><div className="text-[11.5px] text-muted">Zamanlama</div>{d.schedule}</div>
              <div><div className="text-[11.5px] text-muted">Saklanan</div>Son {d.keep} başarılı yedek</div>
              <div><div className="text-[11.5px] text-muted">Son başarılı yedek</div>{lastOk ? `${fmtDateTime(lastOk.created_at)} (${ago(lastOk.created_at)})` : "Henüz yok"}</div>
            </Card>
          )}
          <Card className="mt-6">
            <CardHeader eyebrow="Kayıtlar" title="Yedek geçmişi" />
            {!d.items.length ? <Empty title="Henüz yedek kaydı yok" /> : (
              <Table head={["No", "Zaman", "Dosya", "Boyut", "Durum", "Doğrulama"]} minWidth={900}>
                {d.items.map((r) => (
                  <tr key={r.id} data-testid={`backup-${r.id}`}>
                    <td className="num px-4 py-2.5">#{r.id}</td>
                    <td className="px-4 py-2.5">{fmtDateTime(r.created_at)}<div className="text-[11px] text-muted">{r.trigger === "schedule" ? "zamanlanmış" : "komut satırı"}{r.duration_ms !== null && ` · ${(r.duration_ms / 1000).toFixed(1)} sn`}</div></td>
                    <td className="px-4 py-2.5 font-mono text-[11.5px]" title={r.sha256 ?? undefined}>{r.file_name}<div className="text-muted">{r.sha256 ? `sha256 ${r.sha256.slice(0, 12)}…` : ""}</div></td>
                    <td className="num px-4 py-2.5">{size(r.size_bytes)}</td>
                    <td className="px-4 py-2.5"><Badge tone={r.status === "ok" ? "teal" : r.status === "failed" ? "red" : "neutral"}>{r.status === "ok" ? "Hazır" : r.status === "failed" ? "Başarısız" : "Budandı"}</Badge></td>
                    <td className="px-4 py-2.5"><VerifyCell r={r} /></td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
          <Card className="mt-6 p-5 text-[12.5px]">
            <div className="mb-2 font-medium">Komut satırı (sunucuda)</div>
            <pre className="overflow-x-auto rounded-ctl bg-bg-elevated p-3 font-mono text-[12px] leading-relaxed">{`mi-admin backup                     # yedek al + geri yükleyerek doğrula
mi-admin backup-verify [--id N]     # bir yedeği yeniden doğrula
mi-admin restore DOSYA --target-url URL --yes   # ayrı bir veritabanına geri yükle`}</pre>
            <p className="mt-2 text-muted">Ayrıntılı adımlar: docs/calistirma-kilavuzu.md → “Yedekten geri dönüş”.</p>
          </Card>
        </>
      )}
    </>
  );
}
