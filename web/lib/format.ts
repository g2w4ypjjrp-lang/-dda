// Biçimlendirme: tüm zamanlar Türkiye saatiyle gösterilir (API UTC döner).
const TZ = "Europe/Istanbul";

export const fmtTime = (iso: string) =>
  new Intl.DateTimeFormat("tr-TR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" }).format(new Date(iso));

export const fmtDate = (iso: string) =>
  new Intl.DateTimeFormat("tr-TR", { timeZone: TZ, day: "numeric", month: "long", weekday: "long" }).format(
    new Date(iso),
  );

export const fmtDateTime = (iso: string) =>
  new Intl.DateTimeFormat("tr-TR", {
    timeZone: TZ, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  }).format(new Date(iso));

export function trToday(offsetDays = 0): string {
  const now = new Date(Date.now() + offsetDays * 86400000);
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" })
    .format(now);
  return parts; // YYYY-MM-DD
}

export function shiftDay(day: string, delta: number): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}

export const dayLabel = (day: string) =>
  new Intl.DateTimeFormat("tr-TR", { timeZone: "UTC", weekday: "short", day: "numeric", month: "short" }).format(
    new Date(`${day}T12:00:00Z`),
  );

export const pct = (p: number | null | undefined, digits = 0) =>
  p === null || p === undefined || Number.isNaN(p) ? "—" : `%${(p * 100).toFixed(digits)}`;

export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s} sn önce`;
  if (s < 3600) return `${Math.round(s / 60)} dk önce`;
  if (s < 86400) return `${Math.round(s / 3600)} sa önce`;
  return `${Math.round(s / 86400)} gün önce`;
}

export const num = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? "—" : v.toFixed(digits);

/** Sanal birim (SB) — gerçek para değildir. API kuruş hassasiyetinde (minor) döner. */
export const sb = (minor: number | null | undefined) =>
  minor === null || minor === undefined
    ? "—"
    : `${(minor / 100).toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} SB`;

/** Para tutarı (kuruş → "199,00 ₺"). Yalnızca gerçek fiyat/sipariş kayıtları için. */
export const money = (minor: number | null | undefined, currency = "TRY") =>
  minor === null || minor === undefined
    ? "—"
    : (minor / 100).toLocaleString("tr-TR", { style: "currency", currency, minimumFractionDigits: 2 });

export const ORDER_STATUS: Record<string, string> = {
  pending: "Ödeme bekleniyor",
  paid: "Ödendi",
  failed: "Başarısız",
  refunded: "İade edildi",
  review: "İncelemede",
};

export const SUB_SOURCE: Record<string, string> = { payment: "Ödeme", license: "Lisans", admin: "Yönetici" };
export const SUB_STATUS: Record<string, string> = { active: "Etkin", canceled: "İptal (dönem sonuna kadar)", refunded: "İade", revoked: "Sonlandırıldı" };

/** "17 Aralık 2026" — dönem bitişi gibi yıl içeren tarihler için. */
export const fmtDay = (iso: string) =>
  new Intl.DateTimeFormat("tr-TR", { timeZone: TZ, day: "numeric", month: "long", year: "numeric" }).format(new Date(iso));
