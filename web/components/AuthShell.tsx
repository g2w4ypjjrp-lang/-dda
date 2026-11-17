import type { ReactNode } from "react";

import { LogoMark } from "./Logo";

export function AuthShell({ title, subtitle, children, footer }: { title: string; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="mx-auto flex min-h-[calc(100dvh-4rem)] max-w-[420px] flex-col justify-center py-12">
      <div className="rise rounded-card border border-line bg-surface p-7 shadow-card sm:p-8">
        <LogoMark size={34} className="text-text" />
        <h1 className="mt-6 text-[22px] font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-2 text-[13.5px] leading-relaxed text-muted">{subtitle}</p>}
        <div className="mt-7">{children}</div>
      </div>
      {footer && <div className="mt-5 text-center text-[13px] text-muted">{footer}</div>}
    </div>
  );
}
