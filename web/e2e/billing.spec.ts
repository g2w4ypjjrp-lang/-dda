import { expect, test } from "@playwright/test";

import { sql } from "./support";

const PASSWORD = "E2e-Guclu-Parola-2026";

test("paketler: FREE kilitleri → test ödemesi → PRO etkin", async ({ page }) => {
  // Kurulum: PRO aylık fiyatı (yönetim panelinden de verilebilir) — test veritabanında.
  sql("UPDATE plan_prices SET active = false WHERE plan_code = 'PRO' AND period = 'monthly' AND active");
  sql("INSERT INTO plan_prices (plan_code, period, amount_minor, currency, active, created_at) VALUES ('PRO', 'monthly', 19900, 'TRY', true, now())");

  await page.goto("/paketler");
  await expect(page.getByRole("heading", { name: "Analiz derinliğinizi seçin" })).toBeVisible();
  await expect(page.getByTestId("plan-PRO").getByText("199,00")).toBeVisible();
  await expect(page.getByTestId("plan-ELITE").getByText("Fiyat yakında")).toBeVisible();

  const email = `odeme-${Date.now()}@ornek.com`;
  const origin = new URL(page.url()).origin;
  expect((await page.request.post("/v1/auth/register", { data: { email, password: PASSWORD, display_name: "Ödeme Test", accept_terms: true }, headers: { Origin: origin } })).status()).toBe(202);
  sql(`UPDATE users SET email_verified_at = now() WHERE email = '${email}'`);
  expect((await page.request.post("/v1/auth/login", { data: { email, password: PASSWORD }, headers: { Origin: origin } })).status()).toBe(200);

  await page.goto("/panel");
  await expect(page.getByText("Ücretsiz paket").first()).toBeVisible();

  await page.goto("/paketler");
  await page.getByRole("button", { name: "Pro satın al" }).click();
  await page.getByLabel("Ad soyad (fatura)").fill("Ödeme Test");
  const pay = page.getByRole("button", { name: "Ödemeye geç" });
  await expect(pay).toBeDisabled(); // onay kutuları zorunlu
  for (const box of await page.getByRole("checkbox").all()) await box.check();
  await pay.click();

  await expect(page.getByText("TEST MODU — gerçek ödeme alınmaz")).toBeVisible();
  await page.getByRole("button", { name: "Başarılı ödeme" }).click();
  await expect(page.getByTestId("order-status")).toHaveText(/Ödendi/);

  await page.getByRole("link", { name: "Panelime git" }).click();
  await expect(page.getByTestId("plan-period")).toContainText("Ödeme ile");
  await expect(page.getByText(/#\d+ · PRO \(test\)/)).toBeVisible();
});
