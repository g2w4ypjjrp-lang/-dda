import type { ReactNode } from "react";

import { SiteShell } from "@/components/SiteHeader";

export default function SiteLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <a href="#icerik" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-ctl focus:bg-gold focus:px-3 focus:py-2 focus:text-accent-text">
        İçeriğe atla
      </a>
      <SiteShell>{children}</SiteShell>
    </>
  );
}
