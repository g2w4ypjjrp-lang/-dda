"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BarChart3, Crown, Home, LayoutDashboard, LogIn, Menu, ShieldCheck, Ticket, Wallet, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { api } from "@/lib/api";
import { fmtDate, trToday } from "@/lib/format";
import { useMe } from "@/lib/hooks";
import type { FixtureList, Prediction } from "@/lib/types";
import { useLayout } from "./design";
import { NotificationBell } from "./engage";
import { Logo } from "./Logo";
import { SiteFooter } from "./SiteFooter";
import { cx } from "./ui";

const NAV = [
  { href: "/", label: "Genel Bakış", icon: Home },
  { href: "/maclar", label: "Maç Merkezi", icon: Activity },
  { href: "/kuponlar", label: "Kupon Merkezi", icon: Ticket },
  { href: "/sanal", label: "Sanal Portföy", icon: Wallet },
  { href: "/performans", label: "Model Şeffaflığı", icon: BarChart3 },
  { href: "/paketler", label: "Paketler", icon: Crown },
];

function isActive(path: string, href: string) {
  return href === "/" ? path === "/" : path.startsWith(href);
}

function NavLinks({ vertical = false, onNavigate }: { vertical?: boolean; onNavigate?: () => void }) {
  const path = usePathname();
  return (
    <>
      {NAV.map((n) => (
        <Link
          key={n.href}
          href={n.href}
          onClick={onNavigate}
          aria-current={isActive(path, n.href) ? "page" : undefined}
          className={cx(
            "mi-nav-link font-medium text-text-2 transition-colors hover:text-text",
            vertical ? "flex items-center gap-2.5 px-3 py-2.5 text-[13.5px]" : "px-3 py-2 text-[13px]",
          )}
        >
          {vertical && <n.icon className="size-4 shrink-0" aria-hidden />}
          {n.label}
        </Link>
      ))}
    </>
  );
}

function Account({ stacked = false }: { stacked?: boolean }) {
  const { data: me } = useMe();
  return (
    <div className={cx("flex items-center gap-2", stacked && "flex-col items-stretch")}>
      {me?.staff_roles.length ? (
        <Link href="/yonetim" className="hidden items-center gap-1.5 rounded-ctl px-3 py-2 text-[13px] text-text-2 hover:text-text sm:inline-flex">
          <ShieldCheck className="size-4" aria-hidden /> Yönetim
        </Link>
      ) : null}
      <NotificationBell />
      {me ? (
        <Link href="/panel" className="inline-flex h-9 items-center gap-2 rounded-ctl border border-line-strong bg-surface-2 px-3 text-[13px] font-medium text-text hover:bg-surface-3">
          <LayoutDashboard className="size-4 text-gold" aria-hidden />
          <span className="max-w-[120px] truncate">{me.display_name}</span>
        </Link>
      ) : (
        <>
          <Link href="/giris" className={cx("h-9 items-center rounded-ctl px-3 text-[13px] font-medium text-text-2 hover:text-text", stacked ? "inline-flex justify-center" : "hidden sm:inline-flex")}>
            Giriş
          </Link>
          <Link href="/kayit" className="mi-btn-primary inline-flex h-9 items-center justify-center whitespace-nowrap rounded-ctl bg-gold px-3.5 text-[13px] font-semibold text-accent-text hover:bg-gold-hover">
            Ücretsiz başla
          </Link>
        </>
      )}
    </div>
  );
}

/* --- Mobil gezinme ------------------------------------------------------------------------------ */

function MobileTabs() {
  const path = usePathname();
  const { data: me } = useMe();
  return (
    <nav aria-label="Mobil menü" className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-bg/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
      <div className="grid grid-cols-5">
        {[...NAV.filter((n) => n.href !== "/sanal" && n.href !== "/paketler"), me ? { href: "/panel", label: "Panelim", icon: LayoutDashboard } : { href: "/giris", label: "Giriş", icon: LogIn }].map((n) => (
          <Link
            key={n.href}
            href={n.href}
            aria-current={isActive(path, n.href) ? "page" : undefined}
            className={cx("flex flex-col items-center gap-1 py-2.5 text-[10.5px] font-medium", isActive(path, n.href) ? "text-gold" : "text-muted")}
          >
            <n.icon className="size-5" aria-hidden />
            {n.label.split(" ")[0]}
          </Link>
        ))}
      </div>
    </nav>
  );
}

