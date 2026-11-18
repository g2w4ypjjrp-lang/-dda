"use client";

// Kişiselleştirilebilir panel: kullanıcı bileşen ekler/kaldırır, sırasını ve boyutunu değiştirir;
// düzen sunucuda saklanır (/v1/dashboard/layout). Her bileşen gerçek veriden beslenir; veri yoksa söyler.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Check, LayoutGrid, Plus, RotateCcw, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { ApiError, api, del, put } from "@/lib/api";
import { ago, fmtDay, pct, sb, trToday } from "@/lib/format";
import type { BillingMe, Fixture, FixtureList, Me, Prediction } from "@/lib/types";
import { useFavorites, useMarkRead, useNotifications } from "./engage";
import { MatchList } from "./match";
import { Badge, Button, Card, CardHeader, Empty, ErrorState, ProbBar, Skeleton, Stat, cx } from "./ui";

type Size = "s" | "m" | "l";
interface Item { widget: string; size: Size }
interface LayoutResponse { layout: Item[]; custom: boolean; widgets: Record<string, string> }

const SPAN: Record<Size, string> = { s: "lg:col-span-4", m: "lg:col-span-6", l: "lg:col-span-12" };
const SIZE_LABEL: Record<Size, string> = { s: "Küçük", m: "Orta", l: "Geniş" };
const LIMIT: Record<Size, number> = { s: 4, m: 6, l: 12 };

function Shell({ title, eyebrow, action, children }: { title: string; eyebrow?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <Card className="h-full overflow-hidden">
      <CardHeader eyebrow={eyebrow} title={title} action={action} />
      <div className="mt-3 border-t border-line">{children}</div>
    </Card>
  );
}

const byFixtureOf = (preds?: Prediction[]) => new Map((preds ?? []).map((p) => [p.fixture_id, p]));

function useToday(enabled: boolean) {
  const day = trToday();
  const fixtures = useQuery({ queryKey: ["fixtures", day], queryFn: () => api<FixtureList>(`/v1/football/fixtures?date=${day}`), enabled });
  const preds = useQuery({ queryKey: ["predictions", day], queryFn: () => api<{ items: Prediction[] }>(`/v1/predictions?date=${day}`), enabled });
  return { fixtures, preds };
}

function useFavFixtures() {
  return useQuery({ queryKey: ["favorites", "fixtures"], queryFn: () => api<{ teams: Fixture[]; competitions: Fixture[]; saved: Fixture[] }>("/v1/favorites/fixtures") });
}

function AccountWidget({ me }: { me: Me }) {
  return (
    <Shell eyebrow="Hesap" title="Hesap özeti">
      <div className="grid grid-cols-2 gap-4 p-5">
        <Stat label="E-posta" value={me.email_verified ? "Doğrulandı" : "Bekliyor"} tone={me.email_verified ? "teal" : undefined} />
        <Stat label="2 adımlı doğrulama" value={me.mfa_enabled ? "Açık" : "Kapalı"} tone={me.mfa_enabled ? "teal" : "red"} />
      </div>
    </Shell>
  );
}

function SubscriptionWidget() {
  const q = useQuery({ queryKey: ["billing", "me"], queryFn: () => api<BillingMe>("/v1/billing/me") });
  return (
    <Shell eyebrow="Abonelik" title={q.data?.plan ?? "…"} action={<Link href="/paketler" className="text-[12px] font-medium text-gold hover:underline">Paketler</Link>}>
      <div className="p-5 text-[12.5px] text-text-2">
        {q.isLoading ? <Skeleton className="h-10" /> : q.data?.current ? `${fmtDay(q.data.current.current_period_end)} tarihine kadar geçerli. Otomatik yenileme yoktur.` : "Ücretsiz paket."}
      </div>
    </Shell>
  );
}

function TodayWidget({ size }: { size: Size }) {
  const { fixtures, preds } = useToday(true);
  const items = fixtures.data?.items ?? [];
  return (
    <Shell eyebrow="Bugün" title="Günün maçları" action={<Link href="/maclar" className="text-[12px] font-medium text-gold hover:underline">Tümü</Link>}>
      {fixtures.isLoading ? <Skeleton className="m-5 h-24" /> : fixtures.error ? <ErrorState error={fixtures.error} /> : items.length === 0 ? <Empty title="Bugün maç yok veya veri henüz gelmedi" /> : (
        <MatchList fixtures={items.slice(0, LIMIT[size])} byFixture={byFixtureOf(preds.data?.items)} columns={size === "l" ? 3 : 2} />
      )}
    </Shell>
  );
}

