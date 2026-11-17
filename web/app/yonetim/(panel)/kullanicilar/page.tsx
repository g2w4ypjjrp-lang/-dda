"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Fragment, useEffect, useState } from "react";

import { PageTitle, Table, can, useAdmin, useGuard } from "@/components/admin";
import { Badge, Button, Card, CardHeader, Empty, FormError, Input, Skeleton } from "@/components/ui";
import { api, post, put } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

interface UserRow { id: string; email: string; display_name: string; status: string; email_verified: boolean; mfa_enabled: boolean; roles: string[]; created_at: string }
interface UserDetail extends UserRow { suspended_reason: string | null; active_sessions: Record<string, number>; activity: { id: number; occurred_at: string; action: string; ip: string | null }[] }

const ROLES = ["SUPER_ADMIN", "ADMIN", "SUPPORT", "ANALYST", "FINANCE_MANAGER", "OPERATIONS_MANAGER", "CONTENT_MANAGER"];

function UserPanel({ id, onChanged }: { id: string; onChanged: () => void }) {
  const me = useAdmin();
  const guard = useGuard();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "user", id], queryFn: () => api<UserDetail>(`/admin/v1/users/${id}`) });
  const [reason, setReason] = useState("");
  const [roles, setRoles] = useState<string[] | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["admin", "user", id] }); onChanged(); };
  const suspend = useMutation({ mutationFn: () => guard(() => post(`/admin/v1/users/${id}/suspend`, { reason })), onSuccess: refresh });
  const activate = useMutation({ mutationFn: () => guard(() => post(`/admin/v1/users/${id}/activate`)), onSuccess: refresh });
  const saveRoles = useMutation({ mutationFn: (r: string[]) => guard(() => put(`/admin/v1/users/${id}/roles`, { roles: r })), onSuccess: () => { setRoles(null); refresh(); } });
  if (q.isLoading || !q.data) return <Skeleton className="m-5 h-40" />;
  const u = q.data;
  const current = roles ?? u.roles;
  return (
    <div className="grid gap-6 p-5 lg:grid-cols-3">
      <div className="space-y-3 text-[12.5px]">
        <div className="eyebrow">Hesap</div>
        <div>Durum: <Badge tone={u.status === "active" ? "teal" : u.status === "suspended" ? "red" : "neutral"}>{u.status}</Badge></div>
        {u.suspended_reason && <div className="text-muted">Neden: {u.suspended_reason}</div>}
        <div className="text-text-2">Açık oturum: uygulama {u.active_sessions.app ?? 0}, yönetim {u.active_sessions.admin ?? 0}</div>
        {can(me, "users.manage") && (u.status === "active" ? (
          <div className="space-y-2">
            <Input label="Askıya alma nedeni" name="reason" value={reason} onChange={(e) => setReason(e.target.value)} />
            <Button size="sm" variant="danger" disabled={reason.trim().length < 3} loading={suspend.isPending} onClick={() => suspend.mutate()}>Askıya al</Button>
          </div>
        ) : u.status === "suspended" ? (
          <Button size="sm" variant="secondary" loading={activate.isPending} onClick={() => activate.mutate()}>Etkinleştir</Button>
        ) : null)}
        <FormError error={suspend.error ?? activate.error} />
      </div>
      <div className="space-y-2 text-[12.5px]">
        <div className="eyebrow">Yönetici rolleri</div>
        {ROLES.map((r) => (
          <label key={r} className="flex items-center gap-2">
            <input type="checkbox" className="accent-[var(--mi-gold)]" disabled={!can(me, "roles.assign")} checked={current.includes(r)}
              onChange={(e) => setRoles(e.target.checked ? [...current, r] : current.filter((x) => x !== r))} />
            {r}
          </label>
        ))}
        {roles && <Button size="sm" loading={saveRoles.isPending} onClick={() => saveRoles.mutate(roles)}>Rolleri kaydet</Button>}
        {!u.mfa_enabled && <p className="text-[11.5px] text-amber">Rol atanabilmesi için kullanıcı iki adımlı doğrulamayı açmalı.</p>}
        <FormError error={saveRoles.error} />
      </div>
      <div className="text-[12px]">
        {can(me, "data.explore") && (
          <div className="mb-4">
            <div className="eyebrow mb-2">İlişkili kayıtlar</div>
            <div className="flex flex-wrap gap-1.5">
              {([["subscriptions", "subscriptions.read", "Abonelikler"], ["orders", "finance.read", "Ödemeler"], ["coupons", "coupons.read", "Kuponlar"], ["virtual_accounts", "virtual.read", "Sanal hesap"]] as const)
                .filter(([, perm]) => can(me, perm))
                .map(([entity, , label]) => (
                  <Link key={entity} href={`/yonetim/veri-gezgini?e=${entity}&f.user_id=${u.id}`} className="rounded-full border border-line px-2.5 py-1 hover:border-gold hover:text-gold">{label}</Link>
                ))}
            </div>
          </div>
        )}
        <div className="eyebrow mb-2">Son etkinlik</div>
        <ul className="max-h-56 space-y-1.5 overflow-y-auto">
          {u.activity.map((a) => <li key={a.id} className="flex justify-between gap-2"><span className="truncate">{a.action}</span><span className="shrink-0 text-muted">{fmtDateTime(a.occurred_at)}</span></li>)}
        </ul>
      </div>
    </div>
  );
}

