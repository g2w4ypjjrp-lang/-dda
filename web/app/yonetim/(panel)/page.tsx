"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Info, Siren } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { PageTitle, can, useAdmin } from "@/components/admin";
import { Badge, Card, CardHeader, ErrorState, Skeleton, Stat, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, money, num, pct } from "@/lib/format";

type Money = Record<string, number> | null;
interface Overview {
  generated_at: string;
  business?: {
    revenue_today_minor: number | null; revenue_month_minor: number | null; revenue: Record<string, { net_minor: number; orders: number }> | null;
    mrr_minor: Money; arr_minor: Money; arpu_30d_minor: number | null; churn_30d: number | null; active_subscriptions: number;
    new_subscriptions_30d: number; canceled_30d: number; orders_in_review: number; costs: { api: null; server: null }; note: string;
  };
  users?: { total: number; active_30d: number; new_7d: number; suspended: number; plans: Record<"FREE" | "PRO" | "ELITE", number> };
  football?: { today: number; live: number; finished_today: number; upcoming_7d: number; postponed_7d: number; active_leagues: number; last_sync: { job: string; status: string; at: string } | null; failed_syncs_24h: number };
  ai?: {
    champions: { id: number; scope_key: string; trained_until: string; test: { n: number | null; log_loss: number | null; ece: number | null } }[];
    predictions_30d: { published: number; abstained: number }; settled_30d: { n: number; brier: number | null; log_loss: number | null; uniform_log_loss: number };
    optuna_trials: number; last_training_at: string | null; drift: { scope_key: string }[];
  };
  coupons?: { total: number; pending: number; won: number; lost: number; void: number; created_7d: number; realized: { n: number; mean_predicted: number; observed_win_rate: number } | null };
  virtual?: { accounts: number; active_30d: number; total_balance_minor: number; tickets: number; pending_tickets: number; simulated_roi: number | null; label: string };
}
interface Health { status: string; components: Record<string, { status: string }> }
interface Actions { counts: Record<string, number>; items: { key: string; severity: string; title: string; link: string | null }[] }

const fmtMoney = (m: Money) => (m ? Object.entries(m).map(([c, v]) => money(v, c)).join(" · ") : "Veri yok");
const NONE = "Veri yok";

function Section({ title, href, children }: { title: string; href?: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader eyebrow="Özet" title={title} action={href ? <Link href={href} className="inline-flex items-center gap-1 text-[12px] font-medium text-gold hover:underline">Modül <ArrowRight className="size-3.5" aria-hidden /></Link> : undefined} />
      <div className="grid grid-cols-2 gap-5 p-5 sm:grid-cols-3">{children}</div>
    </Card>
  );
}

const STATUS_TONE: Record<string, "teal" | "amber" | "red" | "neutral"> = { ok: "teal", degraded: "amber", down: "red", not_configured: "neutral", unknown: "neutral" };
const STATUS_LABEL: Record<string, string> = { ok: "Çalışıyor", degraded: "Sorunlu", down: "Çalışmıyor", not_configured: "Bağlı değil", unknown: "Bilinmiyor" };
const COMPONENT_LABEL: Record<string, string> = {
  database: "PostgreSQL", redis: "Redis", queue: "Kuyruk", workers: "İşçiler", scheduler: "Zamanlayıcı",
  football_api: "Futbol API", payment_api: "Ödeme API", backend: "Backend",
};