function FeaturedWidget({ size }: { size: Size }) {
  const { fixtures, preds } = useToday(true);
  const top = (preds.data?.items ?? []).filter((p) => p.status === "published" && p.probabilities)
    .sort((a, b) => Math.max(...Object.values(b.probabilities!["1x2"])) - Math.max(...Object.values(a.probabilities!["1x2"])))
    .slice(0, LIMIT[size]);
  return (
    <Shell eyebrow="AI" title="Öne çıkan analizler">
      {preds.isLoading ? <Skeleton className="m-5 h-24" /> : top.length === 0 ? <Empty title="Bugün yayımlanmış analiz yok" /> : (
        <ul className="divide-y divide-line">
          {top.map((p) => {
            const f = fixtures.data?.items.find((x) => x.id === p.fixture_id);
            return (
              <li key={p.id}>
                <Link href={`/maclar/${p.fixture_id}`} className="block px-5 py-3 hover:bg-surface-2">
                  <div className="mb-2 flex items-center justify-between gap-2 text-[13px]"><span className="truncate font-medium">{f ? `${f.home.name} – ${f.away.name}` : `Maç #${p.fixture_id}`}</span><Badge>{p.reliability.label}</Badge></div>
                  <ProbBar p={p.probabilities!["1x2"]} size="sm" />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </Shell>
  );
}

function FavoriteTeamsWidget({ size }: { size: Size }) {
  const fav = useFavorites(true);
  const fx = useFavFixtures();
  const teams = fav.data?.teams ?? [];
  return (
    <Shell eyebrow="Favoriler" title="Favori takımlar">
      {fav.isLoading ? <Skeleton className="m-5 h-16" /> : teams.length === 0 ? (
        <Empty title="Favori takım yok">Maç sayfasında takımın yanındaki yıldızla ekleyin.</Empty>
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5 px-5 pt-3">{teams.map((t) => <Badge key={t.id}>{t.name}</Badge>)}</div>
          {fx.data?.teams.length ? <MatchList fixtures={fx.data.teams.slice(0, LIMIT[size])} byFixture={new Map()} /> : <p className="px-5 py-4 text-[12.5px] text-muted">Önümüzdeki 7 günde maçları yok.</p>}
        </>
      )}
    </Shell>
  );
}

function FavoriteLeaguesWidget({ size }: { size: Size }) {
  const fav = useFavorites(true);
  const fx = useFavFixtures();
  const comps = fav.data?.competitions ?? [];
  return (
    <Shell eyebrow="Favoriler" title="Favori ligler">
      {comps.length === 0 ? <Empty title="Favori lig yok">Lig sayfasındaki yıldızla ekleyin.</Empty> : (
        <>
          <div className="flex flex-wrap gap-1.5 px-5 pt-3">{comps.map((c) => <Link key={c.id} href={`/ligler/${c.id}`}><Badge>{c.name}</Badge></Link>)}</div>
          {fx.data?.competitions.length ? <MatchList fixtures={fx.data.competitions.slice(0, LIMIT[size])} byFixture={new Map()} /> : <p className="px-5 py-4 text-[12.5px] text-muted">Önümüzdeki 7 günde maç yok.</p>}
        </>
      )}
    </Shell>
  );
}

function SavedMatchesWidget({ size }: { size: Size }) {
  const fx = useFavFixtures();
  return (
    <Shell eyebrow="Kaydedilenler" title="Kaydedilmiş maçlar">
      {fx.isLoading ? <Skeleton className="m-5 h-16" /> : !fx.data?.saved.length ? <Empty title="Kaydedilmiş maç yok">Maç sayfasındaki “Maçı kaydet” ile ekleyin.</Empty> : (
        <MatchList fixtures={fx.data.saved.slice(0, LIMIT[size])} byFixture={new Map()} />
      )}
    </Shell>
  );
}

function CouponsWidget({ size }: { size: Size }) {
  const q = useQuery({ queryKey: ["coupons"], queryFn: () => api<{ items: { id: number; created_at: string; status: string; joint_probability: number; legs: unknown[] }[] }>("/v1/coupons"), retry: false });
  const forbidden = q.error instanceof ApiError && q.error.status === 403;
  const label: Record<string, string> = { pending: "Bekliyor", won: "Tuttu", lost: "Tutmadı", void: "Geçersiz" };
  return (
    <Shell eyebrow="Kupon" title="Kupon geçmişi" action={<Link href="/kuponlar" className="text-[12px] font-medium text-gold hover:underline">Kupon Merkezi</Link>}>
      {q.isLoading ? <Skeleton className="m-5 h-16" /> : forbidden ? <Empty title="Kupon oluşturucu PRO paketinde" /> : !q.data?.items.length ? <Empty title="Henüz kayıtlı kupon yok" /> : (
        <ul className="divide-y divide-line">
          {q.data.items.slice(0, LIMIT[size]).map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-3 px-5 py-2.5 text-[12.5px]">
              <span>#{c.id} · {c.legs.length} seçim · {ago(c.created_at)}</span>
              <span className="flex items-center gap-2"><span className="num text-muted">{pct(c.joint_probability, 1)}</span><Badge>{label[c.status] ?? c.status}</Badge></span>
            </li>
          ))}
        </ul>
      )}
    </Shell>
  );
}

function VirtualWidget() {
  const acc = useQuery({ queryKey: ["virtual", "account"], queryFn: () => api<{ balance_minor: number; starting_balance_minor: number }>("/v1/virtual/account"), retry: false });
  const rep = useQuery({ queryKey: ["virtual", "report", "widget"], queryFn: () => api<{ simulated_roi: number | null }>("/v1/virtual/report"), enabled: !!acc.data, retry: false });
  return (
    <Shell eyebrow="Simülasyon" title="Sanal bakiye" action={<Link href="/sanal" className="text-[12px] font-medium text-gold hover:underline">Aç</Link>}>
      {acc.isLoading ? <Skeleton className="m-5 h-12" /> : !acc.data ? <Empty title="Sanal portföy açılmadı" /> : (
        <div className="grid grid-cols-2 gap-4 p-5">
          <Stat label="Bakiye" value={sb(acc.data.balance_minor)} />
          <Stat label="Simüle ROI" value={rep.data?.simulated_roi == null ? "Veri yok" : pct(rep.data.simulated_roi, 1)} hint="Gerçek para değildir" />
        </div>
      )}
    </Shell>
  );
}

function NotificationsWidget({ size }: { size: Size }) {
  const q = useNotifications(true, LIMIT[size]);
  const read = useMarkRead();
  return (
    <Shell eyebrow="Bildirimler" title={q.data?.unread ? `${q.data.unread} okunmamış` : "Bildirimler"} action={<Link href="/bildirimler" className="text-[12px] font-medium text-gold hover:underline">Tümü</Link>}>
      {q.isLoading ? <Skeleton className="m-5 h-16" /> : !q.data?.items.length ? <Empty title="Bildirim yok" /> : (
        <ul className="divide-y divide-line">
          {q.data.items.map((n) => (
            <li key={n.id} className={cx("px-5 py-2.5 text-[12.5px]", !n.read && "tone-highlight bg-gold-soft/40")}>
              <Link href={n.link ?? "/bildirimler"} onClick={() => !n.read && read.mutate({ ids: [n.id] })} className="block">
                <div className="font-medium">{n.title}</div><div className="text-[11px] text-muted">{ago(n.created_at)}</div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Shell>
  );
}

function ActivityWidget({ size }: { size: Size }) {
  const q = useQuery({ queryKey: ["me", "activity"], queryFn: () => api<{ items: { at: string; label: string; ip: string | null }[] }>(`/v1/me/activity?limit=${LIMIT[size]}`) });
  return (
    <Shell eyebrow="Hesap" title="Son aktiviteler">
      {q.isLoading ? <Skeleton className="m-5 h-16" /> : !q.data?.items.length ? <Empty title="Etkinlik yok" /> : (
        <ul className="divide-y divide-line">
          {q.data.items.map((a, i) => <li key={i} className="flex justify-between gap-3 px-5 py-2.5 text-[12.5px]"><span>{a.label}</span><span className="text-muted">{ago(a.at)}{a.ip ? ` · ${a.ip}` : ""}</span></li>)}
        </ul>
      )}
    </Shell>
  );
}

function Widget({ item, me }: { item: Item; me: Me }) {
  switch (item.widget) {
    case "account": return <AccountWidget me={me} />;
    case "subscription": return <SubscriptionWidget />;
    case "today": return <TodayWidget size={item.size} />;
    case "featured": return <FeaturedWidget size={item.size} />;
    case "favorite_teams": return <FavoriteTeamsWidget size={item.size} />;
    case "favorite_leagues": return <FavoriteLeaguesWidget size={item.size} />;
    case "saved_matches": return <SavedMatchesWidget size={item.size} />;
    case "coupons": return <CouponsWidget size={item.size} />;
    case "virtual": return <VirtualWidget />;
    case "notifications": return <NotificationsWidget size={item.size} />;
    case "activity": return <ActivityWidget size={item.size} />;
    default: return null;
  }
}

export function DashboardGrid({ me }: { me: Me }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["dashboard", "layout"], queryFn: () => api<LayoutResponse>("/v1/dashboard/layout") });
  const [draft, setDraft] = useState<Item[] | null>(null);
  const save = useMutation({
    mutationFn: (layout: Item[]) => put<LayoutResponse>("/v1/dashboard/layout", { layout }),
    onSuccess: (r) => { qc.setQueryData(["dashboard", "layout"], r); setDraft(null); },
  });
  const reset = useMutation({
    mutationFn: () => del<LayoutResponse>("/v1/dashboard/layout"),
    onSuccess: (r) => { qc.setQueryData(["dashboard", "layout"], r); setDraft(null); },
  });
  if (q.isLoading || !q.data) return <Skeleton className="h-64" />;
  const editing = draft !== null;
  const layout = draft ?? q.data.layout;
  const missing = Object.keys(q.data.widgets).filter((w) => !layout.some((i) => i.widget === w));
  const move = (i: number, d: -1 | 1) => { const n = [...layout]; const [x] = n.splice(i, 1); n.splice(i + d, 0, x!); setDraft(n); };

  return (
    <section aria-label="Panel bileşenleri">
      <div className="mb-3 flex flex-wrap items-center justify-end gap-2">
        {editing ? (
          <>
            <span className="mr-auto text-[12.5px] text-muted">Düzenleme modu: sırala, boyutlandır, kaldır veya ekle.</span>
            <Button size="sm" variant="ghost" onClick={() => reset.mutate()} loading={reset.isPending}><RotateCcw className="size-3.5" aria-hidden />Varsayılan</Button>
            <Button size="sm" variant="ghost" onClick={() => setDraft(null)}><X className="size-3.5" aria-hidden />Vazgeç</Button>
            <Button size="sm" onClick={() => save.mutate(layout)} loading={save.isPending}><Check className="size-3.5" aria-hidden />Düzeni kaydet</Button>
          </>
        ) : (
          <Button size="sm" variant="secondary" onClick={() => setDraft(q.data.layout)}><LayoutGrid className="size-3.5" aria-hidden />Paneli düzenle</Button>
        )}
      </div>
      {editing && missing.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-card border border-dashed border-line-strong p-3 text-[12.5px]">
          <span className="text-muted">Ekle:</span>
          {missing.map((w) => (
            <button key={w} type="button" onClick={() => setDraft([...layout, { widget: w, size: "m" }])} className="inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-1 hover:border-gold hover:text-gold">
              <Plus className="size-3" aria-hidden />{q.data.widgets[w]}
            </button>
          ))}
        </div>
      )}
      {layout.length === 0 ? <Card><Empty title="Panel boş">“Paneli düzenle” ile bileşen ekleyin.</Empty></Card> : (
        <div className="grid gap-5 lg:grid-cols-12">
          {layout.map((item, i) => (
            <div key={item.widget} className={cx(SPAN[item.size], "flex min-w-0 flex-col", editing && "rounded-card ring-1 ring-gold/40")} data-widget={item.widget}>
              {editing && (
                <div className="tone-highlight flex flex-wrap items-center gap-1 rounded-t-card bg-gold-soft px-3 py-1.5 text-[11.5px]">
                  <span className="mr-auto font-medium">{q.data.widgets[item.widget]}</span>
                  {(["s", "m", "l"] as const).map((s) => (
                    <button key={s} type="button" aria-pressed={item.size === s} onClick={() => setDraft(layout.map((x, j) => (j === i ? { ...x, size: s } : x)))}
                      className={cx("rounded px-1.5 py-0.5", item.size === s ? "bg-gold text-accent-text" : "hover:bg-surface-2")}>{SIZE_LABEL[s]}</button>
                  ))}
                  <button type="button" aria-label={`${q.data.widgets[item.widget]} yukarı`} disabled={i === 0} onClick={() => move(i, -1)} className="rounded p-1 hover:bg-surface-2 disabled:opacity-30"><ArrowUp className="size-3.5" aria-hidden /></button>
                  <button type="button" aria-label={`${q.data.widgets[item.widget]} aşağı`} disabled={i === layout.length - 1} onClick={() => move(i, 1)} className="rounded p-1 hover:bg-surface-2 disabled:opacity-30"><ArrowDown className="size-3.5" aria-hidden /></button>
                  <button type="button" aria-label={`${q.data.widgets[item.widget]} kaldır`} onClick={() => setDraft(layout.filter((_, j) => j !== i))} className="rounded p-1 text-red hover:bg-surface-2"><Trash2 className="size-3.5" aria-hidden /></button>
                </div>
              )}
              <div className="min-h-0 flex-1"><Widget item={item} me={me} /></div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
