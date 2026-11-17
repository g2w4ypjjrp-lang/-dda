"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  BadgeCheck, Brain, Database, Gauge, History, ShieldCheck, Sigma,
} from "lucide-react";

import { HomeHero } from "@/components/heroes";
import { DataStatusBanner, MatchList } from "@/components/match";
import { Badge, Card, CardHeader, Empty, ErrorState, ProbBar, Skeleton, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { num, pct, trToday } from "@/lib/format";
import type { FixtureList, Performance, Prediction } from "@/lib/types";

function useToday() {
  const day = trToday();
  const fixtures = useQuery({
    queryKey: ["fixtures", day],
    queryFn: () => api<FixtureList>(`/v1/football/fixtures?date=${day}`),
    refetchInterval: 60_000,
  });
  const predictions = useQuery({
    queryKey: ["predictions", day],
    queryFn: () => api<{ items: Prediction[] }>(`/v1/predictions?date=${day}`),
  });
  return { day, fixtures, predictions };
}

const PILLARS = [
  { icon: Database, title: "Gerçek veri, kaynak izi", body: "Her skor ve istatistik lisanslı sağlayıcıdan gelir; kaynağı ve son güncelleme zamanı kayıtlıdır. Eski veri canlı gibi gösterilmez." },
  { icon: Sigma, title: "Sızıntısız modeller", body: "Poisson, Dixon-Coles, Elo ve gradyan artırma modelleri yalnızca maçtan önce bilinen veriyle eğitilir; zaman sırasıyla, hiç görülmemiş dönemde test edilir." },
  { icon: Gauge, title: "Olasılık ≠ güvenilirlik", body: "Olayın olasılığı, modelin güvenilirliği, veri kalitesi ve modeller arası uyum ayrı ayrı gösterilir. Yetersiz veride tahmin vermeyiz." },
  { icon: History, title: "Değiştirilemez geçmiş", body: "Tahminler maç başlamadan önce kaydedilir ve sonradan değiştirilemez. Performans yalnızca sonuçlanmış gerçek tahminlerden hesaplanır." },
];

const PLANS = [
  { name: "FREE", tag: "Başlangıç", items: ["Günün maçları ve canlı skorlar", "Temel maç istatistikleri", "Günlük sınırlı AI analizi", "Model şeffaflık raporu"] },
  { name: "PRO", tag: "Analist", highlight: true, items: ["Tüm AI analizleri ve piyasalar", "Olasılık + belirsizlik aralıkları", "Kupon oluşturucu (sanal)", "Gelişmiş istatistik ve geçmiş"] },
  { name: "ELITE", tag: "Profesyonel", items: ["Model karşılaştırmaları", "Gelişmiş filtreler ve raporlar", "Gelişmiş sanal portföy simülasyonu", "Yeni özelliklere öncelikli erişim"] },
];

const FAQ = [
  { q: "Tahminler kazanç garantisi veriyor mu?", a: "Hayır. Olasılıklar istatistiksel tahmindir; en iyi model bile sık sık yanılır. Platform gerçek para ile bahis yapmaz ve aracılık etmez." },
  { q: "Model neden bazı maçlarda tahmin vermiyor?", a: "Takım geçmişi yetersizse, veri eskiyse, modeller birbirinden çok farklı düşünüyorsa veya belirsizlik çok genişse tahmin yayımlanmaz ve nedeni gösterilir." },
  { q: "Model performansını nereden görebilirim?", a: "Model Şeffaflığı sayfasında; yalnızca maçtan önce yayımlanmış ve sonuçlanmış tahminlerden hesaplanan Brier skoru, log loss ve kalibrasyon grafiği yer alır." },
  { q: "Verileriniz nereden geliyor?", a: "Lisanslı futbol veri sağlayıcılarından. Her maç sayfasında kaynak ve son güncelleme zamanı yazar." },
];

export default function HomePage() {
  const { day, fixtures, predictions } = useToday();
  const perf = useQuery({ queryKey: ["performance"], queryFn: () => api<Performance>("/v1/predictions/performance") });
  const items = fixtures.data?.items ?? [];
  const preds = predictions.data?.items ?? [];
  const byFixture = new Map(preds.map((p) => [p.fixture_id, p]));
  const published = preds.filter((p) => p.status === "published");

  return (
    <div className="pb-8">
      <HomeHero d={{ day, list: fixtures.data, items, preds, published, perf: perf.data, loading: fixtures.isLoading || predictions.isLoading }} />

      <div className="mb-6"><DataStatusBanner status={fixtures.data} items={fixtures.data?.items} /></div>

      {/* Günün maçları + AI */}
      <section className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <Card>
          <CardHeader
            eyebrow="Canlı veri"
            title="Günün maçları"
            action={<Link href="/maclar" className="text-[13px] font-medium text-gold hover:underline">Tümü</Link>}
          />
          <div className="mt-3 divide-y divide-line border-t border-line">
            {fixtures.isLoading ? (
              <div className="space-y-3 p-5">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-12" />)}</div>
            ) : fixtures.isError ? (
              <ErrorState error={fixtures.error} onRetry={() => fixtures.refetch()} />
            ) : items.length === 0 ? (
              <Empty title="Bugün için maç yok">Takip edilen liglerde bugün maç bulunmuyor veya veri henüz gelmedi.</Empty>
            ) : (
              <MatchList fixtures={items.slice(0, 8)} byFixture={byFixture} />
            )}
          </div>
        </Card>

        <Card>
          <CardHeader eyebrow="AI Intelligence" title="Öne çıkan analizler" action={<Brain className="size-4 text-gold" aria-hidden />} />
          <div className="mt-3 space-y-1 border-t border-line p-2">
            {predictions.isLoading ? (
              <div className="space-y-3 p-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16" />)}</div>
            ) : published.length === 0 ? (
              <Empty title="Bugün yayımlanmış analiz yok" icon={<Brain className="size-5" aria-hidden />}>
                Model yalnızca yeterli veri ve test edilmiş güvenilirlik olduğunda tahmin yayımlar.
              </Empty>
            ) : (
              published
                .sort((a, b) => Math.max(...Object.values(b.probabilities!["1x2"])) - Math.max(...Object.values(a.probabilities!["1x2"])))
                .slice(0, 5)
                .map((p) => {
                  const f = items.find((x) => x.id === p.fixture_id);
                  return (
                    <Link key={p.id} href={`/maclar/${p.fixture_id}`} className="block rounded-ctl p-3 hover:bg-surface-2">
                      <div className="mb-2 flex items-center justify-between gap-3 text-[13px]">
                        <span className="truncate font-medium text-text">{f ? `${f.home.name} – ${f.away.name}` : `Maç #${p.fixture_id}`}</span>
                        <Badge tone={p.reliability.level === "high" ? "teal" : p.reliability.level === "medium" ? "gold" : "neutral"}>
                          {p.reliability.label}
                        </Badge>
                      </div>
                      <ProbBar p={p.probabilities!["1x2"]} size="sm" />
                    </Link>
                  );
                })
            )}
          </div>
        </Card>
      </section>

      {/* Model performansı */}
      <section className="mt-6">
        <Card className="overflow-hidden">
          <div className="grid gap-6 p-6 md:grid-cols-[1fr_2fr] md:items-center">
            <div>
              <div className="eyebrow mb-2">Model performansı</div>
              <h2 className="text-xl font-semibold tracking-tight">Ölçülen, saklanmayan performans</h2>
              <p className="mt-2 text-[13px] leading-relaxed text-muted">
                Yalnızca maçtan önce yayımlanmış ve sonuçlanmış tahminlerden. Doğruluk tek başına ölçü değildir;
                olasılıkların kalibrasyonu da gösterilir.
              </p>
            </div>
            {perf.data?.data_status === "ok" ? (
              <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
                <Stat label="Sonuçlanan" value={perf.data.settled_published} />
                <Stat label="Brier" value={num(perf.data.brier, 3)} hint="düşük daha iyi" />
                <Stat label="Log loss" value={num(perf.data.log_loss, 3)} hint={`tekdüze: ${num(perf.data.uniform_log_loss, 3)}`} />
                <Stat label="İsabet" value={pct(perf.data.accuracy)} />
              </div>
            ) : (
              <Empty title="Henüz sonuçlanmış tahmin yok" icon={<ShieldCheck className="size-5" aria-hidden />}>
                Performans metrikleri ilk gerçek tahminler sonuçlandıkça burada yayımlanacak. Örnek veya tahmini
                rakam göstermiyoruz.
              </Empty>
            )}
          </div>
        </Card>
      </section>

      {/* Güven ve şeffaflık */}
      <section className="mt-20">
        <div className="eyebrow mb-3">Yaklaşım</div>
        <h2 className="max-w-2xl text-[28px] font-semibold leading-tight tracking-tight">Güven, gösterişten değil yöntemden gelir.</h2>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {PILLARS.map((p) => (
            <Card key={p.title} className="p-5">
              <p.icon className="size-5 text-gold" aria-hidden />
              <h3 className="mt-4 text-[14.5px] font-semibold">{p.title}</h3>
              <p className="mt-2 text-[13px] leading-relaxed text-muted">{p.body}</p>
            </Card>
          ))}
        </div>
      </section>

      {/* Üyelik */}
      <section className="mt-20">
        <div className="eyebrow mb-3">Üyelik</div>
        <h2 className="text-[28px] font-semibold tracking-tight">İhtiyacınız kadar derinlik</h2>
        <p className="mt-2 text-[13.5px] text-muted">Paket hakları ve güncel fiyatlar (fiyat yoksa satış kapalıdır) Paketler sayfasında.</p>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {PLANS.map((p) => (
            <Card key={p.name} className={p.highlight ? "border-gold/40 p-6" : "p-6"}>
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold tracking-[0.18em]">{p.name}</span>
                <span className="text-[12px] text-muted">{p.tag}</span>
              </div>
              <ul className="mt-5 space-y-2.5 text-[13px] text-text-2">
                {p.items.map((i) => (
                  <li key={i} className="flex gap-2"><BadgeCheck className="mt-0.5 size-4 shrink-0 text-gold" aria-hidden />{i}</li>
                ))}
              </ul>
              <div className="mt-6">
                {p.name === "FREE" ? (
                  <Link href="/kayit" className="inline-flex h-10 w-full items-center justify-center mi-btn-primary rounded-ctl bg-gold text-sm font-semibold text-accent-text hover:bg-gold-hover">Ücretsiz hesap aç</Link>
                ) : (
                  <Link href="/paketler" className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-ctl border border-line-strong text-[13px] font-medium text-text hover:bg-surface-2">Paketi incele</Link>
                )}
              </div>
            </Card>
          ))}
        </div>
      </section>

      {/* SSS */}
      <section className="mt-20 grid gap-8 lg:grid-cols-[1fr_1.6fr]">
        <div>
          <div className="eyebrow mb-3">SSS</div>
          <h2 className="text-[28px] font-semibold tracking-tight">Sık sorulan sorular</h2>
        </div>
        <div className="divide-y divide-line rounded-card border border-line bg-surface">
          {FAQ.map((f) => (
            <details key={f.q} className="group px-5 py-4">
              <summary className="cursor-pointer list-none text-[14px] font-medium text-text marker:hidden">
                <span className="flex items-center justify-between gap-4">
                  {f.q}
                  <span className="text-gold transition-transform group-open:rotate-45" aria-hidden>+</span>
                </span>
              </summary>
              <p className="mt-3 text-[13px] leading-relaxed text-muted">{f.a}</p>
            </details>
          ))}
        </div>
      </section>
    </div>
  );
}
