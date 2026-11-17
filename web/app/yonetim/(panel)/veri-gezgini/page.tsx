"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Download, Save, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { PageTitle, useGuard } from "@/components/admin";
import { Badge, Button, Card, Empty, ErrorState, FormError, Skeleton, cx } from "@/components/ui";
import { ApiError, api, del, post } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

interface Column { key: string; label: string; kind: string; choices: string[]; filter: boolean; link: string | null }
interface EntityInfo { key: string; label: string; searchable: boolean; default_sort: string; columns: Column[]; related: { entity: string; column: string; label: string }[] }
interface Page { entity: EntityInfo; total: number; page: number; page_size: number; rows: Record<string, unknown>[] }
interface Saved { id: number; name: string; params: Record<string, string> }

function readUrl(): { entity: string | null; params: Record<string, string> } {
  const sp = new URLSearchParams(window.location.search);
  const params: Record<string, string> = {};
  for (const [k, v] of sp) if (k !== "e") params[k] = v;
  return { entity: sp.get("e"), params };
}

function cell(col: Column, v: unknown) {
  if (v === null || v === undefined) return <span className="text-muted">—</span>;
  if (col.kind === "datetime") return fmtDateTime(String(v));
  if (col.kind === "bool") return v ? "Evet" : "Hayır";
  if (col.kind === "float") return Number(v).toFixed(4);
  return String(v);
}

