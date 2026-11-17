"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CornerDownLeft, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";

import { api } from "@/lib/api";
import { cx } from "./ui";

interface Hit { type: string; id: string; label: string; hint: string; href: string }
interface Entry { key: string; label: string; hint: string; href: string; icon?: LucideIcon }

const TYPE_LABEL: Record<string, string> = { user: "Kullanıcı", team: "Takım", order: "Sipariş", fixture: "Maç", coupon: "Kupon" };

/** Ctrl+K / Cmd+K: modüllere git ve yetkili kayıtlarda ara (sonuçlar sunucuda yetkiye göre süzülür). */
export function CommandPalette({ open, onClose, items }: { open: boolean; onClose: () => void; items: readonly { href: string; label: string; group: string; icon: LucideIcon }[] }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (open) { setQ(""); setActive(0); setTimeout(() => input.current?.focus(), 0); } }, [open]);
  useEffect(() => { const t = setTimeout(() => setDebounced(q.trim()), 200); return () => clearTimeout(t); }, [q]);
  const search = useQuery({
    queryKey: ["admin", "search", debounced],
    queryFn: () => api<{ items: Hit[] }>(`/admin/v1/search?q=${encodeURIComponent(debounced)}`),
    enabled: open && debounced.length >= 2,
  });
  const entries = useMemo<Entry[]>(() => {
    const term = q.trim().toLocaleLowerCase("tr");
    const modules = items
      .filter((n) => !term || n.label.toLocaleLowerCase("tr").includes(term) || n.group.toLocaleLowerCase("tr").includes(term))
      .map((n) => ({ key: n.href, label: n.label, hint: n.group, href: n.href, icon: n.icon }));
    const hits = (search.data?.items ?? []).map((h) => ({ key: `${h.type}:${h.id}`, label: h.label, hint: `${TYPE_LABEL[h.type] ?? h.type} · ${h.hint}`, href: h.href }));
    return [...modules, ...hits];
  }, [q, items, search.data]);
  useEffect(() => setActive(0), [q]);
  if (!open) return null;
  const go = (e: Entry | undefined) => { if (e) { onClose(); router.push(e.href); } };
  return (
    <div role="dialog" aria-modal="true" aria-label="Komut paleti" className="fixed inset-0 z-[80] flex items-start justify-center bg-black/50 p-4 pt-[12vh] backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-xl overflow-hidden rounded-card border border-line-strong bg-surface shadow-card" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Search className="size-4 text-muted" aria-hidden />
          <input
            ref={input}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              else if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(entries.length - 1, a + 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
              else if (e.key === "Enter") { e.preventDefault(); go(entries[active]); }
            }}
            placeholder="Modül, e-posta, takım veya sipariş/maç/kupon no…"
            aria-label="Komut ara"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            className="h-12 w-full bg-transparent text-[14px] outline-none placeholder:text-muted"
          />
          <kbd className="rounded border border-line px-1.5 font-mono text-[10.5px] text-muted">Esc</kbd>
        </div>
        <ul id="palette-list" role="listbox" className="max-h-[50vh] overflow-y-auto p-2">
          {entries.length === 0 && <li className="px-3 py-6 text-center text-[13px] text-muted">{search.isFetching ? "Aranıyor…" : "Sonuç yok"}</li>}
          {entries.map((e, i) => (
            <li key={e.key} role="option" aria-selected={i === active}>
              <button type="button" onMouseEnter={() => setActive(i)} onClick={() => go(e)}
                className={cx("flex w-full items-center gap-3 rounded-ctl px-3 py-2 text-left text-[13px]", i === active ? "bg-surface-2 text-text" : "text-text-2")}>
                {e.icon ? <e.icon className="size-4 text-muted" aria-hidden /> : <ArrowRight className="size-4 text-muted" aria-hidden />}
                <span className="min-w-0 flex-1 truncate">{e.label}</span>
                <span className="shrink-0 text-[11.5px] text-muted">{e.hint}</span>
                {i === active && <CornerDownLeft className="size-3.5 text-muted" aria-hidden />}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
