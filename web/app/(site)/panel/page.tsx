"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LogOut, Monitor, ShieldAlert, ShieldCheck, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import QRCode from "qrcode";
import { useEffect, useState } from "react";

import { MatchRow } from "@/components/match";
import { Badge, Button, Card, CardHeader, Empty, FormError, Input, Skeleton, Stat } from "@/components/ui";
import { api, post } from "@/lib/api";
import { ago, fmtDateTime, trToday } from "@/lib/format";
import { useLogout, useMe } from "@/lib/hooks";
import type { FixtureList, Me, Prediction } from "@/lib/types";

function MfaCard({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [setup, setSetup] = useState<{ uri: string; secret: string; qr: string } | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const start = async () => {
    setError(null);
    setBusy(true);
    try {
      const r = await post<{ otpauth_uri: string; secret: string }>("/v1/auth/mfa/setup");
      const qr = await QRCode.toDataURL(r.otpauth_uri, { margin: 1, width: 180, color: { dark: "#0a0b0d", light: "#ffffff" } });
      setSetup({ uri: r.otpauth_uri, secret: r.secret, qr });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const enable = async () => {
    setError(null);
    setBusy(true);
    try {
      const r = await post<{ recovery_codes: string[] }>("/v1/auth/mfa/enable", { code });
      setCodes(r.recovery_codes);
      setSetup(null);
      await qc.invalidateQueries({ queryKey: ["me"] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader
        eyebrow="Güvenlik"
        title="İki adımlı doğrulama"
        action={me.mfa_enabled ? <Badge tone="teal"><ShieldCheck className="size-3" aria-hidden />Açık</Badge> : <Badge tone="amber"><ShieldAlert className="size-3" aria-hidden />Kapalı</Badge>}
      />
      <div className="space-y-4 p-5">
        {codes ? (
          <div>
            <p className="text-[13px] text-text-2">Kurtarma kodlarınızı güvenli bir yere kaydedin. Her biri bir kez kullanılabilir ve <strong className="text-text">bir daha gösterilmez</strong>.</p>
            <div className="num mt-3 grid grid-cols-2 gap-2 rounded-ctl border border-line bg-bg-elevated p-3 font-mono text-[13px]">
              {codes.map((c) => <span key={c}>{c}</span>)}
            </div>
          </div>
        ) : me.mfa_enabled ? (
          <p className="text-[13px] text-text-2">Girişte doğrulama uygulamanızdaki kod istenir.{me.staff_roles.length ? " Yönetici hesaplarında kapatılamaz." : ""}</p>
        ) : setup ? (
          <div className="grid gap-5 sm:grid-cols-[auto_1fr]">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={setup.qr} alt="Doğrulama uygulaması için QR kodu" width={180} height={180} className="rounded-ctl" />
            <div className="space-y-3">
              <p className="text-[13px] text-text-2">QR kodu doğrulama uygulamanızla tarayın veya anahtarı elle girin:</p>
              <code className="block break-all rounded-ctl border border-line bg-bg-elevated px-3 py-2 font-mono text-[12px]">{setup.secret}</code>
              <Input label="Uygulamadaki 6 haneli kod" name="mfa-code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
              <Button onClick={enable} loading={busy} disabled={code.length < 6}>Etkinleştir</Button>
            </div>
          </div>
        ) : (
          <>
            <p className="text-[13px] text-text-2">Hesabınızı parolanın ötesinde korumak için doğrulama uygulaması (Google Authenticator, 1Password vb.) ekleyin.</p>
            <Button variant="secondary" onClick={start} loading={busy}><KeyRound className="size-4" aria-hidden />Kurulumu başlat</Button>
          </>
        )}
        <FormError error={error} />
      </div>
    </Card>
  );
}

function SessionsCard() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["sessions"],
    queryFn: () => api<{ items: { id: string; scope: string; current: boolean; last_seen_at: string; ip: string | null; user_agent: string | null }[] }>("/v1/auth/sessions"),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => post(`/v1/auth/sessions/${id}/revoke`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });
  return (
    <Card>
      <CardHeader eyebrow="Güvenlik" title="Açık oturumlar" />
      <ul className="divide-y divide-line p-2">
        {q.isLoading && <Skeleton className="m-3 h-10" />}
        {q.data?.items.map((s) => (
          <li key={s.id} className="flex items-center gap-3 px-3 py-2.5 text-[12.5px]">
            <Monitor className="size-4 shrink-0 text-muted" aria-hidden />
            <div className="min-w-0 flex-1">
              <div className="truncate text-text-2">{s.user_agent ?? "Bilinmeyen cihaz"}</div>
              <div className="text-[11px] text-muted">{s.ip ?? "—"} · {ago(s.last_seen_at)}{s.scope === "admin" ? " · yönetim" : ""}</div>
            </div>
            {s.current ? <Badge tone="teal">Bu cihaz</Badge> : <Button size="sm" variant="ghost" loading={revoke.isPending && revoke.variables === s.id} onClick={() => revoke.mutate(s.id)}>Kapat</Button>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function DeleteAccount({ me }: { me: Me }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  if (me.staff_roles.length) return null;
  return (
    <Card>
      <CardHeader eyebrow="KVKK" title="Hesabı sil" />
      <div className="space-y-3 p-5">
        <p className="text-[12.5px] leading-relaxed text-muted">Kişisel bilgileriniz anonimleştirilir ve tüm oturumlar kapatılır. Bu işlem geri alınamaz.</p>
        {!open ? (
          <Button variant="danger" size="sm" onClick={() => setOpen(true)}><Trash2 className="size-4" aria-hidden />Hesabımı sil</Button>
        ) : (
          <div className="space-y-3">
            <Input label="Parola" type="password" name="delete-password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            {me.mfa_enabled && <Input label="Doğrulama kodu" name="delete-code" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />}
            <FormError error={error} />
            <div className="flex gap-2">
              <Button
                variant="danger"
                size="sm"
                loading={busy}
                onClick={async () => {
                  setBusy(true);
                  setError(null);
                  try {
                    await post("/v1/auth/delete-account", { password, ...(me.mfa_enabled ? { code } : {}) });
                    await qc.invalidateQueries({ queryKey: ["me"] });
                    router.push("/");
                  } catch (e) {
                    setError(e);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Kalıcı olarak sil
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Vazgeç</Button>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

export default function PanelPage() {
  const router = useRouter();
  const { data: me, isLoading } = useMe();
  const logout = useLogout();
  const day = trToday();
  const fixtures = useQuery({ queryKey: ["fixtures", day], queryFn: () => api<FixtureList>(`/v1/football/fixtures?date=${day}`), enabled: !!me });
  const predictions = useQuery({ queryKey: ["predictions", day], queryFn: () => api<{ items: Prediction[] }>(`/v1/predictions?date=${day}`), enabled: !!me });

  useEffect(() => {
    if (!isLoading && me === null) router.replace("/giris?next=/panel");
  }, [isLoading, me, router]);

  if (isLoading || !me) return <div className="space-y-4 py-8"><Skeleton className="h-28" /><Skeleton className="h-64" /></div>;
  const byFixture = new Map((predictions.data?.items ?? []).map((p) => [p.fixture_id, p]));
  const items = fixtures.data?.items ?? [];

  return (
    <div className="py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow mb-2">Panelim</div>
          <h1 className="text-[28px] font-semibold tracking-tight">Merhaba, {me.display_name}</h1>
        </div>
        <Button variant="ghost" size="sm" onClick={async () => { await logout(); router.push("/"); }}>
          <LogOut className="size-4" aria-hidden />Çıkış
        </Button>
      </div>

      <Card className="mt-6 grid grid-cols-2 gap-6 p-6 md:grid-cols-4">
        <Stat label="Üyelik" value="FREE" hint="Ücretli paketler yakında" />
        <Stat label="E-posta" value={me.email_verified ? "Doğrulandı" : "Bekliyor"} tone={me.email_verified ? "teal" : undefined} hint={me.email} />
        <Stat label="İki adımlı doğrulama" value={me.mfa_enabled ? "Açık" : "Kapalı"} tone={me.mfa_enabled ? "teal" : "red"} />
        <Stat label="Üyelik tarihi" value={fmtDateTime(me.created_at).split(" ").slice(0, 2).join(" ")} />
      </Card>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader eyebrow="Bugün" title="Günün maçları" />
          <div className="mt-3 divide-y divide-line border-t border-line">
            {fixtures.isLoading ? <Skeleton className="m-5 h-24" /> : items.length === 0 ? (
              <Empty title="Bugün maç yok veya veri henüz gelmedi" />
            ) : items.slice(0, 10).map((f) => <MatchRow key={f.id} fixture={f} prediction={byFixture.get(f.id)} />)}
          </div>
        </Card>
        <div className="space-y-6">
          <MfaCard me={me} />
          <SessionsCard />
          <DeleteAccount me={me} />
        </div>
      </div>
    </div>
  );
}
