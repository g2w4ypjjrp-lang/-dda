"use client";

import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";

import { PageTitle, Table } from "@/components/admin";
import { Badge, Card, CardHeader, Empty, ErrorState, Skeleton, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, fmtDateTime } from "@/lib/format";

interface Security {
  window_hours: number; counts: Record<string, number>; suspicious_ips: { ip: string; failures: number }[];
  staff: { total: number; mfa_enabled: number; items: { email: string; mfa: boolean; roles: string[] }[] };
  admin_sessions: { email: string; ip: string | null; last_seen_at: string; created_at: string; user_agent: string | null }[];
  events: { id: number; at: string; action: string; actor_type: string; ip: string | null }[];
  protections: string[];
}

const LABELS: Record<string, string> = {
  "auth.login_failed": "Başarısız giriş", "auth.mfa_failed": "Hatalı MFA kodu", "admin.login_failed": "Başarısız yönetici girişi",
  "admin.reauth_failed": "Başarısız yeniden doğrulama", "auth.password_reset_requested": "Parola sıfırlama isteği", "auth.password_changed": "Parola değişti",
  "auth.mfa_disabled": "MFA kapatıldı", "admin.roles_changed": "Rol değişikliği", "admin.user_suspended": "Hesap askıya alındı",
  "billing.license_redeem_failed": "Başarısız lisans denemesi", "billing.webhook_invalid_signature": "Geçersiz imzalı ödeme bildirimi",
};

export default function SecurityCenter() {
  const q = useQuery({ queryKey: ["admin", "security"], queryFn: () => api<Security>("/admin/v1/security"), refetchInterval: 60_000 });
  if (q.isLoading) return <><PageTitle eyebrow="Kullanıcı & Güvenlik" title="Güvenlik Merkezi" /><Skeleton className="h-96" /></>;
  if (q.error || !q.data) return <><PageTitle eyebrow="Kullanıcı & Güvenlik" title="Güvenlik Merkezi" /><Card><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card></>;
  const s = q.data;
  const c = (k: string) => s.counts[k] ?? 0;
  return (
    <div className="space-y-6">
      <PageTitle eyebrow="Kullanıcı & Güvenlik" title="Güvenlik Merkezi" />
      <Card className="grid grid-cols-2 gap-6 p-6 md:grid-cols-5">
        <Stat label="Başarısız giriş (24 s)" value={c("auth.login_failed") + c("admin.login_failed")} tone={c("auth.login_failed") + c("admin.login_failed") > 10 ? "red" : undefined} />
        <Stat label="Hatalı MFA (24 s)" value={c("auth.mfa_failed")} />
        <Stat label="Şüpheli IP" value={s.suspicious_ips.length} hint="24 saatte ≥3 başarısız deneme" tone={s.suspicious_ips.length ? "red" : undefined} />
        <Stat label="Yönetici MFA" value={`${s.staff.mfa_enabled}/${s.staff.total}`} tone={s.staff.mfa_enabled === s.staff.total ? "teal" : "red"} />
        <Stat label="Açık yönetici oturumu" value={s.admin_sessions.length} />
      </Card>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader eyebrow="24 saat" title="Şüpheli IP adresleri" />
          {s.suspicious_ips.length ? (
            <Table head={["IP", "Başarısız deneme"]} minWidth={320}>{s.suspicious_ips.map((i) => <tr key={i.ip}><td className="px-4 py-2 font-mono">{i.ip}</td><td className="num px-4 py-2">{i.failures}</td></tr>)}</Table>
          ) : <Empty title="Şüpheli IP yok" icon={<ShieldCheck className="size-5" aria-hidden />} />}
        </Card>
        <Card>
          <CardHeader eyebrow="Oturumlar" title="Açık yönetici oturumları" />
          <Table head={["Yönetici", "IP", "Son etkinlik"]} minWidth={420}>
            {s.admin_sessions.map((x, i) => <tr key={i}><td className="px-4 py-2">{x.email}</td><td className="px-4 py-2 font-mono">{x.ip ?? "—"}</td><td className="px-4 py-2">{ago(x.last_seen_at)}</td></tr>)}
          </Table>
        </Card>
      </div>
      <Card>
        <CardHeader eyebrow="Yönetim ekibi" title="Roller ve MFA" />
        <Table head={["E-posta", "Roller", "MFA"]} minWidth={520}>
          {s.staff.items.map((x) => <tr key={x.email}><td className="px-4 py-2">{x.email}</td><td className="px-4 py-2">{x.roles.join(", ")}</td><td className="px-4 py-2"><Badge tone={x.mfa ? "teal" : "red"}>{x.mfa ? "Açık" : "Kapalı"}</Badge></td></tr>)}
        </Table>
      </Card>
      <Card>
        <CardHeader eyebrow="Denetim kaydından" title="Son güvenlik olayları" />
        {s.events.length ? (
          <Table head={["Zaman", "Olay", "Aktör", "IP"]} minWidth={560}>
            {s.events.map((e) => <tr key={e.id}><td className="px-4 py-2">{fmtDateTime(e.at)}</td><td className="px-4 py-2">{LABELS[e.action] ?? e.action}</td><td className="px-4 py-2">{e.actor_type}</td><td className="px-4 py-2 font-mono">{e.ip ?? "—"}</td></tr>)}
          </Table>
        ) : <Empty title="Güvenlik olayı yok" />}
      </Card>
      <Card className="p-5">
        <div className="eyebrow mb-2">Etkin korumalar</div>
        <ul className="list-disc space-y-1 pl-5 text-[13px] text-text-2">{s.protections.map((p) => <li key={p}>{p}</li>)}</ul>
      </Card>
    </div>
  );
}
