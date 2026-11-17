"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, RotateCcw, Wallet } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Area, Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useLayout } from "@/components/design";

import { Badge, Button, Card, CardHeader, Empty, ErrorState, FormError, Notice, Skeleton, Stat } from "@/components/ui";
import { ApiError, api, post, put } from "@/lib/api";
import { fmtDateTime, pct, sb } from "@/lib/format";
import { useMe } from "@/lib/hooks";

type Settings = { method: "fixed" | "percent" | "kelly"; fixed_minor: number; percent: number; kelly_fraction: number; max_stake_pct: number; daily_risk_pct: number; max_daily_tickets: number };
interface Account { balance_minor: number; starting_balance_minor: number; settings: Settings; pending_settings: Settings | null; pending_effective_at: string | null; reset_count: number; disclaimer: string }
interface Ticket { id: number; coupon_id: number; created_at: string; stake_minor: number; odds: number; odds_source: string; odds_note: string; model_probability: number; model_ev: number | null; status: string; payout_minor: number | null }
interface Report {
  balance_minor: number; net_minor: number; simulated_roi: number | null; win_rate: number | null; max_drawdown: number | null;
  average_odds: number | null; mean_model_probability: number | null; reset_count: number;
  tickets: { total: number; pending: number; won: number; lost: number; void: number };
  balance_series: { at: string; balance_minor: number; kind: string }[]; label: string; disclaimer: string;
}

const STATUS = { pending: { tone: "neutral", label: "Bekliyor" }, won: { tone: "teal", label: "Kazandı" }, lost: { tone: "red", label: "Kaybetti" }, void: { tone: "amber", label: "İade" } } as const;
const METHODS = { fixed: "Sabit tutar", percent: "Bakiyenin yüzdesi", kelly: "Kesirli Kelly" } as const;

function OpenAccount() {
  const qc = useQueryClient();
  const [accept, setAccept] = useState(false);
  const open = useMutation({ mutationFn: () => post("/v1/virtual/account", { accept: true }), onSuccess: () => qc.invalidateQueries({ queryKey: ["virtual"] }) });
  return (
    <Card className="mt-6">
      <Empty title="Sanal portföy oluşturun" icon={<Wallet className="size-5" aria-hidden />}>
        10.000 SB sanal bakiyeyle başlarsınız. Kuponlarınızı gerçek para olmadan simüle edip modelin ve kararlarınızın nasıl sonuç verdiğini izlersiniz.
      </Empty>
      <div className="mx-auto max-w-md space-y-4 px-6 pb-8">
        <label className="flex items-start gap-2.5 text-[12.5px] leading-relaxed text-text-2">
          <input type="checkbox" className="mt-0.5 size-4 accent-[var(--mi-gold)]" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
          Sanal birimin (SB) gerçek para olmadığını; çekilemeyeceğini, transfer edilemeyeceğini ve satın alınamayacağını anladım.
        </label>
        <FormError error={open.error} />
        <Button className="w-full" disabled={!accept} loading={open.isPending} onClick={() => open.mutate()}>Sanal portföyü aç</Button>
      </div>
    </Card>
  );
}

