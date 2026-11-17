import { expect, test } from "@playwright/test";

import { grantPlan } from "./support";

const PASSWORD = "E2e-Guclu-Parola-2026";

test("maç sayfasından kupona ekle → seçimlerim → birleşik olasılık → kaydet", async ({ page }) => {
  await page.goto("/");
  const origin = new URL(page.url()).origin;
  const email = `sepet-${Date.now()}@ornek.com`;
  expect((await page.request.post("/v1/auth/register", { data: { email, password: PASSWORD, display_name: "Sepet Test", accept_terms: true }, headers: { Origin: origin } })).status()).toBe(202);
  grantPlan(email, "PRO");
  expect((await page.request.post("/v1/auth/login", { data: { email, password: PASSWORD }, headers: { Origin: origin } })).status()).toBe(200);

  // Yayımlanmış tahmini olan, başlamamış bir maç bul (demo verisi).
  let fixtureId: number | null = null;
  for (const offset of [0, 1]) {
    const day = new Date(Date.now() + offset * 86_400_000).toLocaleDateString("en-CA", { timeZone: "Europe/Istanbul" });
    const items = (await (await page.request.get(`/v1/predictions?date=${day}`)).json()).items as { fixture_id: number; status: string; kickoff_at: string }[];
    const hit = items.find((p) => p.status === "published" && Date.parse(p.kickoff_at) > Date.now() + 15 * 60_000);
    if (hit) { fixtureId = hit.fixture_id; break; }
  }
  test.skip(fixtureId === null, "Demo verisinde başlamamış yayımlanmış tahmin yok");

  await page.goto(`/maclar/${fixtureId}`);
  await expect(page.getByText("Olasılık dağılımı")).toBeVisible();
  // İY modeli demo verisinde kalibrasyon kapısını geçmezse neden açıkça yazılır; geçerse İY bölümü görünür.
  await expect(page.getByTestId("first-half").or(page.getByTestId("first-half-unavailable"))).toBeVisible();

  await page.getByRole("button", { name: "Maç sonucu: 1 kupona ekle" }).click();
  await page.getByRole("button", { name: "2.5 Üst kupona ekle" }).click();
  await expect(page.getByRole("button", { name: "2.5 Üst kupondan çıkar" })).toBeVisible();

  await page.getByRole("link", { name: "Kupon Merkezi" }).first().click();
  const basket = page.getByTestId("basket");
  await expect(basket.getByText("Kupona eklenenler (2)")).toBeVisible();
  await expect(basket.getByRole("heading", { name: "Seçimlerimin birleşik olasılığı" })).toBeVisible();
  await expect(basket.getByText("Simülasyon doğruladı")).toBeVisible();
  await basket.getByRole("button", { name: "Kuponu kaydet" }).click();
  await expect(basket.getByRole("button", { name: "Kaydedildi" })).toBeVisible();
  await expect(page.getByText("2 seçim").first()).toBeVisible(); // Kuponlarım geçmişi
});
