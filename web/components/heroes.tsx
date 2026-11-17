"use client";

// On tasarımın ana sayfa açılış kompozisyonları. Hepsi aynı gerçek veriyi (bugünün maçları,
// yayımlanmış tahminler, sonuçlanmış tahminlerden ölçülen performans) farklı bir bilgi
// mimarisiyle sunar. Veri yoksa bunu açıkça söyler; örnek/uydurma değer göstermez.

import Link from "next/link";
import { ArrowRight, BadgeCheck, Database, Layers, Sigma } from "lucide-react";
import type { ReactNode } from "react";

import { ago, fmtDate, fmtTime, num, pct } from "@/lib/format";
import type { Fixture, FixtureList, Performance, Prediction } from "@/lib/types";
import { useLayout } from "./design";
import { SignatureMark } from "./Logo";
import { LiveCount, MatchTable } from "./match";
import { Badge, Card, ProbBar, Skeleton, Stat, TeamCrest, cx } from "./ui";

export interface HeroData {
  day: string;
  list?: FixtureList;
  items: Fixture[];
  preds: Prediction[];
  published: Prediction[];
  perf?: Performance;
  loading: boolean;
}

const maxP = (p: Prediction) => Math.max(...Object.values(p.probabilities!["1x2"]));

function featured(d: HeroData): { p: Prediction; f: Fixture } | null {
  const ranked = [...d.published].sort((a, b) => maxP(b) - maxP(a));
  for (const p of ranked) {
    const f = d.items.find((x) => x.id === p.fixture_id);
    if (f) return { p, f };
  }
  return null;
}

function favourite(p: Prediction, f: Fixture): string {
  const x = p.probabilities!["1x2"];
  if (x.home >= x.draw && x.home >= x.away) return `${f.home.name} kazanır`;
  if (x.away >= x.draw) return `${f.away.name} kazanır`;
  return "Beraberlik";
}

function Cta({ className }: { className?: string }) {
  return (
    <div className={cx("flex flex-wrap gap-3", className)}>
      <Link href="/maclar" className="mi-btn-primary inline-flex h-11 items-center gap-2 rounded-ctl bg-gold px-5 text-sm font-semibold text-accent-text hover:bg-gold-hover">
        Maç Merkezi <ArrowRight className="size-4" aria-hidden />
      </Link>
      <Link href="/performans" className="inline-flex h-11 items-center gap-2 rounded-ctl border border-line-strong bg-surface-2 px-5 text-sm font-medium text-text hover:bg-surface-3">
        Model nasıl ölçülüyor?
      </Link>
    </div>
  );
}

function NoAnalysis({ children }: { children?: ReactNode }) {
  return (
    <p className="text-[13px] leading-relaxed text-muted">
      {children ?? "Bugün yayımlanmış AI analizi yok. Model yalnızca yeterli veri ve test edilmiş güvenilirlik olduğunda tahmin yayımlar."}
    </p>
  );
}

function perfLine(perf?: Performance) {
  return perf?.data_status === "ok"
    ? `${perf.settled_published} sonuçlanmış tahmin · log loss ${num(perf.log_loss, 3)} (tekdüze ${num(perf.uniform_log_loss, 3)})`
    : "Henüz sonuçlanmış tahmin yok; performans rakamı gösterilmiyor.";
}

