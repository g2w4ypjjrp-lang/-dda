import { test } from "@playwright/test";

import { expectAccessible } from "./a11y";

// Erişilebilirlik (axe, WCAG 2.1 AA): herkese açık sayfalar varsayılan tasarımda, ayrıca 10 tasarımın
// her biri (renk kontrastı tasarıma bağlıdır). Oturum gerektiren ve yönetim sayfaları ilgili akış
// testlerinin içinde denetlenir (kayıt hız sınırını aşmamak için).
const PUBLIC = ["/", "/maclar", "/ligler", "/performans", "/risk", "/sss", "/paketler", "/giris", "/kayit", "/sifremi-unuttum", "/kuponlar", "/sanal", "/yonetim/giris"];
const DESIGNS = ["signature-black", "swiss-intelligence", "quantum-terminal", "editorial-sports", "ai-atelier", "architectural-luxury", "institutional-blue", "obsidian-glass", "future-sports-lab", "mi-signature"];

test("erişilebilirlik: herkese açık sayfalar", async ({ page }) => {
  test.setTimeout(180_000);
  const fixture = (await (await page.request.get("/v1/football/fixtures?status=finished&limit=1")).json()).items?.[0];
  const league = (await (await page.request.get("/v1/football/competitions")).json()).items?.[0];
  const pages = [...PUBLIC, ...(fixture ? [`/maclar/${fixture.id}`] : []), ...(league ? [`/ligler/${league.id}`] : [])];
  for (const p of pages) {
    await page.goto(p);
    await expectAccessible(page, p);
  }
});

test("erişilebilirlik: 10 tasarımın her biri (renk kontrastı dahil)", async ({ page, context }) => {
  test.setTimeout(300_000);
  const fixture = (await (await page.request.get("/v1/football/fixtures?status=finished&limit=1")).json()).items?.[0];
  for (const d of DESIGNS) {
    await context.addCookies([{ name: "mi_design", value: d, url: test.info().project.use.baseURL ?? "http://localhost:3000" }]);
    for (const p of ["/", "/maclar", ...(fixture ? [`/maclar/${fixture.id}`] : []), "/paketler", "/giris"]) {
      await page.goto(p);
      await expectAccessible(page, `${d} ${p}`);
    }
  }
});