export default function DataExplorer() {
  const guard = useGuard();
  const qc = useQueryClient();
  const meta = useQuery({ queryKey: ["admin", "explorer"], queryFn: () => api<{ items: EntityInfo[]; can_export: boolean }>("/admin/v1/explorer"), retry: false });
  const [entity, setEntity] = useState<string | null>(null);
  const [params, setParams] = useState<Record<string, string>>({});
  const [page, setPage] = useState(1);
  const [qInput, setQInput] = useState("");
  const [saveName, setSaveName] = useState("");

  useEffect(() => {
    const u = readUrl();
    if (u.entity) { setEntity(u.entity); setParams(u.params); setQInput(u.params.q ?? ""); }
  }, []);
  useEffect(() => { if (!entity && meta.data?.items[0]) setEntity(meta.data.items[0].key); }, [meta.data, entity]);
  useEffect(() => {
    if (!entity) return;
    const sp = new URLSearchParams({ e: entity, ...params });
    window.history.replaceState(null, "", `?${sp}`);
  }, [entity, params]);

  const query = useMemo(() => new URLSearchParams({ ...params, page: String(page), page_size: "25" }).toString(), [params, page]);
  const rows = useQuery({ queryKey: ["admin", "explorer", entity, query], queryFn: () => api<Page>(`/admin/v1/explorer/${entity}?${query}`), enabled: !!entity, retry: false });
  const saved = useQuery({ queryKey: ["admin", "explorer", "saved", entity], queryFn: () => api<{ items: Saved[] }>(`/admin/v1/explorer/${entity}/filters`), enabled: !!entity });
  const save = useMutation({
    mutationFn: () => post(`/admin/v1/explorer/${entity}/filters`, { name: saveName.trim(), params }),
    onSuccess: () => { setSaveName(""); qc.invalidateQueries({ queryKey: ["admin", "explorer", "saved", entity] }); },
  });
  const removeSaved = useMutation({
    mutationFn: (id: number) => del(`/admin/v1/explorer/filters/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "explorer", "saved", entity] }),
  });
  const exportCsv = useMutation({
    mutationFn: () => guard(async () => {
      const res = await fetch(`/admin/v1/explorer/${entity}/export.csv?${new URLSearchParams(params)}`, { credentials: "same-origin" });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { code?: string; detail?: string };
        throw new ApiError(res.status, body.code ?? `http_${res.status}`, body.detail ?? "Dışa aktarılamadı");
      }
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${entity}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    }),
  });

  const set = (patch: Record<string, string | null>) => {
    setPage(1);
    setParams((p) => {
      const n = { ...p };
      for (const [k, v] of Object.entries(patch)) { if (v === null || v === "") delete n[k]; else n[k] = v; }
      return n;
    });
  };
  const switchEntity = (key: string, preset: Record<string, string> = {}) => { setEntity(key); setParams(preset); setQInput(preset.q ?? ""); setPage(1); };

  if (meta.isLoading) return <><PageTitle eyebrow="Platform" title="Data Explorer" /><Skeleton className="h-96" /></>;
  if (meta.error) return <><PageTitle eyebrow="Platform" title="Data Explorer" /><Card><ErrorState error={meta.error} /></Card></>;
  const info = rows.data?.entity ?? meta.data?.items.find((e) => e.key === entity);
  const sort = params.sort ?? info?.default_sort;
  const desc = params.dir !== "asc";
  const pages = rows.data ? Math.max(1, Math.ceil(rows.data.total / rows.data.page_size)) : 1;

  return (
    <>
      <PageTitle eyebrow="Platform" title="Data Explorer">
        {meta.data?.can_export && (
          <Button size="sm" variant="secondary" loading={exportCsv.isPending} onClick={() => exportCsv.mutate()}><Download className="size-4" aria-hidden />CSV dışa aktar</Button>
        )}
      </PageTitle>
      <p className="-mt-3 mb-4 max-w-3xl text-[13px] text-muted">Yalnızca yetkili olduğunuz kayıt türleri ve izin verilen alanlar gösterilir; parola özeti, MFA sırrı, belirteç gibi alanlar hiçbir zaman listelenmez. Dışa aktarma denetim kaydına yazılır.</p>
      <FormError error={exportCsv.error} />

      <div className="mb-4 flex flex-wrap gap-1.5" role="tablist" aria-label="Kayıt türü">
        {meta.data?.items.map((e) => (
          <button key={e.key} type="button" role="tab" aria-selected={e.key === entity} onClick={() => switchEntity(e.key)}
            className={cx("h-8 rounded-full px-3 text-[12.5px] font-medium", e.key === entity ? "bg-gold-soft text-gold" : "border border-line text-text-2 hover:text-text")}>
            {e.label}
          </button>
        ))}
      </div>

      {info && (
        <Card className="mb-4 p-4">
          <div className="flex flex-wrap items-end gap-3">
            {info.searchable && (
              <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); set({ q: qInput.trim() || null }); }}>
                <label className="block text-[12.5px]"><span className="mb-1 block text-text-2">Ara</span>
                  <input aria-label="Ara" value={qInput} onChange={(e) => setQInput(e.target.value)} className="h-9 w-56 rounded-ctl border border-line-strong bg-bg-elevated px-3 text-[13px]" />
                </label>
                <Button size="sm" type="submit" variant="secondary"><Search className="size-3.5" aria-hidden />Ara</Button>
              </form>
            )}
            {info.columns.filter((c) => c.filter).map((c) => (
              <label key={c.key} className="block text-[12.5px]"><span className="mb-1 block text-text-2">{c.label}</span>
                {c.kind === "enum" || c.kind === "bool" ? (
                  <select aria-label={c.label} value={params[`f.${c.key}`] ?? ""} onChange={(e) => set({ [`f.${c.key}`]: e.target.value })} className="h-9 rounded-ctl border border-line-strong bg-bg-elevated px-2 text-[13px]">
                    <option value="">Tümü</option>
                    {(c.kind === "bool" ? ["true", "false"] : c.choices).map((o) => <option key={o} value={o}>{c.kind === "bool" ? (o === "true" ? "Evet" : "Hayır") : o}</option>)}
                  </select>
                ) : (
                  <input aria-label={c.label} defaultValue={params[`f.${c.key}`] ?? ""} key={`${entity}-${c.key}-${params[`f.${c.key}`] ?? ""}`}
                    onBlur={(e) => set({ [`f.${c.key}`]: e.target.value.trim() || null })} onKeyDown={(e) => e.key === "Enter" && set({ [`f.${c.key}`]: (e.target as HTMLInputElement).value.trim() || null })}
                    className="h-9 w-40 rounded-ctl border border-line-strong bg-bg-elevated px-3 font-mono text-[12px]" />
                )}
              </label>
            ))}
            {Object.keys(params).length > 0 && <Button size="sm" variant="ghost" onClick={() => { setParams({}); setQInput(""); }}><X className="size-3.5" aria-hidden />Temizle</Button>}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3 text-[12px]">
            <span className="text-muted">Kayıtlı filtreler:</span>
            {saved.data?.items.length ? saved.data.items.map((f) => (
              <span key={f.id} className="inline-flex items-center gap-1 rounded-full border border-line pl-2.5">
                <button type="button" className="hover:text-gold" onClick={() => { setParams(f.params); setQInput(f.params.q ?? ""); setPage(1); }}>{f.name}</button>
                <button type="button" aria-label={`${f.name} filtresini sil`} className="px-1.5 text-muted hover:text-text" onClick={() => removeSaved.mutate(f.id)}><X className="size-3" aria-hidden /></button>
              </span>
            )) : <span className="text-muted">yok</span>}
            <form className="ml-auto flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
              <input aria-label="Filtre adı" placeholder="Filtre adı" value={saveName} onChange={(e) => setSaveName(e.target.value)} className="h-8 w-40 rounded-ctl border border-line bg-bg-elevated px-2" />
              <Button size="sm" variant="ghost" type="submit" disabled={!saveName.trim()} loading={save.isPending}><Save className="size-3.5" aria-hidden />Kaydet</Button>
            </form>
          </div>
          <FormError error={save.error} />
        </Card>
      )}

      <Card className="overflow-hidden">
        {rows.isLoading ? <Skeleton className="m-5 h-48" /> : rows.error ? <ErrorState error={rows.error} /> : !rows.data || rows.data.rows.length === 0 ? (
          <Empty title="Kayıt bulunamadı">Filtreleri değiştirin.</Empty>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="mi-table num w-full min-w-[720px] text-[12.5px]">
                <thead>
                  <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-muted">
                    {info!.columns.map((c) => (
                      <th key={c.key} className="px-3 py-2.5 font-medium">
                        <button type="button" className="inline-flex items-center gap-1 hover:text-text" onClick={() => set({ sort: c.key, dir: sort === c.key && desc ? "asc" : "desc" })}>
                          {c.label}{sort === c.key && (desc ? <ArrowDown className="size-3" aria-hidden /> : <ArrowUp className="size-3" aria-hidden />)}
                        </button>
                      </th>
                    ))}
                    {info!.related.length > 0 && <th className="px-3 py-2.5 font-medium">İlişkili</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {rows.data.rows.map((r, idx) => (
                    <tr key={idx} className="hover:bg-surface-2">
                      {info!.columns.map((c) => (
                        <td key={c.key} className="max-w-[260px] truncate px-3 py-2" title={r[c.key] === null ? undefined : String(r[c.key])}>
                          {c.link && r[c.key] !== null ? (
                            <button type="button" className="text-gold hover:underline" onClick={() => switchEntity(c.link!, { "f.id": String(r[c.key]) })}>{cell(c, r[c.key])}</button>
                          ) : cell(c, r[c.key])}
                        </td>
                      ))}
                      {info!.related.length > 0 && (
                        <td className="px-3 py-2">
                          <div className="flex flex-wrap gap-1">
                            {info!.related.filter((rel) => meta.data?.items.some((e) => e.key === rel.entity)).map((rel) => (
                              <button key={`${rel.entity}-${rel.column}`} type="button" onClick={() => switchEntity(rel.entity, { [`f.${rel.column}`]: String(r.id) })}>
                                <Badge>{rel.label}</Badge>
                              </button>
                            ))}
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-[12px] text-muted">
              <span>{rows.data.total.toLocaleString("tr-TR")} kayıt</span>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>Önceki</Button>
                <span className="num">{page} / {pages}</span>
                <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => setPage(page + 1)}>Sonraki</Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