export default function CommandCenter() {
  const me = useAdmin();
  const q = useQuery({ queryKey: ["admin", "overview"], queryFn: () => api<Overview>("/admin/v1/overview"), refetchInterval: 60_000 });
  const health = useQuery({ queryKey: ["admin", "health"], queryFn: () => api<Health>("/admin/v1/health"), enabled: can(me, "system.read"), refetchInterval: 60_000 });
  const actions = useQuery({ queryKey: ["admin", "actions"], queryFn: () => api<Actions>("/admin/v1/actions"), refetchInterval: 60_000 });

  if (q.isLoading) return <><PageTitle eyebrow="Command Center" title="Platform durumu" /><Skeleton className="h-96" /></>;
  if (q.error || !q.data) return <><PageTitle eyebrow="Command Center" title="Platform durumu" /><Card><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card></>;
  const d = q.data;
  const top = actions.data?.items.slice(0, 5) ?? [];

  return (
    <div className="space-y-6">
      <PageTitle eyebrow="Command Center" title="Platform durumu">
        <span className="text-[12px] text-muted">Güncellendi: {ago(d.generated_at)}</span>
      </PageTitle>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader eyebrow="Action Center" title="Dikkat gerektirenler" action={<Link href="/yonetim/aksiyon" className="text-[12px] font-medium text-gold hover:underline">Tümü</Link>} />
          <div className="p-5">
            <div className="mb-4 flex flex-wrap gap-2">
              <Badge tone="red">{actions.data?.counts.critical ?? 0} kritik</Badge>
              <Badge tone="amber">{actions.data?.counts.warning ?? 0} uyarı</Badge>
              <Badge>{actions.data?.counts.info ?? 0} bilgi</Badge>
            </div>
            {top.length === 0 ? <p className="text-[13px] text-muted">Açık uyarı yok.</p> : (
              <ul className="space-y-2">
                {top.map((i) => (
                  <li key={i.key} className="flex items-start gap-2 text-[13px]">
                    {i.severity === "critical" ? <Siren className="mt-0.5 size-4 shrink-0 text-red" aria-hidden /> : i.severity === "warning" ? <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber" aria-hidden /> : <Info className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />}
                    {i.link ? <Link href={i.link} className="hover:text-gold">{i.title}</Link> : i.title}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
        {can(me, "system.read") && (
          <Card>
            <CardHeader eyebrow="Sistem sağlığı" title={health.data ? STATUS_LABEL[health.data.status] ?? health.data.status : "…"} action={<Link href="/yonetim/sistem" className="text-[12px] font-medium text-gold hover:underline">Ayrıntı</Link>} />
            <ul className="grid grid-cols-2 gap-2 p-5 text-[12.5px]">
              {health.data && Object.entries(health.data.components).map(([k, c]) => (
                <li key={k} className="flex items-center justify-between gap-2 rounded-ctl border border-line px-3 py-2">
                  <span>{COMPONENT_LABEL[k] ?? k}</span><Badge tone={STATUS_TONE[c.status] ?? "neutral"}>{STATUS_LABEL[c.status] ?? c.status}</Badge>
                </li>
              ))}
              {health.isLoading && <Skeleton className="col-span-2 h-24" />}
            </ul>
          </Card>
        )}
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        {d.business && (
          <Section title="İşletme" href="/yonetim/finans">
            <Stat label="Bugünkü gelir" value={d.business.revenue_today_minor === null ? NONE : money(d.business.revenue_today_minor)} />
            <Stat label="Bu ay" value={d.business.revenue_month_minor === null ? NONE : money(d.business.revenue_month_minor)} />
            <Stat label="Toplam net" value={d.business.revenue ? Object.entries(d.business.revenue).map(([c, v]) => money(v.net_minor, c)).join(" · ") : NONE} />
            <Stat label="MRR" value={fmtMoney(d.business.mrr_minor)} hint={d.business.arr_minor ? `ARR ${fmtMoney(d.business.arr_minor)}` : undefined} />
            <Stat label="ARPU (30 g)" value={d.business.arpu_30d_minor === null ? NONE : money(d.business.arpu_30d_minor)} />
            <Stat label="Churn (30 g)" value={d.business.churn_30d === null ? NONE : pct(d.business.churn_30d, 1)} />
            <Stat label="Aktif abonelik" value={d.business.active_subscriptions} />
            <Stat label="Yeni / iptal (30 g)" value={`${d.business.new_subscriptions_30d} / ${d.business.canceled_30d}`} />
            <Stat label="API / sunucu maliyeti" value={NONE} hint="Maliyet verisi bağlı değil" />
          </Section>
        )}
        {d.users && (
          <Section title="Kullanıcılar" href="/yonetim/kullanicilar">
            <Stat label="Toplam" value={d.users.total} />
            <Stat label="Aktif (30 g)" value={d.users.active_30d} hint="oturum açan" />
            <Stat label="Yeni (7 g)" value={d.users.new_7d} />
            <Stat label="FREE" value={d.users.plans.FREE} />
            <Stat label="PRO" value={d.users.plans.PRO} />
            <Stat label="ELITE" value={d.users.plans.ELITE} />
            <Stat label="Askıda" value={d.users.suspended} tone={d.users.suspended ? "red" : undefined} />
          </Section>
        )}
        {d.football && (
          <Section title="Futbol operasyonları" href="/yonetim/veri">
            <Stat label="Bugünkü maç" value={d.football.today} hint={`${d.football.finished_today} bitti`} />
            <Stat label="Canlı" value={d.football.live} tone={d.football.live ? "teal" : undefined} />
            <Stat label="Yaklaşan (7 g)" value={d.football.upcoming_7d} />
            <Stat label="Ertelenen (7 g)" value={d.football.postponed_7d} />
            <Stat label="Aktif lig" value={d.football.active_leagues} />
            <Stat label="Veri güncelleme" value={d.football.last_sync ? d.football.last_sync.status : NONE} hint={d.football.last_sync ? `${d.football.last_sync.job} · ${ago(d.football.last_sync.at)}` : "Henüz iş çalışmadı"} tone={d.football.failed_syncs_24h ? "red" : undefined} />
          </Section>
        )}
        {d.ai && (
          <Section title="AI" href="/yonetim/modeller">
            <Stat label="Aktif (şampiyon) model" value={d.ai.champions.length} hint={d.ai.champions[0] ? `test log loss ${num(d.ai.champions[0].test.log_loss, 3)}` : "Eğitilmedi"} />
            <Stat label="Tahmin (30 g)" value={d.ai.predictions_30d.published} hint={`${d.ai.predictions_30d.abstained} çekimser`} />
            <Stat label="Brier (canlı)" value={d.ai.settled_30d.brier === null ? NONE : num(d.ai.settled_30d.brier, 3)} hint={`${d.ai.settled_30d.n} sonuçlanan`} />
            <Stat label="Log loss (canlı)" value={d.ai.settled_30d.log_loss === null ? NONE : num(d.ai.settled_30d.log_loss, 3)} hint={`tekdüze ${num(d.ai.settled_30d.uniform_log_loss, 3)}`} />
            <Stat label="Optuna denemesi" value={d.ai.optuna_trials} hint={d.ai.last_training_at ? `son eğitim ${ago(d.ai.last_training_at)}` : undefined} />
            <Stat label="Kayma uyarısı" value={d.ai.drift.length} tone={d.ai.drift.length ? "red" : undefined} />
          </Section>
        )}
        {d.coupons && (
          <Section title="Kuponlar" href="/yonetim/kuponlar">
            <Stat label="Toplam" value={d.coupons.total} hint={`${d.coupons.created_7d} son 7 gün`} />
            <Stat label="Bekleyen" value={d.coupons.pending} />
            <Stat label="Tuttu / tutmadı" value={`${d.coupons.won} / ${d.coupons.lost}`} hint={`${d.coupons.void} geçersiz`} />
            <Stat label="Gerçekleşen oran" value={d.coupons.realized ? pct(d.coupons.realized.observed_win_rate, 1) : NONE} hint={d.coupons.realized ? `beklenen ${pct(d.coupons.realized.mean_predicted, 1)} · ${d.coupons.realized.n} kupon` : "Sonuçlanmış kupon yok"} />
          </Section>
        )}
        {d.virtual && (
          <Section title="Sanal finans" href="/yonetim/sanal">
            <Stat label="Sanal hesap" value={d.virtual.accounts} hint={`${d.virtual.active_30d} aktif (30 g)`} />
            <Stat label="Toplam sanal bakiye" value={`${(d.virtual.total_balance_minor / 100).toLocaleString("tr-TR")} SB`} />
            <Stat label="Bilet" value={d.virtual.tickets} hint={`${d.virtual.pending_tickets} bekliyor`} />
            <Stat label="Simüle ROI" value={d.virtual.simulated_roi === null ? NONE : pct(d.virtual.simulated_roi, 1)} hint={d.virtual.label} />
          </Section>
        )}
      </div>
      <p className={cx("text-[11.5px] text-muted")}>Tüm değerler gerçek kayıtlardan hesaplanır; kayıt yoksa "Veri yok" gösterilir. Test modundaki ödemeler gelire dahil değildir.</p>
    </div>
  );
}
