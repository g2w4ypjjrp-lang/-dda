"use client";

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import { forwardRef } from "react";
import { AlertTriangle, Inbox, Loader2 } from "lucide-react";

import { ApiError } from "@/lib/api";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

export function Card({ children, className, as: Tag = "section" }: { children: ReactNode; className?: string; as?: "section" | "div" | "article" }) {
  return (
    <Tag className={cx("rounded-card border border-line bg-surface shadow-card", className)}>{children}</Tag>
  );
}

export function CardHeader({ eyebrow, title, action, className }: { eyebrow?: string; title: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cx("flex items-start justify-between gap-4 px-5 pt-5", className)}>
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-1.5">{eyebrow}</div>}
        <h2 className="text-[15px] font-semibold tracking-tight text-text">{title}</h2>
      </div>
      {action}
    </div>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading, disabled, className, children, ...rest },
  ref,
) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-ctl font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
  const sizes = { sm: "h-8 px-3 text-[13px]", md: "h-10 px-4 text-sm" };
  const variants = {
    primary: "bg-gold text-[#14110a] hover:bg-[#d6b97d] active:bg-[#bb9d61]",
    secondary: "border border-line-strong bg-surface-2 text-text hover:bg-surface-3",
    ghost: "text-text-2 hover:bg-surface-2 hover:text-text",
    danger: "border border-red/40 bg-red-soft text-red hover:bg-red/20",
  };
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(base, sizes[size], variants[variant], className)}
      {...rest}
    >
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
});

export function Badge({ tone = "neutral", children, className }: { tone?: "neutral" | "gold" | "cobalt" | "teal" | "amber" | "red"; children: ReactNode; className?: string }) {
  const tones = {
    neutral: "bg-surface-3 text-text-2",
    gold: "bg-gold-soft text-gold",
    cobalt: "bg-cobalt-soft text-cobalt",
    teal: "bg-teal-soft text-teal",
    amber: "bg-amber-soft text-amber",
    red: "bg-red-soft text-red",
  };
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium", tones[tone], className)}>
      {children}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton", className)} aria-hidden />;
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div className="mb-1 grid size-11 place-items-center rounded-full border border-line bg-surface-2 text-muted">
        {icon ?? <Inbox className="size-5" aria-hidden />}
      </div>
      <p className="text-sm font-medium text-text">{title}</p>
      {children && <div className="max-w-md text-[13px] leading-relaxed text-muted">{children}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof ApiError ? error.message : "Beklenmeyen bir hata oluştu.";
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-6 py-10 text-center">
      <AlertTriangle className="size-5 text-red" aria-hidden />
      <p className="text-sm text-text-2">{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Tekrar dene
        </Button>
      )}
    </div>
  );
}

export function Notice({ tone = "neutral", children, title }: { tone?: "neutral" | "amber" | "red" | "teal"; children: ReactNode; title?: string }) {
  const tones = {
    neutral: "border-line bg-surface-2 text-text-2",
    amber: "border-amber/30 bg-amber-soft text-text-2",
    red: "border-red/30 bg-red-soft text-text-2",
    teal: "border-teal/30 bg-teal-soft text-text-2",
  };
  return (
    <div className={cx("rounded-ctl border px-4 py-3 text-[13px] leading-relaxed", tones[tone])}>
      {title && <div className="mb-0.5 font-semibold text-text">{title}</div>}
      {children}
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "gold" | "teal" | "red" }) {
  const colors = { gold: "text-gold", teal: "text-teal", red: "text-red" };
  return (
    <div className="min-w-0">
      <div className="eyebrow mb-1.5 truncate">{label}</div>
      <div className={cx("num text-2xl font-semibold tracking-tight", tone ? colors[tone] : "text-text")}>{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string; hint?: string }>(
  function Input({ label, error, hint, id, className, ...rest }, ref) {
    const inputId = id ?? rest.name;
    return (
      <label htmlFor={inputId} className="block">
        <span className="mb-1.5 block text-[13px] font-medium text-text-2">{label}</span>
        <input
          ref={ref}
          id={inputId}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${inputId}-error` : undefined}
          className={cx(
            "h-11 w-full rounded-ctl border bg-bg-elevated px-3.5 text-sm text-text placeholder:text-muted/70",
            "outline-none transition-colors focus:border-gold/60",
            error ? "border-red/60" : "border-line-strong",
            className,
          )}
          {...rest}
        />
        {error ? (
          <span id={`${inputId}-error`} className="mt-1.5 block text-xs text-red">{error}</span>
        ) : hint ? (
          <span className="mt-1.5 block text-xs text-muted">{hint}</span>
        ) : null}
      </label>
    );
  },
);

export function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof ApiError ? error.message : "Beklenmeyen bir hata oluştu.";
  const upgrade = error instanceof ApiError && ["plan_required", "plan_limit", "daily_limit"].includes(error.code);
  return (
    <div role="alert" className="rounded-ctl border border-red/30 bg-red-soft px-3.5 py-2.5 text-[13px] text-text">
      {message}
      {upgrade && <> <a href="/paketler" className="font-medium text-gold hover:underline">Paketleri incele →</a></>}
    </div>
  );
}

/** 1X2 olasılık çubuğu: üç parça, renkler token'lardan. */
export function ProbBar({ p, size = "md", labels = true }: { p: { home: number; draw: number; away: number }; size?: "sm" | "md"; labels?: boolean }) {
  const parts = [
    { key: "home", label: "1", v: p.home, cls: "bg-home" },
    { key: "draw", label: "X", v: p.draw, cls: "bg-draw" },
    { key: "away", label: "2", v: p.away, cls: "bg-away" },
  ];
  return (
    <div>
      <div
        className={cx("flex overflow-hidden rounded-full bg-surface-3", size === "sm" ? "h-1.5" : "h-2.5")}
        role="img"
        aria-label={`Ev sahibi %${Math.round(p.home * 100)}, beraberlik %${Math.round(p.draw * 100)}, deplasman %${Math.round(p.away * 100)}`}
      >
        {parts.map((x) => (
          <div key={x.key} className={cx(x.cls, "h-full transition-[width] duration-500")} style={{ width: `${x.v * 100}%` }} />
        ))}
      </div>
      {labels && (
        <div className="num mt-2 grid grid-cols-3 text-xs">
          {parts.map((x, i) => (
            <div key={x.key} className={cx(i === 1 && "text-center", i === 2 && "text-right")}>
              <span className="text-muted">{x.label} </span>
              <span className="font-semibold text-text">%{Math.round(x.v * 100)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function TeamCrest({ name, logo, size = 28 }: { name: string; logo?: string | null; size?: number }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toLocaleUpperCase("tr-TR");
  if (logo) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={logo} alt="" width={size} height={size} className="shrink-0 object-contain" loading="lazy" />;
  }
  return (
    <span
      aria-hidden
      className="grid shrink-0 place-items-center rounded-full border border-line-strong bg-surface-3 text-[10px] font-semibold text-text-2"
      style={{ width: size, height: size }}
    >
      {initials}
    </span>
  );
}
