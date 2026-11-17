import type { NextConfig } from "next";

// API aynı köken üzerinden vekil edilir: tarayıcı yalnızca bu siteyle konuşur, oturum çerezleri
// birinci taraf ve SameSite=Strict kalır, API adresi ve anahtarları tarayıcıya hiç gitmez.
const API = process.env.MI_API_URL ?? "http://127.0.0.1:8080";
const production = process.env.NODE_ENV === "production";

const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'" + (production ? "" : " 'unsafe-eval'"),
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: https:",
  "font-src 'self'",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const config: NextConfig = {
  // Docker imajı için bağımsız sunucu çıktısı. Not: vekil adresi (MI_API_URL) derleme anında
  // rota tablosuna yazılır; imaj derlenirken verilmelidir.
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/v1/:path*", destination: `${API}/v1/:path*` },
      { source: "/admin/v1/:path*", destination: `${API}/admin/v1/:path*` },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          ...(production
            ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" }]
            : []),
        ],
      },
    ];
  },
};

export default config;
