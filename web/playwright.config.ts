import { defineConfig, devices } from "@playwright/test";

// Sunucular dışarıda başlatılır (CI adımları veya yerelde): API + `next start`, demo verili test DB'si.
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "off",
    locale: "tr-TR",
    timezoneId: "Europe/Istanbul",
  },
  // Görsel karşılaştırma: yazı tipi/kenar yumuşatma farklarına küçük tolerans, animasyonlar kapalı.
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.01, animations: "disabled", caret: "hide" } },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } }, testIgnore: /visual\.spec\.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /public\.spec\.ts/ },
    // İsteğe bağlı: E2E_VISUAL=1 ile görsel karşılaştırma (masaüstü + mobil).
    ...(process.env.E2E_VISUAL
      ? [
          { name: "visual", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } }, testMatch: /visual\.spec\.ts/ },
          { name: "visual-mobile", use: { ...devices["Pixel 7"] }, testMatch: /visual\.spec\.ts/ },
        ]
      : []),
  ],
});
