"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight, BadgeCheck, Brain, Database, Gauge, History, Layers, Lock, ShieldCheck, Sigma,
} from "lucide-react";

import { DataStatusBanner, LiveCount, MatchRow } from "@/components/match";
import { Badge, Card, CardHeader, Empty, ErrorState, ProbBar, Skeleton, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, fmtDate, num, pct, trToday } from "@/lib/format";
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
      {/* Hero */}
      <section className="grid items-center gap-10 pb-14 pt-12 lg:grid-cols-[1.15fr_1fr] lg:pt-20">
        <div className="rise">
          <div className="eyebrow mb-5 flex items-center gap-2">
            <span className="h-px w-8 bg-gold" aria-hidden /> Sports Intelligence Platform
          </div>
          <h1 className="text-[40px] font-semibold leading-[1.05] tracking-[-0.025em] text-text sm:text-[56px]">
            Futbolu <span className="text-gold">olasılıklarla</span>
            <br /> okuyun.
          </h1>
          <p className="mt-6 max-w-xl text-[15.5px] leading-relaxed text-text-2">
            Gerçek maç verisi, kronolojik olarak test edilmiş modeller ve belirsizliği saklamayan analizler.
            Her olasılığın yanında ne kadar güvenilir olduğunu da görürsünüz.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/maclar" className="inline-flex h-11 items-center gap-2 rounded-ctl bg-gold px-5 text-sm font-semibold text-[#14110a] hover:bg-[#d6b97d]">
              Maç Merkezi <ArrowRight className="size-4" aria-hidden />
            </Link>
            <Link href="/performans" className="inline-flex h-11 items-center gap-2 rounded-ctl border border-line-strong bg-surface-2 px-5 text-sm font-medium text-text hover:bg-surface-3">
              Model nasıl ölçülüyor?
            </Link>
          </div>
        </div>

        <Card className="rise overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
            <div className="flex items-center gap-2 text-[13px] font-medium text-text">
              <span className="size-1.5 rounded-full bg-teal" aria-hidden /> Bugün · {fmtDate(`${day}T12:00:00Z`)}
            </div>
            <LiveCount items={items} />
          </div>
          <div className="grid grid-cols-3 gap-4 px-5 py-5">
            {fixtures.isLoading ? (
              [0, 1, 2].map((i) => <Skeleton key={i} className="h-14" />)
            ) : (
              <>
                <Stat label="Maç" value={items.length} />
                <Stat label="AI analizi" value={published.length} hint={preds.length - published.length ? `${preds.length - published.length} çekimser` : undefined} />
                <Stat label="Biten" value={items.filter((f) => f.status === "finished").length} />
              </>
            )}
          </div>
          <div className="border-t border-line px-5 py-4">
            <div className="eyebrow mb-3">Bir analiz nasıl okunur</div>
            <ul className="grid grid-cols-2 gap-3 text-[12.5px] text-text-2">
              <li className="flex items-start gap-2"><Sigma className="mt-0.5 size-4 text-cobalt" aria-hidden />Olay olasılığı</li>
              <li className="flex items-start gap-2"><BadgeCheck className="mt-0.5 size-4 text-gold" aria-hidden />Model güvenilirliği</li>
              <li className="flex items-start gap-2"><Database className="mt-0.5 size-4 text-teal" aria-hidden />Veri kalitesi</li>
              <li className="flex items-start gap-2"><Layers className="mt-0.5 size-4 text-text-2" aria-hidden />Modeller arası uyum</li>
            </ul>
          </div>
          <div className="border-t border-line bg-bg-elevated px-5 py-3 text-[11.5px] text-muted">
            Veri kaynağı: {fixtures.data?.provider_label ?? "—"} · Son eşitleme: {ago(fixtures.data?.last_successful_sync_at)}
          </div>
        </Card>
      </section>

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
              items.slice(0, 8).map((f) => <MatchRow key={f.id} fixture={f} prediction={byFixture.get(f.id)} />)
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
        <p className="mt-2 text-[13.5px] text-muted">Ücretli paketler ve fiyatlar ödeme altyapısı tamamlandığında açıklanacak.</p>
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
                  <Link href="/kayit" className="inline-flex h-10 w-full items-center justify-center rounded-ctl bg-gold text-sm font-semibold text-[#14110a] hover:bg-[#d6b97d]">Ücretsiz hesap aç</Link>
                ) : (
                  <span className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-ctl border border-line text-[13px] text-muted"><Lock className="size-3.5" aria-hidden />Yakında</span>
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
