"use client";

import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ReferenceLine } from "recharts";

import { Card, CardHeader, Empty, ErrorState, Skeleton, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { num, pct } from "@/lib/format";
import type { Performance } from "@/lib/types";

const METHOD = [
  { t: "Zaman sıralı test", d: "Model, ayar seçiminde hiç kullanılmamış sonraki dönemde ölçülür; geçmişe bakarak kendini kandıramaz." },
  { t: "Brier skoru", d: "Olasılıkların gerçekleşen sonuçtan ne kadar uzak olduğunu ölçer. 0 kusursuz; tekdüze tahmin ≈ 0.667." },
  { t: "Log loss", d: "Yanlış ve aşırı emin tahminleri sert cezalandırır. Tekdüze tahmin = 1.099; daha düşük daha iyi." },
  { t: "Kalibrasyon", d: "\"%60\" dediğimiz maçların yaklaşık %60'ı gerçekleşmeli. Grafikteki noktalar köşegene ne kadar yakınsa o kadar iyi." },
];

export default function PerformancePage() {
  const q = useQuery({ queryKey: ["performance"], queryFn: () => api<Performance>("/v1/predictions/performance") });
  const d = q.data;
  return (
    <div className="py-8">
      <div className="eyebrow mb-2">Model Şeffaflığı</div>
      <h1 className="text-[28px] font-semibold tracking-tight">Gerçekleşmiş tahmin performansı</h1>
      <p className="mt-2 max-w-2xl text-[13.5px] leading-relaxed text-muted">
        Bu sayfadaki her rakam, maç başlamadan önce kaydedilmiş ve sonradan değiştirilemeyen tahminlerden hesaplanır.
        Çekimser kalınan maçlar ayrıca sayılır.
      </p>

      {q.isLoading ? (
        <Skeleton className="mt-6 h-72" />
      ) : q.isError || !d ? (
        <Card className="mt-6"><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card>
      ) : d.data_status !== "ok" ? (
        <Card className="mt-6">
          <Empty title="Henüz sonuçlanmış tahmin yok">
            İlk gerçek tahminler sonuçlandıkça Brier skoru, log loss ve kalibrasyon grafiği burada yayımlanacak.
            {d.settled_abstained ? ` Şu ana kadar ${d.settled_abstained} maçta çekimser kalındı.` : ""}
          </Empty>
        </Card>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_1.4fr]">
          <Card className="p-6">
            <div className="grid grid-cols-2 gap-6">
              <Stat label="Sonuçlanan tahmin" value={d.settled_published} hint={`son ${d.window_days} gün`} />
              <Stat label="Çekimser" value={d.settled_abstained} />
              <Stat label="Brier" value={num(d.brier, 3)} hint="tekdüze ≈ 0.667" />
              <Stat label="Log loss" value={num(d.log_loss, 3)} hint={`tekdüze ${num(d.uniform_log_loss, 3)}`} />
              <Stat label="İsabet" value={pct(d.accuracy)} hint="tek başına başarı ölçüsü değildir" />
            </div>
          </Card>
          <Card>
            <CardHeader eyebrow="Güvenilirlik diyagramı" title="Tahmin edilen ↔ gerçekleşen" />
            <div className="h-72 p-4">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 10, right: 16, bottom: 24, left: 0 }}>
                  <CartesianGrid stroke="var(--mi-line)" />
                  <XAxis type="number" dataKey="mean_confidence" domain={[0, 1]} tickFormatter={(v) => `%${Math.round(v * 100)}`} stroke="var(--mi-muted)" fontSize={11} name="Tahmin" />
                  <YAxis type="number" dataKey="observed_rate" domain={[0, 1]} tickFormatter={(v) => `%${Math.round(v * 100)}`} stroke="var(--mi-muted)" fontSize={11} name="Gerçekleşen" />
                  <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="var(--mi-line-strong)" strokeDasharray="4 4" />
                  <Tooltip
                    cursor={{ stroke: "var(--mi-line-strong)" }}
                    contentStyle={{ background: "var(--mi-surface-2)", border: "1px solid var(--mi-line-strong)", borderRadius: 8, fontSize: 12 }}
                    formatter={(v) => `%${(Number(v) * 100).toFixed(1)}`}
                  />
                  <Scatter data={d.reliability} fill="var(--mi-gold)" />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>
      )}

      <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {METHOD.map((m) => (
          <Card key={m.t} className="p-5">
            <h2 className="text-[14px] font-semibold">{m.t}</h2>
            <p className="mt-2 text-[12.5px] leading-relaxed text-muted">{m.d}</p>
          </Card>
        ))}
      </div>
    </div>
  );
}
