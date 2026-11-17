import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: { default: "Match Intelligence AI", template: "%s · Match Intelligence AI" },
  description:
    "Gerçek futbol verisi, açıklanabilir yapay zekâ ve şeffaf olasılıklar. Tahminler kazanç garantisi değildir.",
  icons: { icon: "/icon.svg" },
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = { themeColor: "#0a0b0d", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="tr" data-design="signature-black">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
