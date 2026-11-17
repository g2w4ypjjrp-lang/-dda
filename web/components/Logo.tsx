"use client";

import { useLayout } from "./design";

// Match Intelligence AI marka işareti: yuvarlatılmış kare içinde yükselen olasılık eğrisi ve
// eğrinin zirvesinde top/düğüm. Tek renk (currentColor) + vurgu; favicon'da da kullanılır.
export function LogoMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden className={className}>
      <rect x="1.5" y="1.5" width="29" height="29" rx="8.5" stroke="currentColor" strokeOpacity="0.35" strokeWidth="1.5" />
      <path d="M7 22.5 L12.5 15.5 L17 19 L24 9.5" stroke="var(--mi-gold)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="24" cy="9.5" r="2.6" fill="var(--mi-gold)" />
      <path d="M7 25.5 H25" stroke="currentColor" strokeOpacity="0.28" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

/** DESIGN 10'a özel işaret: saha orta yuvarlağı ve içinden geçen üç parçalı olasılık şeridi (1·X·2). */
export function SignatureMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden>
      <circle cx="16" cy="16" r="13.5" stroke="currentColor" strokeOpacity="0.4" strokeWidth="1.4" />
      <path d="M16 2.5 V29.5" stroke="currentColor" strokeOpacity="0.22" strokeWidth="1.2" />
      <rect x="4" y="13.5" width="10" height="5" rx="2.5" fill="var(--mi-home)" />
      <rect x="14.6" y="13.5" width="5" height="5" rx="2.5" fill="var(--mi-draw)" />
      <rect x="20.2" y="13.5" width="7.8" height="5" rx="2.5" fill="var(--mi-gold)" />
    </svg>
  );
}

export function Logo({ compact = false }: { compact?: boolean }) {
  const { logo } = useLayout();
  if (logo === "wordmark") {
    return (
      <span className="inline-flex items-baseline gap-1.5 text-text" aria-label="Match Intelligence AI">
        <span className="font-heading text-[15px] font-semibold tracking-[-0.01em]">Match Intelligence</span>
        <span className="size-1.5 translate-y-[-2px] rounded-full bg-gold" aria-hidden />
        {!compact && <span className="hidden text-[11px] font-medium tracking-[0.18em] text-muted sm:inline">AI</span>}
      </span>
    );
  }
  if (logo === "terminal") {
    return (
      <span className="inline-flex items-center gap-2 font-mono text-[13px] text-text" aria-label="Match Intelligence AI">
        <span className="rounded-[3px] bg-gold px-1.5 py-0.5 text-[11px] font-semibold text-accent-text">MI</span>
        <span className="tracking-[0.08em]">MATCH<span className="text-gold">/</span>INTEL</span>
        {!compact && <span className="hidden text-muted sm:inline">v.ai</span>}
      </span>
    );
  }
  if (logo === "serif") {
    return (
      <span className="inline-flex flex-col leading-none text-text" aria-label="Match Intelligence AI">
        <span className="font-heading text-[22px] font-bold italic tracking-[-0.02em]">Match Intelligence</span>
        {!compact && <span className="mt-1 text-[9.5px] font-semibold uppercase tracking-[0.34em] text-gold">Futbol · Analiz · AI</span>}
      </span>
    );
  }
  if (logo === "signature") {
    return (
      <span className="inline-flex items-center gap-2.5 text-text" aria-label="Match Intelligence AI">
        <SignatureMark />
        {!compact && (
          <span className="leading-none">
            <span className="font-heading block text-[16px] font-semibold tracking-[-0.03em]">match<span className="text-gold">·</span>intelligence</span>
            <span className="mt-1 block text-[10px] font-medium tracking-[0.2em] text-muted">OLASILIĞIN DİLİ</span>
          </span>
        )}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-2.5 text-text">
      <LogoMark />
      {!compact && (
        <span className="leading-none">
          <span className="block text-[11.5px] font-semibold tracking-[0.12em] sm:text-[13px] sm:tracking-[0.14em]">MATCH INTELLIGENCE</span>
          <span className="mt-1 hidden text-[9.5px] font-medium tracking-[0.32em] text-gold sm:block">AI · SPORTS ANALYTICS</span>
          <span className="mt-1 block text-[9px] font-medium tracking-[0.3em] text-gold sm:hidden">AI</span>
        </span>
      )}
    </span>
  );
}
