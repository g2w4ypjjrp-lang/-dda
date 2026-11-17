"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, Lock } from "lucide-react";

import { PageTitle } from "@/components/admin";
import { Card, ErrorState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

interface Matrix { permissions: { code: string; label: string; sensitive: boolean }[]; roles: { code: string; label: string; permissions: string[] }[] }

export default function RolesMatrix() {
  const q = useQuery({ queryKey: ["admin", "roles-matrix"], queryFn: () => api<Matrix>("/admin/v1/roles/matrix") });
  return (
    <>
      <PageTitle eyebrow="Kullanıcı & Güvenlik" title="Rol ve Yetki" />
      <p className="-mt-3 mb-5 max-w-3xl text-[13px] text-muted">Yetki kontrolü her istekte sunucuda yapılır. <Lock className="inline size-3.5" aria-hidden /> işaretli izinler hassastır: son 5 dakikada parola ve doğrulama koduyla yeniden doğrulama ister. Rol atama Kullanıcılar sayfasından yapılır (roles.assign).</p>
      {q.isLoading ? <Skeleton className="h-96" /> : q.error || !q.data ? <Card><ErrorState error={q.error} /></Card> : (
        <Card className="overflow-x-auto">
          <table className="mi-table w-full min-w-[960px] text-[12px]">
            <thead>
              <tr className="border-b border-line text-left text-[10.5px] uppercase tracking-wide text-muted">
                <th className="sticky left-0 bg-surface px-4 py-2.5 font-medium">İzin</th>
                {q.data.roles.map((r) => <th key={r.code} className="px-2 py-2.5 text-center font-medium" title={r.label}>{r.code.replace("_", " ")}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {q.data.permissions.map((p) => (
                <tr key={p.code}>
                  <td className="sticky left-0 bg-surface px-4 py-2"><div className="flex items-center gap-1.5 font-mono">{p.code}{p.sensitive && <Lock className="size-3 text-amber" aria-label="hassas" />}</div><div className="text-[11px] text-muted">{p.label}</div></td>
                  {q.data.roles.map((r) => <td key={r.code} className="px-2 py-2 text-center">{r.permissions.includes(p.code) ? <Check className="mx-auto size-4 text-teal" aria-label="var" /> : <span className="text-muted" aria-label="yok">·</span>}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