export default function UsersPage() {
  const [q, setQ] = useState("");
  useEffect(() => { const v = new URLSearchParams(window.location.search).get("q"); if (v) setQ(v); }, []);
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["admin", "users", q, status, page],
    queryFn: () => api<{ items: UserRow[]; total: number; page_size: number }>(`/admin/v1/users?page=${page}&q=${encodeURIComponent(q)}${status ? `&status=${status}` : ""}`),
  });
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.page_size)) : 1;
  return (
    <div>
      <PageTitle eyebrow="Kullanıcı Yönetimi" title="Kullanıcılar" />
      <Card>
        <div className="flex flex-wrap items-end gap-3 p-5">
          <div className="min-w-[220px] flex-1"><Input label="Ara" name="q" placeholder="E-posta veya ad" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></div>
          <label className="block">
            <span className="mb-1.5 block text-[13px] font-medium text-text-2">Durum</span>
            <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className="h-11 rounded-ctl border border-line-strong bg-bg-elevated px-3 text-sm">
              <option value="">Tümü</option><option value="active">Aktif</option><option value="suspended">Askıda</option><option value="deleted">Silinmiş</option>
            </select>
          </label>
        </div>
        <div className="border-t border-line">
          {list.isLoading ? <Skeleton className="m-5 h-40" /> : list.data?.items.length === 0 ? <Empty title="Kullanıcı bulunamadı" /> : (
            <Table head={["E-posta", "Ad", "Durum", "MFA", "Roller", "Kayıt"]}>
              {list.data?.items.map((u) => (
                <Fragment key={u.id}>
                  <tr className="cursor-pointer hover:bg-surface-2" onClick={() => setOpen(open === u.id ? null : u.id)}>
                    <td className="px-4 py-2.5 font-medium">{u.email}</td>
                    <td className="px-4 py-2.5 text-text-2">{u.display_name}</td>
                    <td className="px-4 py-2.5"><Badge tone={u.status === "active" ? "teal" : u.status === "suspended" ? "red" : "neutral"}>{u.status}</Badge></td>
                    <td className="px-4 py-2.5">{u.mfa_enabled ? "Açık" : "—"}</td>
                    <td className="px-4 py-2.5 text-text-2">{u.roles.join(", ") || "—"}</td>
                    <td className="px-4 py-2.5 text-muted">{fmtDateTime(u.created_at)}</td>
                  </tr>
                  {open === u.id && <tr><td colSpan={6} className="bg-bg-elevated"><UserPanel id={u.id} onChanged={() => qc.invalidateQueries({ queryKey: ["admin", "users"] })} /></td></tr>}
                </Fragment>
              ))}
            </Table>
          )}
        </div>
        <CardHeader title={<span className="text-[12.5px] font-normal text-muted">{list.data?.total ?? 0} kullanıcı · sayfa {page}/{pages}</span>}
          action={<div className="flex gap-2 pb-4"><Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>Önceki</Button><Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => setPage(page + 1)}>Sonraki</Button></div>} />
      </Card>
    </div>
  );
}
