"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BarChart3, Home, LayoutDashboard, LogIn, ShieldCheck } from "lucide-react";

import { Logo } from "./Logo";
import { cx } from "./ui";
import { useMe } from "@/lib/hooks";

const NAV = [
  { href: "/", label: "Genel Bakış", icon: Home },
  { href: "/maclar", label: "Maç Merkezi", icon: Activity },
  { href: "/performans", label: "Model Şeffaflığı", icon: BarChart3 },
];

function isActive(path: string, href: string) {
  return href === "/" ? path === "/" : path.startsWith(href);
}

export function SiteHeader() {
  const path = usePathname();
  const { data: me } = useMe();
  return (
    <>
      <header className="sticky top-0 z-30 border-b border-line bg-bg/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-[1240px] items-center gap-4 px-4 sm:gap-8 sm:px-6">
          <Link href="/" className="shrink-0" aria-label="Match Intelligence AI ana sayfa">
            <Logo />
          </Link>
          <nav aria-label="Ana menü" className="hidden items-center gap-1 md:flex">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                aria-current={isActive(path, n.href) ? "page" : undefined}
                className={cx(
                  "rounded-ctl px-3 py-2 text-[13px] font-medium transition-colors",
                  isActive(path, n.href) ? "bg-surface-2 text-text" : "text-text-2 hover:text-text",
                )}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {me?.staff_roles.length ? (
              <Link href="/yonetim" className="hidden items-center gap-1.5 rounded-ctl px-3 py-2 text-[13px] text-text-2 hover:text-text sm:inline-flex">
                <ShieldCheck className="size-4" aria-hidden /> Yönetim
              </Link>
            ) : null}
            {me ? (
              <Link href="/panel" className="inline-flex h-9 items-center gap-2 rounded-ctl border border-line-strong bg-surface-2 px-3 text-[13px] font-medium text-text hover:bg-surface-3">
                <LayoutDashboard className="size-4 text-gold" aria-hidden />
                <span className="max-w-[120px] truncate">{me.display_name}</span>
              </Link>
            ) : (
              <>
                <Link href="/giris" className="hidden h-9 items-center rounded-ctl px-3 text-[13px] font-medium text-text-2 hover:text-text sm:inline-flex">
                  Giriş
                </Link>
                <Link href="/kayit" className="inline-flex h-9 items-center whitespace-nowrap rounded-ctl bg-gold px-3.5 text-[13px] font-semibold text-[#14110a] hover:bg-[#d6b97d]">
                  Ücretsiz başla
                </Link>
              </>
            )}
          </div>
        </div>
      </header>
      {/* Mobil alt gezinme: masaüstü menünün küçültülmüşü değil, başparmak erişimine göre. */}
      <nav aria-label="Mobil menü" className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-bg/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
        <div className="grid grid-cols-4">
          {[...NAV, me ? { href: "/panel", label: "Panelim", icon: LayoutDashboard } : { href: "/giris", label: "Giriş", icon: LogIn }].map((n) => (
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
    </>
  );
}
