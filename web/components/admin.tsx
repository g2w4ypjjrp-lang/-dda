"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  Activity, AlertTriangle, BrainCircuit, CheckCircle2, CircleDashed, Clock, Database, FileClock, LayoutGrid, LogOut,
  ShieldCheck, Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { ApiError, post } from "@/lib/api";
import { useAdminMe, useLogout } from "@/lib/hooks";
import type { AdminMe } from "@/lib/types";
import { Logo } from "./Logo";
import { Badge, Button, FormError, Input, Skeleton, cx } from "./ui";

const NAV = [
  { href: "/yonetim", label: "Command Center", icon: LayoutGrid, perm: null },
  { href: "/yonetim/veri", label: "Futbol Veri Merkezi", icon: Database, perm: "football.read" },
  { href: "/yonetim/modeller", label: "Model Lab", icon: BrainCircuit, perm: "models.read" },
  { href: "/yonetim/kullanicilar", label: "Kullanıcılar", icon: Users, perm: "users.read" },
  { href: "/yonetim/denetim", label: "Denetim Kaydı", icon: FileClock, perm: "audit.read" },
] as const;

const AdminContext = createContext<AdminMe | null>(null);
export const useAdmin = () => useContext(AdminContext);
export const can = (me: AdminMe | null, perm: string) => !!me?.permissions.includes(perm);

/* --- Yeniden doğrulama: hassas işlem "reauth_required" dönerse pencere açılır, sonra işlem tekrarlanır. --- */

type Guard = <T>(fn: () => Promise<T>) => Promise<T>;
const ReauthContext = createContext<Guard>((fn) => fn());
export const useGuard = () => useContext(ReauthContext);

function ReauthDialog({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => first.current?.focus(), []);
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="reauth-title" className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm" onKeyDown={(e) => e.key === "Escape" && onCancel()}>
      <form
        className="w-full max-w-sm rounded-card border border-line-strong bg-surface p-6 shadow-card"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await post("/admin/v1/auth/reauth", { password, code });
            onDone();
          } catch (err) {
            setError(err);
          } finally {
            setBusy(false);
          }
        }}
      >
        <ShieldCheck className="size-6 text-gold" aria-hidden />
        <h2 id="reauth-title" className="mt-4 text-lg font-semibold">Kimliğinizi doğrulayın</h2>
        <p className="mt-1 text-[13px] text-muted">Bu kritik işlem için parolanızı ve doğrulama kodunuzu yeniden girin. Doğrulama 5 dakika geçerlidir.</p>
        <div className="mt-5 space-y-3">
          <Input ref={first} label="Parola" type="password" name="reauth-password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <Input label="Doğrulama kodu" name="reauth-code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
          <FormError error={error} />
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onCancel}>Vazgeç</Button>
          <Button type="submit" loading={busy}>Doğrula</Button>
        </div>
      </form>
    </div>
  );
}

function ReauthProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<{ resolve: () => void; reject: (e: unknown) => void } | null>(null);
  const qc = useQueryClient();
  const guard = useCallback<Guard>(
    async (fn) => {
      try {
        return await fn();
      } catch (e) {
        if (!(e instanceof ApiError && e.code === "reauth_required")) throw e;
        await new Promise<void>((resolve, reject) => setPending({ resolve, reject }));
        await qc.invalidateQueries({ queryKey: ["admin-me"] });
        return fn();
      }
    },
    [qc],
  );
  return (
    <ReauthContext.Provider value={guard}>
      {children}
      {pending && (
        <ReauthDialog
          onDone={() => { pending.resolve(); setPending(null); }}
          onCancel={() => { pending.reject(new ApiError(403, "reauth_cancelled", "İşlem iptal edildi")); setPending(null); }}
        />
      )}
    </ReauthContext.Provider>
  );
}

export function AdminShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const { data: me, isLoading } = useAdminMe();
  const logout = useLogout("admin");

  useEffect(() => {
    if (!isLoading && me === null) router.replace("/yonetim/giris");
  }, [isLoading, me, router]);

  if (isLoading || !me) {
    return <div className="grid min-h-dvh place-items-center"><Skeleton className="h-10 w-48" /></div>;
  }
  const items = NAV.filter((n) => !n.perm || can(me, n.perm));
  return (
    <AdminContext.Provider value={me}>
      <ReauthProvider>
        <div className="min-h-dvh md:grid md:grid-cols-[248px_1fr]">
          <aside className="border-b border-line bg-bg-elevated md:sticky md:top-0 md:h-dvh md:border-b-0 md:border-r">
            <div className="flex h-16 items-center px-5"><Link href="/yonetim"><Logo /></Link></div>
            <nav aria-label="Yönetim menüsü" className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:overflow-visible">
              {items.map((n) => {
                const active = n.href === "/yonetim" ? path === n.href : path.startsWith(n.href);
                return (
                  <Link
                    key={n.href}
                    href={n.href}
                    aria-current={active ? "page" : undefined}
                    className={cx("flex shrink-0 items-center gap-2.5 rounded-ctl px-3 py-2 text-[13px] font-medium", active ? "bg-surface-2 text-text" : "text-text-2 hover:text-text")}
                  >
                    <n.icon className={cx("size-4", active ? "text-gold" : "text-muted")} aria-hidden />
                    {n.label}
                  </Link>
                );
              })}
            </nav>
            <div className="hidden px-5 py-4 md:absolute md:bottom-0 md:block md:w-full">
              <div className="truncate text-[12.5px] font-medium">{me.display_name}</div>
              <div className="truncate text-[11px] text-muted">{me.roles.join(", ")}</div>
              <div className="mt-3 flex gap-2">
                <Link href="/" className="inline-flex items-center gap-1 text-[12px] text-text-2 hover:text-text"><Activity className="size-3.5" aria-hidden />Site</Link>
                <button type="button" onClick={async () => { await logout(); router.push("/yonetim/giris"); }} className="ml-auto inline-flex items-center gap-1 text-[12px] text-text-2 hover:text-text">
                  <LogOut className="size-3.5" aria-hidden />Çıkış
                </button>
              </div>
            </div>
          </aside>
          <main className="min-w-0 px-4 py-6 sm:px-8 sm:py-8">{children}</main>
        </div>
      </ReauthProvider>
    </AdminContext.Provider>
  );
}

export function PageTitle({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <div className="eyebrow mb-1.5">{eyebrow}</div>
        <h1 className="text-[24px] font-semibold tracking-tight">{title}</h1>
      </div>
      {children}
    </div>
  );
}

export function Table({ head, children, minWidth = 720 }: { head: string[]; children: ReactNode; minWidth?: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12.5px]" style={{ minWidth }}>
        <thead>
          <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-muted">
            {head.map((h) => <th key={h} className="px-4 py-2.5 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
    </div>
  );
}

export function RunStatus({ s }: { s: string }) {
  if (s === "succeeded") return <Badge tone="teal"><CheckCircle2 className="size-3" aria-hidden />Başarılı</Badge>;
  if (s === "failed") return <Badge tone="red"><AlertTriangle className="size-3" aria-hidden />Hata</Badge>;
  if (s === "skipped") return <Badge tone="amber"><CircleDashed className="size-3" aria-hidden />Atlandı</Badge>;
  return <Badge><Clock className="size-3" aria-hidden />Sürüyor</Badge>;
}