/* 01 — Signature Black: katmanlı başlık + günün özeti kartı */
function SignatureHero({ d }: { d: HeroData }) {
  return (
    <section className="grid items-center gap-10 pb-14 pt-12 lg:grid-cols-[1.15fr_1fr] lg:pt-20">
      <div className="rise">
        <div className="eyebrow mb-5 flex items-center gap-2"><span className="h-px w-8 bg-gold" aria-hidden /> Sports Intelligence Platform</div>
        <h1 className="text-[40px] font-semibold leading-[1.05] tracking-[-0.025em] text-text sm:text-[56px]">
          Futbolu <span className="text-gold">olasılıklarla</span><br /> okuyun.
        </h1>
        <p className="mt-6 max-w-xl text-[15.5px] leading-relaxed text-text-2">
          Gerçek maç verisi, kronolojik olarak test edilmiş modeller ve belirsizliği saklamayan analizler. Her olasılığın yanında ne kadar güvenilir olduğunu da görürsünüz.
        </p>
        <Cta className="mt-8" />
      </div>
      <Card className="rise overflow-hidden">
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <div className="flex items-center gap-2 text-[13px] font-medium text-text"><span className="size-1.5 rounded-full bg-teal" aria-hidden /> Bugün · {fmtDate(`${d.day}T12:00:00Z`)}</div>
          <LiveCount items={d.items} />
        </div>
        <div className="grid grid-cols-3 gap-4 px-5 py-5">
          {d.loading ? [0, 1, 2].map((i) => <Skeleton key={i} className="h-14" />) : (
            <>
              <Stat label="Maç" value={d.items.length} />
              <Stat label="AI analizi" value={d.published.length} hint={d.preds.length - d.published.length ? `${d.preds.length - d.published.length} çekimser` : undefined} />
              <Stat label="Biten" value={d.items.filter((f) => f.status === "finished").length} />
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
          Veri kaynağı: {d.list?.provider_label ?? "—"} · Son eşitleme: {ago(d.list?.last_successful_sync_at)}
        </div>
      </Card>
    </section>
  );
}

/* 02 — Swiss Intelligence: tipografik ifade + numaralı dizin */
function SwissHero({ d }: { d: HeroData }) {
  const rows = [
    ["01", "Bugünkü maç", d.loading ? "…" : String(d.items.length)],
    ["02", "Yayımlanan analiz", d.loading ? "…" : String(d.published.length)],
    ["03", "Çekimser kalınan", d.loading ? "…" : String(d.preds.length - d.published.length)],
    ["04", "Ölçülen log loss", d.perf?.data_status === "ok" ? num(d.perf.log_loss, 3) : "Veri yok"],
  ];
  return (
    <section className="grid gap-12 border-b border-line pb-14 pt-14 lg:grid-cols-[1.3fr_1fr]">
      <div>
        <div className="mb-8 flex items-center gap-3 text-[12px] font-medium uppercase tracking-[0.2em] text-muted"><span className="size-3 bg-gold" aria-hidden />Match Intelligence</div>
        <h1 className="text-[44px] leading-[1.02] sm:text-[72px]">Olasılık.<br />Güvenilirlik.<br /><span className="text-muted">Belirsizlik.</span></h1>
        <p className="mt-8 max-w-lg text-[15px] leading-relaxed text-text-2">Üçünü ayrı ölçer, ayrı gösteririz. Yetersiz veride tahmin vermeyiz ve nedenini yazarız.</p>
        <Cta className="mt-8" />
      </div>
      <div className="self-end">
        <div className="mb-3 text-[12px] text-muted">{fmtDate(`${d.day}T12:00:00Z`)}</div>
        <table className="w-full text-[14px]">
          <tbody className="divide-y divide-line border-y border-line-strong">
            {rows.map(([n, label, v]) => (
              <tr key={n}><td className="num w-12 py-3 text-muted">{n}</td><td className="py-3">{label}</td><td className="num py-3 text-right text-[20px] font-semibold">{v}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/* 03 — Quantum Terminal: başlık yok; panolar */
function TerminalHero({ d }: { d: HeroData }) {
  const byFixture = new Map(d.preds.map((p) => [p.fixture_id, p]));
  return (
    <section className="grid gap-3 pb-6 pt-4 xl:grid-cols-[2fr_1fr]">
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-line px-4 py-2 font-mono text-[11px] uppercase tracking-wider text-muted">
          <span>Günün tahtası · 1X2 model olasılıkları</span><span>{d.items.length} maç</span>
        </div>
        {d.loading ? <Skeleton className="m-4 h-40" /> : d.items.length ? <MatchTable fixtures={d.items.slice(0, 12)} byFixture={byFixture} /> : <p className="p-4 text-[12.5px] text-muted">Bugün maç verisi yok.</p>}
      </Card>
      <div className="grid gap-3">
        <Card className="p-4">
          <div className="mb-3 font-mono text-[11px] uppercase tracking-wider text-muted">Model</div>
          {d.perf?.data_status === "ok" ? (
            <div className="num grid grid-cols-2 gap-3 font-mono text-[13px]">
              <div><div className="text-[10.5px] text-muted">N</div>{d.perf.settled_published}</div>
              <div><div className="text-[10.5px] text-muted">BRIER</div>{num(d.perf.brier, 3)}</div>
              <div><div className="text-[10.5px] text-muted">LOGLOSS</div>{num(d.perf.log_loss, 3)}</div>
              <div><div className="text-[10.5px] text-muted">İSABET</div>{pct(d.perf.accuracy)}</div>
            </div>
          ) : <p className="font-mono text-[12px] text-muted">VERİ YOK — sonuçlanmış tahmin bekleniyor.</p>}
        </Card>
        <Card className="p-4">
          <div className="mb-3 font-mono text-[11px] uppercase tracking-wider text-muted">Sistem</div>
          <dl className="num grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 font-mono text-[12px]">
            <dt className="text-muted">KAYNAK</dt><dd>{d.list?.provider_label ?? "—"}</dd>
            <dt className="text-muted">EŞİTLEME</dt><dd>{ago(d.list?.last_successful_sync_at)}</dd>
            <dt className="text-muted">YAYIN</dt><dd>{d.published.length} / {d.preds.length}</dd>
          </dl>
        </Card>
      </div>
    </section>
  );
}

/* 04 — Editorial Sports: günün maçı kapağı + manşet listesi */
function EditorialHero({ d }: { d: HeroData }) {
  const top = featured(d);
  const others = d.published.filter((p) => p !== top?.p).slice(0, 4);
  return (
    <section className="grid gap-10 border-b border-line pb-12 pt-10 lg:grid-cols-[1.6fr_1fr]">
      <article>
        <div className="mb-4 text-[12px] font-semibold uppercase tracking-[0.24em] text-gold">Günün maçı</div>
        {top ? (
          <>
            <h1 className="text-[40px] leading-[1.04] sm:text-[64px]">{top.f.home.name} <span className="text-muted">–</span> {top.f.away.name}</h1>
            <p className="mt-5 max-w-2xl text-[17px] leading-relaxed text-text-2">
              {top.f.competition.name} · {fmtTime(top.f.kickoff_at)}. Modelin en olası gördüğü sonuç: <strong className="text-text">{favourite(top.p, top.f)}</strong> ({pct(maxP(top.p))}). Model güvenilirliği {top.p.reliability.label.toLowerCase()}.
            </p>
            <div className="mt-6 max-w-2xl"><ProbBar p={top.p.probabilities!["1x2"]} /></div>
            <Link href={`/maclar/${top.f.id}`} className="mt-6 inline-flex items-center gap-2 text-[14px] font-semibold text-gold hover:underline">Analizin tamamı <ArrowRight className="size-4" aria-hidden /></Link>
          </>
        ) : (
          <>
            <h1 className="text-[40px] leading-[1.04] sm:text-[60px]">Futbolu olasılıklarla okuyun.</h1>
            <div className="mt-5 max-w-xl"><NoAnalysis /></div>
          </>
        )}
      </article>
      <aside>
        <div className="mb-3 border-b-2 border-text pb-2 text-[12px] font-semibold uppercase tracking-[0.2em]">Öne çıkanlar</div>
        {others.length === 0 ? <NoAnalysis>Bugün başka yayımlanmış analiz yok.</NoAnalysis> : (
          <ol className="divide-y divide-line">
            {others.map((p, i) => {
              const f = d.items.find((x) => x.id === p.fixture_id);
              return (
                <li key={p.id} className="flex gap-4 py-4">
                  <span className="num font-heading text-[28px] leading-none text-muted">{i + 1}</span>
                  <Link href={`/maclar/${p.fixture_id}`} className="group">
                    <h3 className="text-[17px] font-semibold leading-snug group-hover:text-gold">{f ? `${f.home.name} – ${f.away.name}` : `Maç #${p.fixture_id}`}</h3>
                    <p className="mt-1 text-[12.5px] text-muted">{f ? favourite(p, f) : ""} · {pct(maxP(p))}</p>
                  </Link>
                </li>
              );
            })}
          </ol>
        )}
      </aside>
    </section>
  );
}

/* 05 — AI Atelier: olasılık dağılımı ve belirsizlik merkezde */
function AtelierHero({ d }: { d: HeroData }) {
  const top = featured(d);
  const x = top?.p.probabilities!["1x2"];
  const iv = top?.p.uncertainty.interval_1x2;
  const bars = x ? ([["1", x.home, iv?.home, "bg-home"], ["X", x.draw, iv?.draw, "bg-draw"], ["2", x.away, iv?.away, "bg-away"]] as const) : [];
  return (
    <section className="grid items-center gap-10 pb-12 pt-10 lg:grid-cols-[1fr_1.1fr]">
      <div>
        <div className="eyebrow mb-4">AI Atelier</div>
        <h1 className="text-[38px] leading-[1.08] sm:text-[52px]">Bir tahmin tek sayı değildir; <span className="text-gold">bir dağılımdır.</span></h1>
        <p className="mt-5 max-w-lg text-[15px] leading-relaxed text-text-2">Olasılık, parametre belirsizliği ve modeller arası uyum birlikte gösterilir. Model yanıldığında nedeni ölçülebilir.</p>
        <Cta className="mt-7" />
      </div>
      <Card className="p-6">
        {top && x ? (
          <>
            <div className="mb-1 text-[12px] text-muted">{top.f.competition.name} · {fmtTime(top.f.kickoff_at)}</div>
            <div className="mb-6 text-[17px] font-semibold">{top.f.home.name} – {top.f.away.name}</div>
            <div className="flex h-52 items-end justify-around gap-6 border-b border-line">
              {bars.map(([label, v, range, cls]) => (
                <div key={label} className="relative flex h-full w-16 flex-col items-center justify-end">
                  {range && <div className="absolute w-px bg-text-2" style={{ bottom: `${range[0] * 100}%`, height: `${(range[1] - range[0]) * 100}%` }} aria-hidden />}
                  <div className={cx("w-full rounded-t-ctl opacity-85", cls)} style={{ height: `${v * 100}%` }} />
                  <div className="num absolute -top-1 text-[13px] font-semibold" style={{ bottom: `calc(${v * 100}% + 6px)`, top: "auto" }}>{pct(v)}</div>
                </div>
              ))}
            </div>
            <div className="mt-2 flex justify-around text-[12px] text-muted">{bars.map(([l]) => <span key={l} className="w-16 text-center">{l}</span>)}</div>
            <p className="mt-4 text-[11.5px] text-muted">
              {iv ? "Dikey çizgiler %10–%90 parametre belirsizliği (bootstrap)." : "Bu tahmin için belirsizlik aralığı yok veya paketinizde kilitli."}
              {top.p.model_agreement !== null && ` Modeller arası en büyük fark ${pct(top.p.model_agreement)}.`}
            </p>
          </>
        ) : <NoAnalysis />}
      </Card>
    </section>
  );
}

/* 06 — Architectural Luxury: asimetrik blok kompozisyonu */
function ArchitecturalHero({ d }: { d: HeroData }) {
  const top = featured(d);
  return (
    <section className="mi-grid grid gap-(--mi-gap) pb-12 pt-10">
      <div className="mi-span-main">
        <div className="eyebrow mb-6">Match Intelligence · Mimari</div>
        <h1 className="text-[44px] leading-[1.02] sm:text-[76px]">Ölçülmüş<br />olasılık.</h1>
        <p className="mt-6 max-w-md text-[15px] leading-relaxed text-text-2">Her rakamın yanında kaynağı, güncelliği ve ne kadar güvenilir olduğu yazar.</p>
        <Cta className="mt-8" />
      </div>
      <Card className="mi-span-side p-6">
        <div className="eyebrow mb-3">Bugün</div>
        <div className="grid grid-cols-3 gap-4">
          <Stat label="Maç" value={d.loading ? "…" : d.items.length} />
          <Stat label="Analiz" value={d.loading ? "…" : d.published.length} />
          <Stat label="Çekimser" value={d.loading ? "…" : d.preds.length - d.published.length} />
        </div>
      </Card>
      <Card className="mi-span-offset p-6">
        {top ? (
          <Link href={`/maclar/${top.f.id}`} className="block">
            <div className="eyebrow mb-3">En belirgin analiz</div>
            <div className="text-[15px] font-semibold">{top.f.home.name} – {top.f.away.name}</div>
            <div className="mt-4"><ProbBar p={top.p.probabilities!["1x2"]} size="sm" /></div>
          </Link>
        ) : <NoAnalysis />}
      </Card>
      <p className="mi-span-offset text-[12px] text-muted">{perfLine(d.perf)}</p>
    </section>
  );
}

/* 07 — Institutional Blue: günlük rapor başlığı + KPI + özet tablo */
function InstitutionalHero({ d }: { d: HeroData }) {
  const rows = [...d.published].sort((a, b) => maxP(b) - maxP(a)).slice(0, 6);
  return (
    <section className="pb-8 pt-8">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b-2 border-gold pb-4">
        <div>
          <div className="text-[12px] font-semibold uppercase tracking-[0.14em] text-muted">Günlük analiz raporu</div>
          <h1 className="mt-1 text-[30px] sm:text-[36px]">{fmtDate(`${d.day}T12:00:00Z`)}</h1>
        </div>
        <Cta />
      </div>
      <div className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-card border border-line bg-line md:grid-cols-4">
        {[
          ["Maç", d.loading ? "…" : d.items.length],
          ["Yayımlanan analiz", d.loading ? "…" : d.published.length],
          ["Çekimser", d.loading ? "…" : d.preds.length - d.published.length],
          ["Log loss (ölçülen)", d.perf?.data_status === "ok" ? num(d.perf.log_loss, 3) : "Veri yok"],
        ].map(([l, v]) => <div key={String(l)} className="bg-surface p-5"><Stat label={String(l)} value={v} /></div>)}
      </div>
      <Card className="mt-5 overflow-hidden">
        {rows.length === 0 ? <div className="p-5"><NoAnalysis /></div> : (
          <table className="mi-table num w-full text-[13px]">
            <thead><tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-muted"><th className="px-5 py-2.5 font-medium">Maç</th><th className="px-3 py-2.5 font-medium">Olası sonuç</th><th className="px-3 py-2.5 text-right font-medium">Olasılık</th><th className="px-5 py-2.5 text-right font-medium">Güvenilirlik</th></tr></thead>
            <tbody className="divide-y divide-line">
              {rows.map((p) => {
                const f = d.items.find((x) => x.id === p.fixture_id);
                return (
                  <tr key={p.id}>
                    <td className="px-5 py-2.5"><Link href={`/maclar/${p.fixture_id}`} className="hover:text-gold">{f ? `${f.home.name} – ${f.away.name}` : `#${p.fixture_id}`}</Link></td>
                    <td className="px-3 py-2.5 text-text-2">{f ? favourite(p, f) : "—"}</td>
                    <td className="px-3 py-2.5 text-right font-semibold">{pct(maxP(p))}</td>
                    <td className="px-5 py-2.5 text-right">{p.reliability.label}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
    </section>
  );
}

/* 08 — Obsidian Glass: üst üste binen cam paneller */
function ObsidianHero({ d }: { d: HeroData }) {
  const top = featured(d);
  return (
    <section className="relative grid items-center gap-10 pb-16 pt-14 lg:grid-cols-[1fr_1.1fr]">
      <div>
        <div className="eyebrow mb-5">Obsidian</div>
        <h1 className="text-[42px] leading-[1.05] sm:text-[58px]">Karanlıkta bile <span className="text-gold">net</span> olasılık.</h1>
        <p className="mt-5 max-w-md text-[15px] leading-relaxed text-text-2">Katman katman: olasılık, güvenilirlik, veri kalitesi.</p>
        <Cta className="mt-7" />
      </div>
      <div className="relative min-h-[300px]">
        <Card className="relative z-10 p-6 lg:mr-16">
          {top ? (
            <>
              <div className="mb-4 flex items-center gap-3">
                <TeamCrest name={top.f.home.name} logo={top.f.home.logo_url} size={34} />
                <span className="text-[16px] font-semibold">{top.f.home.name} – {top.f.away.name}</span>
              </div>
              <ProbBar p={top.p.probabilities!["1x2"]} />
              <div className="mt-4 text-[12px] text-muted">{top.f.competition.name} · {fmtTime(top.f.kickoff_at)} · güvenilirlik {top.p.reliability.label.toLowerCase()}</div>
            </>
          ) : <NoAnalysis />}
        </Card>
        <Card className="absolute -bottom-6 right-0 z-20 hidden w-60 p-5 lg:block">
          <Stat label="Bugün yayımlanan" value={d.published.length} hint={`${d.items.length} maç içinde`} />
        </Card>
      </div>
    </section>
  );
}

/* 09 — Future Sports Lab: takım karşılaştırması */
function LabHero({ d }: { d: HeroData }) {
  const top = featured(d);
  const x = top?.p.probabilities?.["1x2"];
  const xg = top?.p.probabilities?.expected_goals;
  const side = (i: 0 | 1) => {
    if (!top || !x) return null;
    const t = i === 0 ? top.f.home : top.f.away;
    return (
      <div className={cx("flex flex-col gap-3", i === 1 && "items-end text-right")}>
        <TeamCrest name={t.name} logo={t.logo_url} size={56} />
        <div className="text-[20px] font-semibold">{t.name}</div>
        <div className="num font-heading text-[48px] font-bold leading-none text-gold">{pct(i === 0 ? x.home : x.away)}</div>
        <div className="text-[12px] text-muted">kazanma olasılığı</div>
        <div className="num text-[13px] text-text-2">{xg ? `Beklenen gol ${num(i === 0 ? xg.home : xg.away, 2)}` : "Beklenen gol: PRO"}</div>
      </div>
    );
  };
  return (
    <section className="pb-12 pt-10">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow mb-2">Sports Lab · Karşılaştırma</div>
          <h1 className="text-[36px] leading-tight sm:text-[48px]">Günün en net eşleşmesi</h1>
        </div>
        <Cta />
      </div>
      <Card className="p-6 sm:p-8">
        {top && x ? (
          <>
            <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-6">
              {side(0)}
              <div className="text-center"><div className="num font-heading text-[28px] font-bold">{pct(x.draw)}</div><div className="text-[12px] text-muted">beraberlik</div></div>
              {side(1)}
            </div>
            <div className="mt-8"><ProbBar p={x} labels={false} /></div>
            <div className="mt-3 text-[12px] text-muted">{top.f.competition.name} · {fmtTime(top.f.kickoff_at)} · model güvenilirliği {top.p.reliability.label.toLowerCase()}</div>
          </>
        ) : <NoAnalysis />}
      </Card>
    </section>
  );
}

/* 10 — Match Intelligence Signature: marka işareti + günün olasılık şeritleri */
function BrandHero({ d }: { d: HeroData }) {
  const strips = d.published.slice(0, 8);
  return (
    <section className="pb-14 pt-14 text-center">
      <div className="mx-auto mb-6 flex justify-center text-text"><SignatureMark size={64} /></div>
      <h1 className="mx-auto max-w-3xl text-[44px] leading-[1.02] sm:text-[72px]">Olasılığın dili.</h1>
      <p className="mx-auto mt-5 max-w-xl text-[15.5px] leading-relaxed text-text-2">Her maç bir şerit: ev sahibi, beraberlik, deplasman. Genişlik olasılık; yanında güvenilirlik.</p>
      <Cta className="mt-7 justify-center" />
      <div className="mx-auto mt-12 max-w-3xl space-y-2.5 text-left">
        {strips.length === 0 ? <div className="text-center"><NoAnalysis /></div> : strips.map((p) => {
          const f = d.items.find((x) => x.id === p.fixture_id);
          return (
            <Link key={p.id} href={`/maclar/${p.fixture_id}`} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)_auto] items-center gap-4 rounded-ctl px-3 py-2 hover:bg-surface-2">
              <span className="truncate text-[13px] font-medium">{f ? `${f.home.name} – ${f.away.name}` : `#${p.fixture_id}`}</span>
              <ProbBar p={p.probabilities!["1x2"]} size="sm" labels={false} />
              <Badge tone={p.reliability.level === "high" ? "teal" : p.reliability.level === "medium" ? "gold" : "neutral"}>{p.reliability.label}</Badge>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

export function HomeHero({ d }: { d: HeroData }) {
  const { hero } = useLayout();
  switch (hero) {
    case "swiss": return <SwissHero d={d} />;
    case "terminal": return <TerminalHero d={d} />;
    case "editorial": return <EditorialHero d={d} />;
    case "atelier": return <AtelierHero d={d} />;
    case "architectural": return <ArchitecturalHero d={d} />;
    case "institutional": return <InstitutionalHero d={d} />;
    case "obsidian": return <ObsidianHero d={d} />;
    case "lab": return <LabHero d={d} />;
    case "brand": return <BrandHero d={d} />;
    default: return <SignatureHero d={d} />;
  }
}
