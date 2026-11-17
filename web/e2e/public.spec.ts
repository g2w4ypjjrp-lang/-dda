import { expect, test } from "@playwright/test";

test("ana sayfa, maç merkezi, maç detayı ve AI analizi", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("olasılıklarla");
  await expect(page.getByRole("heading", { name: "Günün maçları" })).toBeVisible();
  // Gerçek sonuçlanmış tahmin yokken performans uydurulmaz.
  await expect(page.getByText("Henüz sonuçlanmış tahmin yok")).toBeVisible();

  await page.goto("/maclar");
  await expect(page.getByRole("heading", { name: "Maçlar ve analizler" })).toBeVisible();
  const rows = page.locator('a[href^="/maclar/"]');
  await expect(rows.first()).toBeVisible();

  // Yayımlanmış bir tahmini olan maç: olasılık, güvenilirlik ve uyarı ayrı ayrı görünür.
  // Bugün ya da (geç saatte demo maçları yarına kayar) yarın yayımlanmış tahmini olan bir maç.
  type P = { status: string; fixture_id: number };
  let preds: { items: P[] } = { items: [] };
  let published: P | undefined;
  for (const offset of [0, 1]) {
    const day = new Date(Date.now() + offset * 86_400_000).toLocaleDateString("en-CA", { timeZone: "Europe/Istanbul" });
    preds = await (await page.request.get(`/v1/predictions?date=${day}`)).json();
    published = preds.items.find((p) => p.status === "published");
    if (published) break;
  }
  test.skip(!published, "Bugün ve yarın için yayımlanmış tahmin yok");
  await page.goto(`/maclar/${published!.fixture_id}`);
  await expect(page.getByText("Olasılık dağılımı")).toBeVisible();
  await expect(page.getByText("Model güvenilirliği")).toBeVisible();
  await expect(page.getByText("Modeller arası uyum")).toBeVisible();
  await expect(page.getByRole("main").getByText(/kazanç garantisi değildir/)).toBeVisible();
  await expect(page.getByText(/Demo verisi/).first()).toBeVisible();

  const abstained = preds.items.find((p) => p.status === "abstained");
  if (abstained) {
    await page.goto(`/maclar/${abstained.fixture_id}`);
    await expect(page.getByText("Model bu maç için tahmin vermedi")).toBeVisible();
  }
});

test("model şeffaflığı ve risk bildirimi", async ({ page }) => {
  await page.goto("/performans");
  await expect(page.getByRole("heading", { name: "Gerçekleşmiş tahmin performansı" })).toBeVisible();
  await page.goto("/risk");
  await expect(page.getByText(/gerçek para ile bahis işlemi yapmaz/)).toBeVisible();
});
