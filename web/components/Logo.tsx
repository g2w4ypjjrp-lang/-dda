// Match Intelligence AI marka işareti: yuvarlatılmış kare içinde yükselen olasılık eğrisi ve
// eğrinin zirvesinde top/düğüm. Tek renk (currentColor) + şampanya vurgu; favicon'da da kullanılır.
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

export function Logo({ compact = false }: { compact?: boolean }) {
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
