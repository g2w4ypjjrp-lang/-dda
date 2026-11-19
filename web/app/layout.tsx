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
import { DESIGN_COOKIE, allDesignsCss, designAttrs, resolveKey, type DesignPayload } from "@/lib/design";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: { default: "Match Intelligence AI", template: "%s · Match Intelligence AI" },
  description:
    "Gerçek futbol verisi, açıklanabilir yapay zekâ ve şeffaf olasılıklar. Tahminler kazanç garantisi değildir.",
  icons: { icon: "/icon.svg", apple: "/apple-touch-icon.png" },
  appleWebApp: { capable: true, title: "Match IQ", statusBarStyle: "black-translucent" },
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = { themeColor: "#0a0b0d", width: "device-width", initialScale: 1 };

/** Yayımlanmış tasarımlar (API). Ulaşılamazsa yerleşik varsayılan (globals.css) ile devam edilir ve
 * sunucu günlüğüne yazılır (sessizce eski temaya düşmesin). */
async function loadDesigns(): Promise<DesignPayload | null> {
  const api = process.env.MI_API_URL ?? process.env.MI_API_URL_BUILD ?? "http://127.0.0.1:8080";
  try {
    const res = await fetch(`${api}/v1/design`, {
      next: { revalidate: 5 },
      signal: AbortSignal.timeout(2500),
    });
    if (!res.ok) console.error(`tasarımlar alınamadı: ${api}/v1/design → ${res.status}`);
    return res.ok ? ((await res.json()) as DesignPayload) : null;
  } catch (e) {
    console.error(`tasarımlar alınamadı (API: ${api})`, e instanceof Error ? e.message : e);
    return null;
  }
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
