"use client";

import type { DesignConfig } from "@/lib/design";
import { designAttrs } from "@/lib/design";
import { cx } from "./ui";

/** Bir tasarımın gerçek tokenlarıyla çizilen küçük önizleme (kabuk, kart, olasılık şeridi). */
export function DesignSwatch({ designKey, config, selected, className }: { designKey: string; config: DesignConfig; selected?: boolean; className?: string }) {
  const attrs = designAttrs(designKey, config);
  const shell = config.layout.shell;
  return (
    <div {...attrs} className={cx("overflow-hidden rounded-[10px] border text-left", selected ? "border-gold ring-2 ring-gold/40" : "border-line", className)} aria-hidden>
      <div className="flex h-28" style={{ background: "var(--mi-bg)" }}>
        {shell === "sidebar" && <div className="w-8 shrink-0 border-r border-line bg-bg-elevated" />}
        <div className="flex min-w-0 flex-1 flex-col">
          {shell !== "sidebar" && (
            <div className={cx("flex items-center gap-1.5 border-b border-line px-2", shell === "terminal" ? "h-4" : shell === "masthead" ? "h-7 justify-center" : "h-5")}>
              <span className="size-1.5 rounded-full bg-gold" />
              <span className="h-1 w-8 rounded-full bg-text-2 opacity-60" />
            </div>
          )}
          <div className="grid flex-1 grid-cols-[1.2fr_1fr] gap-1.5 p-2">
            <div className="flex flex-col justify-center gap-1">
              <span className="h-2 w-4/5 rounded-full bg-text opacity-80" />
              <span className="h-2 w-3/5 rounded-full bg-gold" />
              <span className="mt-1 h-1 w-full rounded-full bg-muted opacity-50" />
            </div>
            <div className="mi-card flex flex-col justify-end gap-1 rounded-card border border-line bg-surface p-1.5 shadow-card">
              <div className="flex h-1.5 overflow-hidden rounded-full">
                <span className="w-1/2 bg-home" /><span className="w-1/4 bg-draw" /><span className="w-1/4 bg-away" />
              </div>
              <span className="h-1 w-2/3 rounded-full bg-muted opacity-50" />
            </div>
          </div>
        </div>
      </div>
      <div className="border-t border-line bg-surface px-2.5 py-1.5" style={{ fontFamily: "var(--mi-font-heading)" }}>
        <div className="truncate text-[12px] font-semibold text-text">{config.name}</div>
      </div>
    </div>
  );
}
