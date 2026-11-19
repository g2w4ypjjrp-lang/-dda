import type { Metadata, Viewport } from "next";
import { cookies } from "next/headers";
import type { ReactNode } from "react";

import "@fontsource-variable/inter";
import "@fontsource-variable/manrope";
import "@fontsource-variable/space-grotesk";
import "@fontsource-variable/ibm-plex-sans";
import "@fontsource-variable/dm-sans";
import "@fontsource-variable/fraunces";
import "@fontsource-variable/source-serif-4";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./globals.css";
import { DesignProvider } from "@/components/design";
import { DESIGN_COOKIE, FALLBACK_DESIGNS, allDesignsCss, designAttrs, resolveKey, type DesignPayload } from "@/lib/design";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: { default: "Match Intelligence AI", template: "%s · Match Intelligence AI" },
  description:
    "Gerçek futbol verisi, açıklanabilir yapay zekâ ve şeffaf olasılıklar. Tahminler kazanç garantisi değildir.",
  icons: { icon: "/icon.svg", apple: "/apple-touch-icon.png" },
  appleWebApp: { capable: true, title: "Match IQ", statusBarStyle: "black-translucent" },
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = { themeColor: "#f5f6fc", width: "device-width", initialScale: 1 };

/** Son başarılı yanıt: API bir an yavaş/kapalıysa tema geri dönmesin. */
let lastGood: DesignPayload | null = null;

/** Yayımlanmış tasarımlar (API). Ulaşılamazsa son başarılı yanıt, o da yoksa yerleşik Neon Light
 * kullanılır ve sunucu günlüğüne yazılır (sessizce başka temaya düşmesin). */
async function loadDesigns(): Promise<DesignPayload> {
  const api = process.env.MI_API_URL ?? process.env.MI_API_URL_BUILD ?? "http://127.0.0.1:8080";
  try {
    const res = await fetch(`${api}/v1/design`, {
      next: { revalidate: 30 },
      signal: AbortSignal.timeout(8000),
    });
    if (res.ok) {
      lastGood = (await res.json()) as DesignPayload;
      return lastGood;
    }
    console.error(`tasarımlar alınamadı: ${api}/v1/design → ${res.status}`);
  } catch (e) {
    console.error(`tasarımlar alınamadı (API: ${api})`, e instanceof Error ? e.message : e);
  }
  return lastGood ?? FALLBACK_DESIGNS;
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const [payload, jar] = await Promise.all([loadDesigns(), cookies()]);
  const key = resolveKey(payload, jar.get(DESIGN_COOKIE)?.value);
  const config = payload?.designs[key]?.config ?? null;
  return (
    <html lang="tr" {...designAttrs(key, config)} suppressHydrationWarning>
      <head>
        {/* Değerler sunucuda ve burada şemayla doğrulanmıştır (yalnızca renk/sayı/izinli seçenek). */}
        <style id="mi-designs" dangerouslySetInnerHTML={{ __html: allDesignsCss(payload) }} />
      </head>
      <body>
        <Providers>
          <DesignProvider payload={payload} initialKey={key}>{children}</DesignProvider>
        </Providers>
      </body>
    </html>
  );
}
