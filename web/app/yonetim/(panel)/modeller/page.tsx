"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Crown } from "lucide-react";
import { Fragment, useState } from "react";

import { PageTitle, Table, can, useAdmin, useGuard } from "@/components/admin";
import { Badge, Button, Card, CardHeader, Empty, FormError, Skeleton } from "@/components/ui";
import { api, post } from "@/lib/api";
import { fmtDateTime, num, pct } from "@/lib/format";

interface Brief {
  id: number; scope_key: string; status: string; created_at: string; trained_until: string; components: Record<string, number>;
  excluded: Record<string, string>; temperature: number; n_rows: number;
  test: { n: number | null; log_loss: number | null; brier: number | null; ece: number | null; accuracy: number | null };
  vs_champion?: { champion_id: number; log_loss_delta: number | null; note: string };
}
interface Detail extends Brief {
  metrics: { test: Record<string, { n: number; log_loss: number; brier: number; ece: number; accuracy: number }>; periods: Record<string, { from: string; to: string; n: number }> };
  feature_importance: Record<string, number>;
  trials: { number: number; state: string; value: number | null }[];
  predictions: number;
}

const STATUS = { champion: { tone: "gold", label: "Şampiyon" }, challenger: { tone: "cobalt", label: "Aday" }, retired: { tone: "neutral", label: "Emekli" } } as const;

function DetailPanel({ id }: { id: number }) {
  const q = useQuery({ queryKey: ["admin", "model", id], queryFn: () => api<Detail>(`/admin/v1/models/${id}`) });
  if (q.isLoading || !q.data) return <Skeleton className="m-5 h-48" />;
  const d = q.data;
  const top = Object.entries(d.feature_importance).sort((a, b) => b[1] - a[1]).slice(0, 8);
  return (
    <div className="grid gap-6 p-5 lg:grid-cols-2">
      <div>
        <div className="eyebrow mb-2">Test dönemi (örneklem dışı)</div>
        <p className="mb-2 text-[11.5px] text-muted">{d.metrics.periods?.test ? `${fmtDateTime(d.metrics.periods.test.from)} – ${fmtDateTime(d.metrics.periods.test.to)}` : ""}</p>
        <Table head={["Model", "n", "Log loss", "Brier", "ECE", "İsabet"]} minWidth={460}>
          {Object.entries(d.metrics.test).map(([name, m]) => (
            <tr key={name} className={name === "ensemble" ? "tone-highlight bg-gold-soft/40" : undefined}>
              <td className="px-4 py-2 font-medium">{name}{d.components[name] !== undefined ? ` · ${pct(d.components[name])}` : d.excluded[name] ? " · dışlandı" : ""}</td>
              <td className="num px-4 py-2">{m.n}</td>
              <td className="num px-4 py-2">{num(m.log_loss, 4)}</td>
              <td className="num px-4 py-2">{num(m.brier, 4)}</td>
              <td className="num px-4 py-2">{num(m.ece, 3)}</td>
              <td className="num px-4 py-2">{pct(m.accuracy, 1)}</td>
            </tr>
          ))}
        </Table>
        {Object.keys(d.excluded).length > 0 && (
          <ul className="mt-3 space-y-1 text-[11.5px] text-muted">{Object.entries(d.excluded).map(([k, v]) => <li key={k}>{k}: {v}</li>)}</ul>
        )}
      </div>
      <div className="space-y-5">
        <div>
          <div className="eyebrow mb-2">Özellik önemi (LightGBM)</div>
          {top.length === 0 ? <p className="text-[12px] text-muted">LightGBM ensemble'da değil.</p> : top.map(([k, v]) => (
            <div key={k} className="flex items-center gap-3 py-1 text-[12px]">
              <span className="w-32 truncate text-text-2">{k}</span>
              <div className="h-1.5 flex-1 rounded-full bg-surface-3"><div className="h-full rounded-full bg-cobalt" style={{ width: `${v * 100}%` }} /></div>
              <span className="num w-10 text-right">{pct(v)}</span>
            </div>
          ))}
        </div>
        <div className="text-[12px] text-text-2">
          Optuna: {d.trials.length} deneme ({d.trials.filter((t) => t.state === "COMPLETE").length} tamamlandı, {d.trials.filter((t) => t.state === "PRUNED").length} budandı) · Sıcaklık {num(d.temperature, 2)} · {d.predictions} tahmin
        </div>
      </div>
    </div>
  );
}