function MobileDrawerButton() {
  const [open, setOpen] = useState(false);
  const path = usePathname();
  useEffect(() => setOpen(false), [path]);
  return (
    <div className="md:hidden">
      <button type="button" aria-label={open ? "Menüyü kapat" : "Menüyü aç"} aria-expanded={open} onClick={() => setOpen(!open)} className="grid size-9 place-items-center rounded-ctl border border-line text-text">
        {open ? <X className="size-4" aria-hidden /> : <Menu className="size-4" aria-hidden />}
      </button>
      {open && (
        <div className="fixed inset-x-0 top-[var(--mi-header,64px)] z-40 border-b border-line bg-bg px-4 pb-5 pt-2 shadow-card">
          <nav aria-label="Mobil menü" className="flex flex-col"><NavLinks vertical onNavigate={() => setOpen(false)} /></nav>
          <div className="mt-3 border-t border-line pt-3"><Account stacked /></div>
        </div>
      )}
    </div>
  );
}

function MobileTopTabs() {
  return (
    <nav aria-label="Mobil menü" className="flex gap-1 overflow-x-auto border-t border-line px-3 py-1.5 md:hidden">
      <NavLinks />
    </nav>
  );
}

/* --- Kabuklar ----------------------------------------------------------------------------------- */

function Main({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <main id="icerik" className={cx("mx-auto px-4 sm:px-6", wide ? "max-w-none" : "max-w-(--mi-page)")}>
      {children}
    </main>
  );
}

function Topbar({ children }: { children: ReactNode }) {
  const { mobileNav } = useLayout();
  return (
    <>
      <header className="sticky top-0 z-30 border-b border-line bg-bg/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-(--mi-page) items-center gap-4 px-4 sm:gap-8 sm:px-6">
          <Link href="/" className="shrink-0" aria-label="Match Intelligence AI ana sayfa"><Logo /></Link>
          <nav aria-label="Ana menü" className="hidden items-center gap-1 md:flex"><NavLinks /></nav>
          <div className="ml-auto hidden md:block"><Account /></div>
          <div className="ml-auto flex items-center gap-2 md:hidden">
            {mobileNav !== "drawer" && <Account />}
            {mobileNav === "drawer" && <MobileDrawerButton />}
          </div>
        </div>
        {mobileNav === "top" && <MobileTopTabs />}
      </header>
      <Main>{children}</Main>
      <SiteFooter />
      {mobileNav === "tabs" && <MobileTabs />}
    </>
  );
}

function Sidebar({ children }: { children: ReactNode }) {
  const { mobileNav } = useLayout();
  return (
    <div className="lg:grid lg:grid-cols-[var(--mi-sidebar)_1fr]">
      <aside className="sticky top-0 z-30 border-b border-line bg-bg-elevated lg:h-dvh lg:border-b-0 lg:border-r">
        <div className="flex h-16 items-center justify-between px-5 lg:h-20">
          <Link href="/" aria-label="Match Intelligence AI ana sayfa"><Logo /></Link>
          <div className="flex items-center gap-2 lg:hidden">
            <div className="hidden md:block"><Account /></div>
            {mobileNav === "drawer" ? <MobileDrawerButton /> : <span className="md:hidden"><Account /></span>}
          </div>
        </div>
        <nav aria-label="Ana menü" className="hidden flex-col gap-0.5 px-3 lg:flex"><NavLinks vertical /></nav>
        <nav aria-label="Ana menü" className="hidden gap-1 overflow-x-auto px-3 pb-2 md:flex lg:hidden"><NavLinks /></nav>
        {mobileNav === "top" && <MobileTopTabs />}
        <div className="absolute inset-x-0 bottom-0 hidden border-t border-line p-4 lg:block"><Account stacked /></div>
      </aside>
      <div className="min-w-0">
        <Main>{children}</Main>
        <SiteFooter />
      </div>
      {mobileNav === "tabs" && <MobileTabs />}
    </div>
  );
}