function SettingsCard({ account }: { account: Account }) {
  const qc = useQueryClient();
  const [s, setS] = useState<Settings>(account.settings);
  useEffect(() => setS(account.settings), [account.settings]);
  const save = useMutation({
    mutationFn: () => put<{ applied: boolean; detail: string }>("/v1/virtual/settings", s),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["virtual"] }),
  });
  const num = (k: keyof Settings, label: string, step: number, scale = 1) => (
    <label className="block">
      <span className="mb-1 block text-[12px] text-text-2">{label}</span>
      <input type="number" step={step} value={Number(s[k]) / scale} onChange={(e) => setS({ ...s, [k]: Number(e.target.value) * scale })}
        className="num h-10 w-full rounded-ctl border border-line-strong bg-bg-elevated px-3 text-sm" />
    </label>
  );
  return (
    <Card>
      <CardHeader eyebrow="Risk yönetimi" title="Tutar ve sınırlar" />
      <div className="space-y-4 p-5">
        <label className="block">
          <span className="mb-1 block text-[12px] text-text-2">Tutar yöntemi</span>
          <select value={s.method} onChange={(e) => setS({ ...s, method: e.target.value as Settings["method"] })} className="h-10 w-full rounded-ctl border border-line-strong bg-bg-elevated px-3 text-sm">
            {Object.entries(METHODS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <div className="grid grid-cols-2 gap-3">
          {s.method === "fixed" && num("fixed_minor", "Sabit tutar (SB)", 1, 100)}
          {s.method === "percent" && num("percent", "Bakiye yüzdesi (%)", 0.1)}
          {s.method === "kelly" && num("kelly_fraction", "Kelly kesri", 0.05)}
          {num("max_stake_pct", "Tek bilet üst sınırı (%)", 0.5)}
          {num("daily_risk_pct", "Günlük risk sınırı (%)", 1)}
          {num("max_daily_tickets", "Günlük bilet sınırı", 1)}
        </div>
        {s.method === "kelly" && <p className="text-[11.5px] text-muted">Kelly yalnızca girdiğiniz oran modele göre avantaj sağlıyorsa tutar önerir; model adil oranında işlem önermez.</p>}
        {account.pending_settings && account.pending_effective_at && (
          <Notice tone="amber">Riski artıran ayarlarınız {fmtDateTime(account.pending_effective_at)} itibarıyla geçerli olacak (kayıp kovalamaya karşı bekleme).</Notice>
        )}
        {save.data && <Notice tone={save.data.applied ? "teal" : "amber"}>{save.data.detail}</Notice>}
        <FormError error={save.error} />
        <Button variant="secondary" loading={save.isPending} onClick={() => save.mutate()}>Kaydet</Button>
      </div>
    </Card>
  );
}

export default function VirtualPortfolio() {
  const layout = useLayout();
  const { data: me, isLoading: meLoading } = useMe();
  const qc = useQueryClient();
  const account = useQuery({
    queryKey: ["virtual", "account"],
    enabled: !!me,
    queryFn: async () => {
      try {
        return await api<Account>("/v1/virtual/account");
      } catch (e) {
        if (e instanceof ApiError && e.code === "no_account") return null;
        throw e;
      }
    },
  });
  const report = useQuery({ queryKey: ["virtual", "report"], queryFn: () => api<Report>("/v1/virtual/report"), enabled: !!account.data });
  const tickets = useQuery({ queryKey: ["virtual", "tickets"], queryFn: () => api<{ items: Ticket[] }>("/v1/virtual/tickets"), enabled: !!account.data });
  const reset = useMutation({ mutationFn: () => post("/v1/virtual/reset"), onSuccess: () => qc.invalidateQueries({ queryKey: ["virtual"] }) });

  const r = report.data;
  return (
    <div className="py-8">
      <div className="eyebrow mb-2">Sanal Portföy</div>
      <h1 className="text-[28px] font-semibold tracking-tight">Gerçek para olmadan simülasyon</h1>
      <p className="mt-2 max-w-2xl text-[13.5px] leading-relaxed text-muted">
        Kuponlarınızı sanal birimle (SB) izleyin. Sonuçlar simülasyondur; gerçek kazanç değildir. Kayıpları telafi etmek için
        tutarı artırmak risk yönetiminde hatadır — bu yüzden riski artıran ayarlar ertesi gün geçerli olur.
      </p>

      {meLoading || (me && account.isLoading) ? <Skeleton className="mt-6 h-48" /> : !me ? (
        <Card className="mt-6"><Empty title="Sanal portföy için giriş yapın"><Link href="/giris?next=/sanal" className="text-gold hover:underline">Giriş yapın</Link></Empty></Card>
      ) : account.isError ? (
        <Card className="mt-6"><ErrorState error={account.error} onRetry={() => account.refetch()} /></Card>
      ) : !account.data ? (
        <OpenAccount />
      ) : (
        <>
          <Card className="mt-6 grid grid-cols-2 gap-6 p-6 md:grid-cols-5">
            <Stat label="Sanal bakiye" value={sb(account.data.balance_minor)} hint={`Başlangıç ${sb(account.data.starting_balance_minor)}`} />
            <Stat label="Net (simüle)" value={sb(r?.net_minor)} tone={r && r.net_minor < 0 ? "red" : r && r.net_minor > 0 ? "teal" : undefined} />
            <Stat label="Simüle ROI" value={r?.simulated_roi == null ? "—" : pct(r.simulated_roi, 1)} hint="sonuçlanan biletler" />
            <Stat label="En büyük düşüş" value={r?.max_drawdown == null ? "—" : pct(r.max_drawdown, 1)} hint="tepeden dibe, açık biletler dahil" />
            <Stat label="Bilet" value={r?.tickets.total ?? 0} hint={r ? `${r.tickets.won} kazanç · ${r.tickets.lost} kayıp · ${r.tickets.pending} bekliyor` : undefined} />
          </Card>

          <div className="mt-6 grid gap-6 lg:grid-cols-[1.5fr_1fr]">
            <Card>
              <CardHeader eyebrow={r?.label ?? "Simüle"} title="Bakiye geçmişi" />
              <div className="h-64 p-4">
                {r && r.balance_series.length > 1 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={r.balance_series.map((p) => ({ ...p, sb: p.balance_minor / 100 }))} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                      {layout.chartGrid && <CartesianGrid stroke="var(--mi-line)" />}
                      <XAxis dataKey="at" tickFormatter={(v) => fmtDateTime(String(v)).split(" ").slice(0, 2).join(" ")} stroke="var(--mi-muted)" fontSize={11} minTickGap={40} />
                      <YAxis stroke="var(--mi-muted)" fontSize={11} width={64} tickFormatter={(v) => Number(v).toLocaleString("tr-TR")} domain={["auto", "auto"]} />
                      <Tooltip contentStyle={{ background: "var(--mi-surface-2)", border: "1px solid var(--mi-line-strong)", borderRadius: 8, fontSize: 12 }} formatter={(v) => `${Number(v).toLocaleString("tr-TR")} SB`} labelFormatter={(v) => fmtDateTime(String(v))} />
                      {/* Grafik stili tasarımdan: çizgi, alan veya sütun. */}
                      {layout.chart === "bars" ? (
                        <Bar dataKey="sb" fill="var(--mi-gold)" radius={[2, 2, 0, 0]} />
                      ) : layout.chart === "area" ? (
                        <Area type="stepAfter" dataKey="sb" stroke="var(--mi-gold)" strokeWidth={layout.chartStroke} fill="var(--mi-gold-soft)" dot={false} />
                      ) : (
                        <Line type="stepAfter" dataKey="sb" stroke="var(--mi-gold)" strokeWidth={layout.chartStroke} dot={false} />
                      )}
                    </ComposedChart>
                  </ResponsiveContainer>
                ) : <Empty title="Henüz hareket yok">Kupon Merkezi'nde kupon kaydedip "Sanal bilet aç" ile başlayın.</Empty>}
              </div>
            </Card>
            <SettingsCard account={account.data} />
          </div>

          <Card className="mt-6">
            <CardHeader eyebrow="Biletler" title="Sanal bilet geçmişi" action={<Link href="/kuponlar" className="text-[12.5px] text-gold hover:underline">Kupon Merkezi</Link>} />
            <div className="mt-3 divide-y divide-line border-t border-line">
              {!tickets.data?.items.length ? <Empty title="Sanal bilet yok" /> : tickets.data.items.map((t) => (
                <div key={t.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 text-[12.5px]">
                  <Badge tone={STATUS[t.status as keyof typeof STATUS]?.tone ?? "neutral"}>{STATUS[t.status as keyof typeof STATUS]?.label ?? t.status}</Badge>
                  <span className="num font-medium">{sb(t.stake_minor)}</span>
                  <span className="num text-text-2">oran {t.odds.toFixed(2)} · {t.odds_source === "model_fair" ? "model adil oranı" : "kendi oranınız"}</span>
                  <span className="num text-text-2">model %{(t.model_probability * 100).toFixed(1)}</span>
                  {t.model_ev !== null && <span className="num text-text-2">EV {pct(t.model_ev, 1)} (doğrulanmamış oran)</span>}
                  {t.payout_minor !== null && <span className="num">dönüş {sb(t.payout_minor)}</span>}
                  <span className="ml-auto text-[11px] text-muted">{fmtDateTime(t.created_at)}</span>
                </div>
              ))}
            </div>
          </Card>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <Button variant="ghost" size="sm" loading={reset.isPending} onClick={() => window.confirm("Sanal bakiye başlangıca döner. Sıfırlama sayısı raporda görünür. Emin misiniz?") && reset.mutate()}>
              <RotateCcw className="size-4" aria-hidden />Portföyü sıfırla
            </Button>
            <span className="text-[11.5px] text-muted">7 günde bir, bekleyen bilet yokken. Bugüne kadar {account.data.reset_count} kez sıfırlandı.</span>
            <FormError error={reset.error} />
          </div>
          <p className="mt-6 flex items-start gap-2 text-[11.5px] text-muted"><Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />{account.data.disclaimer}</p>
        </>
      )}
    </div>
  );
}
