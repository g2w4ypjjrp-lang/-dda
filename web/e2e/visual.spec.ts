import { expect, test } from "@playwright/test";

// Görsel karşılaştırma (isteğe bağlı): yalnızca E2E_VISUAL=1 ile "visual" projesinde çalışır.
// İçeriği güne/saate göre değişmeyen sayfalar seçildi (maç ve tahmin listeleri tarihe bağlıdır).
// Referanslar: e2e/visual.spec.ts-snapshots/ — bilinçli bir tasarım değişikliğinden sonra
//   E2E_VISUAL=1 npx playwright test --project=visual --update-snapshots
// ile yenilenir ve fark gözden geçirilerek commit edilir.
const PAGES = [
  { name: "giris", path: "/giris" },
  { name: "kayit", path: "/kayit" },
  { name: "sifremi-unuttum", path: "/sifremi-unuttum" },
  { name: "sss", path: "/sss" },
  { name: "risk", path: "/risk" },
  { name: "yonetim-giris", path: "/yonetim/giris" },
];

for (const p of PAGES) {
  test(`görsel: ${p.name}`, async ({ page }) => {
    await page.goto(p.path);
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => document.fonts.ready);
    await expect(page).toHaveScreenshot(`${p.name}.png`, { fullPage: true });
  });
}