export default function ModelLab() {
  const me = useAdmin();
  const qc = useQueryClient();
  const guard = useGuard();
  const [open, setOpen] = useState<number | null>(null);
  const q = useQuery({ queryKey: ["admin", "models"], queryFn: () => api<{ items: Brief[] }>("/admin/v1/models") });
  const promote = useMutation({
    mutationFn: (id: number) => guard(() => post(`/admin/v1/models/${id}/promote`)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "models"] }),
  });
  return (
    <div>
      <PageTitle eyebrow="AI Intelligence" title="Model Lab" />
      <Card>
        <CardHeader eyebrow="Kayıt defteri" title="Model sürümleri" action={<span className="text-[11.5px] text-muted">Eğitim: mi-ml train</span>} />
        <div className="mt-3 border-t border-line">
          {q.isLoading ? <Skeleton className="m-5 h-32" /> : q.data?.items.length === 0 ? (
            <Empty title="Henüz eğitilmiş model yok">Gerçek veriyle `mi-ml train --competition-id …` çalıştırıldığında sürümler burada listelenir.</Empty>
          ) : (
            <Table head={["Sürüm", "Kapsam", "Durum", "Eğitim verisi", "Bileşenler", "Test log loss", "ECE", ""]}>
              {q.data?.items.map((m) => (
                <Fragment key={m.id}>
                  <tr className="cursor-pointer hover:bg-surface-2" onClick={() => setOpen(open === m.id ? null : m.id)}>
                    <td className="px-4 py-2.5 font-medium">#{m.id}</td>
                    <td className="px-4 py-2.5 text-text-2">{m.scope_key}</td>
                    <td className="px-4 py-2.5"><Badge tone={STATUS[m.status as keyof typeof STATUS]?.tone ?? "neutral"}>{m.status === "champion" && <Crown className="size-3" aria-hidden />}{STATUS[m.status as keyof typeof STATUS]?.label ?? m.status}</Badge></td>
                    <td className="px-4 py-2.5 text-text-2">{fmtDateTime(m.trained_until)}</td>
                    <td className="px-4 py-2.5 text-text-2">{Object.keys(m.components).join(", ")}</td>
                    <td className="num px-4 py-2.5">{num(m.test.log_loss, 4)}{m.vs_champion?.log_loss_delta != null && <span className={m.vs_champion.log_loss_delta < 0 ? "text-teal" : "text-red"}> ({m.vs_champion.log_loss_delta > 0 ? "+" : ""}{num(m.vs_champion.log_loss_delta, 4)})</span>}</td>
                    <td className="num px-4 py-2.5">{num(m.test.ece, 3)}</td>
                    <td className="px-4 py-2.5 text-right">
                      {m.status !== "champion" && can(me, "models.manage") && (
                        <Button size="sm" variant="secondary" loading={promote.isPending && promote.variables === m.id} onClick={(e) => { e.stopPropagation(); promote.mutate(m.id); }}>
                          {m.status === "retired" ? "Geri al" : "Şampiyon yap"}
                        </Button>
                      )}
                    </td>
                  </tr>
                  {open === m.id && <tr><td colSpan={8} className="bg-bg-elevated"><DetailPanel id={m.id} /></td></tr>}
                </Fragment>
              ))}
            </Table>
          )}
          <div className="px-5 py-3"><FormError error={promote.error} /></div>
        </div>
      </Card>
    </div>
  );
}
