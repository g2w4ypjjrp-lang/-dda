"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Star } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { api, del, post } from "@/lib/api";
import { ago } from "@/lib/format";
import { useMe } from "@/lib/hooks";
import { cx } from "./ui";

export interface AppNotification { id: number; category: string; title: string; body: string; link: string | null; created_at: string; read: boolean }
export interface Favorites { teams: { id: number; name: string; logo_url: string | null }[]; competitions: { id: number; name: string; logo_url: string | null }[]; fixtures: number[] }

export function useNotifications(enabled: boolean, limit = 20) {
  return useQuery({
    queryKey: ["notifications", limit],
    queryFn: () => api<{ items: AppNotification[]; unread: number }>(`/v1/notifications?limit=${limit}`),
    enabled,
    refetchInterval: 60_000,
  });
}

export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { ids?: number[]; all?: boolean }) => post("/v1/notifications/read", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

/** Başlıktaki bildirim zili: okunmamış sayısı ve son bildirimler. */
export function NotificationBell() {
  const { data: me } = useMe();
  const q = useNotifications(!!me, 8);
  const read = useMarkRead();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  if (!me) return null;
  const unread = q.data?.unread ?? 0;
  return (
    <div ref={box} className="relative">
      <button type="button" aria-label={`Bildirimler${unread ? ` (${unread} okunmamış)` : ""}`} aria-expanded={open} onClick={() => setOpen(!open)}
        className="relative grid size-9 place-items-center rounded-ctl border border-line text-text-2 hover:text-text">
        <Bell className="size-4" aria-hidden />
        {unread > 0 && <span className="num absolute -right-1 -top-1 grid min-w-[18px] place-items-center rounded-full bg-gold px-1 text-[10px] font-semibold text-accent-text">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div role="dialog" aria-label="Bildirimler" className="absolute right-0 top-11 z-50 w-[min(360px,calc(100vw-24px))] overflow-hidden rounded-card border border-line-strong bg-surface shadow-card">
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <span className="text-[13px] font-semibold">Bildirimler</span>
            {unread > 0 && <button type="button" className="text-[12px] text-gold hover:underline" onClick={() => read.mutate({ all: true })}>Tümünü okundu say</button>}
          </div>
          <ul className="max-h-[60vh] divide-y divide-line overflow-y-auto">
            {q.data?.items.length ? q.data.items.map((n) => (
              <li key={n.id}>
                <Link href={n.link ?? "/bildirimler"} onClick={() => { setOpen(false); if (!n.read) read.mutate({ ids: [n.id] }); }}
                  className={cx("block px-4 py-3 hover:bg-surface-2", !n.read && "bg-gold-soft/40")}>
                  <div className="flex items-start gap-2">
                    {!n.read && <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-gold" aria-label="okunmamış" />}
                    <div className="min-w-0">
                      <div className="text-[13px] font-medium">{n.title}</div>
                      <div className="mt-0.5 line-clamp-2 text-[12px] text-text-2">{n.body}</div>
                      <div className="mt-1 text-[11px] text-muted">{ago(n.created_at)}</div>
                    </div>
                  </div>
                </Link>
              </li>
            )) : <li className="px-4 py-6 text-center text-[12.5px] text-muted">Bildirim yok</li>}
          </ul>
          <Link href="/bildirimler" onClick={() => setOpen(false)} className="block border-t border-line px-4 py-2.5 text-center text-[12.5px] font-medium text-gold hover:bg-surface-2">Tümü ve tercihler</Link>
        </div>
      )}
    </div>
  );
}

export function useFavorites(enabled: boolean) {
  return useQuery({ queryKey: ["favorites"], queryFn: () => api<Favorites>("/v1/favorites"), enabled });
}

/** Favori düğmesi (takım, lig veya maç). Oturum yoksa gösterilmez. */
export function FavoriteButton({ kind, refId, label, compact = false }: { kind: "team" | "competition" | "fixture"; refId: number; label: string; compact?: boolean }) {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const fav = useFavorites(!!me);
  const on = kind === "team" ? !!fav.data?.teams.some((t) => t.id === refId)
    : kind === "competition" ? !!fav.data?.competitions.some((c) => c.id === refId)
    : !!fav.data?.fixtures.includes(refId);
  const toggle = useMutation({
    mutationFn: () => (on ? del(`/v1/favorites/${kind}/${refId}`) : post("/v1/favorites", { kind, ref_id: refId })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["favorites"] }),
  });
  if (!me) return null;
  const text = kind === "fixture" ? (on ? "Kaydedildi" : "Maçı kaydet") : on ? "Favoride" : "Favorilere ekle";
  return (
    <button type="button" aria-pressed={on} aria-label={`${label}: ${on ? "favorilerden çıkar" : "favorilere ekle"}`} disabled={toggle.isPending} onClick={() => toggle.mutate()}
      className={cx("inline-flex items-center gap-1.5 rounded-full border text-[12px] font-medium transition-colors", compact ? "size-7 justify-center" : "h-8 px-3",
        on ? "border-gold/50 bg-gold-soft text-gold" : "border-line text-text-2 hover:text-text")}>
      <Star className={cx("size-3.5", on && "fill-current")} aria-hidden />
      {!compact && text}
    </button>
  );
}
