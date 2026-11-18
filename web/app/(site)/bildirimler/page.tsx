"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useMarkRead, useNotifications } from "@/components/engage";
import { Badge, Button, Card, CardHeader, Empty, FormError, Skeleton, cx } from "@/components/ui";
import { api, put } from "@/lib/api";
import { ago, fmtDateTime } from "@/lib/format";
import { useMe } from "@/lib/hooks";

interface Pref { category: string; label: string; in_app: boolean; email: boolean; locked_in_app: boolean }
const CAT: Record<string, string> = { system: "Duyuru", match: "Maç", result: "Sonuç", subscription: "Abonelik", security: "Güvenlik", coupon: "Kupon" };

export default function NotificationsPage() {
  const router = useRouter();
  const { data: me, isLoading } = useMe();
  const qc = useQueryClient();
  const list = useNotifications(!!me, 100);
  const read = useMarkRead();
  const prefs = useQuery({ queryKey: ["notifications", "prefs"], queryFn: () => api<{ items: Pref[]; email_note: string }>("/v1/notifications/prefs"), enabled: !!me });
  const save = useMutation({
    mutationFn: (p: Record<string, Partial<Record<"in_app" | "email", boolean>>>) => put("/v1/notifications/prefs", { prefs: p }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications", "prefs"] }),
  });
  useEffect(() => { if (!isLoading && me === null) router.replace("/giris?next=/bildirimler"); }, [isLoading, me, router]);
  if (isLoading || !me) return <div className="py-8"><Skeleton className="h-64" /></div>;
  return (
    <div className="py-8">
      <div className="eyebrow mb-2">Hesap</div>
      <h1 className="text-[28px] font-semibold tracking-tight">Bildirimler</h1>
      <div className="mt-6 grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <Card>
          <CardHeader eyebrow={`${list.data?.unread ?? 0} okunmamış`} title="Gelen kutusu" action={list.data?.unread ? <Button size="sm" variant="ghost" onClick={() => read.mutate({ all: true })}>Tümünü okundu say</Button> : undefined} />
          <ul className="mt-3 divide-y divide-line border-t border-line">
            {list.isLoading ? <Skeleton className="m-5 h-24" /> : !list.data?.items.length ? <Empty title="Bildirim yok" icon={<Bell className="size-5" aria-hidden />}>Favori takımlarınızın maçları, kupon sonuçları ve hesap güvenliği burada bildirilir.</Empty> : list.data.items.map((n) => (
              <li key={n.id} className={cx("flex gap-3 px-5 py-3.5", !n.read && "tone-highlight bg-gold-soft/40")}>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 text-[13.5px] font-medium">{n.title}<Badge>{CAT[n.category] ?? n.category}</Badge></div>
                  <p className="mt-1 text-[12.5px] text-text-2">{n.body}</p>
                  <div className="mt-1 text-[11px] text-text-2" title={fmtDateTime(n.created_at)}>{ago(n.created_at)}{n.link && <> · <Link href={n.link} className="text-gold underline underline-offset-2" onClick={() => !n.read && read.mutate({ ids: [n.id] })}>Git</Link></>}</div>
                </div>
                {!n.read && <Button size="sm" variant="ghost" onClick={() => read.mutate({ ids: [n.id] })}>Okundu</Button>}
              </li>
            ))}
          </ul>
        </Card>
        <Card className="h-fit">
          <CardHeader eyebrow="Tercihler" title="Ne zaman haber verelim?" />
          <table className="mt-3 w-full text-[12.5px]">
            <thead><tr className="border-y border-line text-left text-[11px] uppercase tracking-wide text-muted"><th className="px-5 py-2 font-medium">Kategori</th><th className="px-2 py-2 text-center font-medium">Uygulama</th><th className="px-5 py-2 text-center font-medium">E-posta</th></tr></thead>
            <tbody className="divide-y divide-line">
              {prefs.data?.items.map((p) => (
                <tr key={p.category}>
                  <td className="px-5 py-2.5">{p.label}</td>
                  <td className="px-2 py-2.5 text-center"><input type="checkbox" aria-label={`${p.label} uygulama içi`} className="accent-[var(--mi-gold)]" checked={p.in_app} disabled={p.locked_in_app || save.isPending} onChange={(e) => save.mutate({ [p.category]: { in_app: e.target.checked } })} /></td>
                  <td className="px-5 py-2.5 text-center"><input type="checkbox" aria-label={`${p.label} e-posta`} className="accent-[var(--mi-gold)]" checked={p.email} disabled={save.isPending} onChange={(e) => save.mutate({ [p.category]: { email: e.target.checked } })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="px-5 py-4 text-[11.5px] text-muted">Güvenlik bildirimleri uygulama içinde kapatılamaz. {prefs.data?.email_note}</p>
          <div className="px-5 pb-4"><FormError error={save.error} /></div>
        </Card>
      </div>
    </div>
  );
}