/** Terminal kabuğu: ince üst çubuk + gerçek verilerle durum şeridi (uydurma akış yok). */
function TerminalTicker() {
  const day = trToday();
  const fixtures = useQuery({ queryKey: ["fixtures", day], queryFn: () => api<FixtureList>(`/v1/football/fixtures?date=${day}`), refetchInterval: 60_000 });
  const preds = useQuery({ queryKey: ["predictions", day], queryFn: () => api<{ items: Prediction[] }>(`/v1/predictions?date=${day}`) });
  const items = fixtures.data?.items ?? [];
  const live = items.filter((f) => f.status === "live" || f.status === "halftime").length;
  const published = (preds.data?.items ?? []).filter((p) => p.status === "published").length;
  const cell = "flex items-center gap-1.5 whitespace-nowrap border-r border-line px-3";
  return (
    <div className="num flex h-7 items-center overflow-x-auto border-b border-line bg-bg-elevated font-mono text-[11px] text-text-2" aria-label="Veri durumu">
      <span className={cell}><span className="text-muted">TARİH</span>{fmtDate(`${day}T12:00:00Z`)}</span>
      <span className={cell}><span className="text-muted">MAÇ</span>{fixtures.isLoading ? "…" : items.length}</span>
      <span className={cell}><span className={cx("size-1.5 rounded-full", live ? "live-dot bg-teal" : "bg-muted")} aria-hidden /><span className="text-muted">CANLI</span>{live}</span>
      <span className={cell}><span className="text-muted">AI</span>{preds.isLoading ? "…" : published}</span>
      <span className={cell}><span className="text-muted">KAYNAK</span>{fixtures.data?.provider_label ?? "—"}</span>
    </div>
  );
}

function Terminal({ children }: { children: ReactNode }) {
  const { mobileNav } = useLayout();
  return (
    <>
      <header className="sticky top-0 z-30 bg-bg" style={{ ["--mi-header" as string]: "44px" }}>
        <div className="flex h-11 items-center gap-4 border-b border-line px-3 sm:px-4">
          <Link href="/" aria-label="Match Intelligence AI ana sayfa"><Logo /></Link>
          <nav aria-label="Ana menü" className="hidden items-center gap-px md:flex"><NavLinks /></nav>
          <div className="ml-auto flex items-center gap-2">
            <div className={cx(mobileNav === "drawer" && "hidden md:block")}><Account /></div>
            {mobileNav === "drawer" && <MobileDrawerButton />}
          </div>
        </div>
        {mobileNav === "top" && <MobileTopTabs />}
        <TerminalTicker />
      </header>
      <Main wide>{children}</Main>
      <SiteFooter />
      {mobileNav === "tabs" && <MobileTabs />}
    </>
  );
}

function Masthead({ children }: { children: ReactNode }) {
  const { mobileNav } = useLayout();
  const day = trToday();
  return (
    <>
      <header className="border-b-4 border-double border-line-strong bg-bg">
        <div className="mx-auto flex max-w-(--mi-page) items-center justify-between gap-4 px-4 py-2 text-[11.5px] text-muted sm:px-6">
          <span className="capitalize">{fmtDate(`${day}T12:00:00Z`)}</span>
          <div className="hidden md:block"><Account /></div>
          <div className="md:hidden">{mobileNav === "drawer" ? <MobileDrawerButton /> : <Account />}</div>
        </div>
        <div className="mx-auto flex max-w-(--mi-page) justify-center border-y border-line px-4 py-5 sm:px-6">
          <Link href="/" aria-label="Match Intelligence AI ana sayfa"><Logo /></Link>
        </div>
        <nav aria-label="Ana menü" className="mx-auto hidden max-w-(--mi-page) justify-center gap-2 px-4 md:flex"><NavLinks /></nav>
        {mobileNav === "top" && <MobileTopTabs />}
      </header>
      <Main>{children}</Main>
      <SiteFooter />
      {mobileNav === "tabs" && <MobileTabs />}
    </>
  );
}

/** Yönetimden açılan bakım/duyuru şeridi (özellik bayrağı: maintenance_notice). */
function NoticeBar() {
  const q = useQuery({ queryKey: ["notice"], queryFn: () => api<{ message: string | null }>("/v1/notice"), staleTime: 60_000, retry: false });
  if (!q.data?.message) return null;
  return (
    <div role="status" className="border-b border-amber/30 bg-amber-soft px-4 py-2 text-center text-[12.5px] text-text" data-testid="site-notice">
      {q.data.message}
    </div>
  );
}

/** Tasarımın kabuğuna göre site çerçevesi (gezinme, içerik genişliği, mobil menü). */
export function SiteShell({ children }: { children: ReactNode }) {
  const { shell } = useLayout();
  const frame =
    shell === "sidebar" ? <Sidebar>{children}</Sidebar>
    : shell === "terminal" ? <Terminal>{children}</Terminal>
    : shell === "masthead" ? <Masthead>{children}</Masthead>
    : <Topbar>{children}</Topbar>;
  return <><NoticeBar />{frame}</>;
}
