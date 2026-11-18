import { expect, test, type Page } from "@playwright/test";

import { grantPlan } from "./support";
import { expectAccessible } from "./a11y";

const PASSWORD = "E2e-Guclu-Parola-2026";

async function loginNew(page: Page, prefix: string) {
  await page.goto("/");
  const email = `${prefix}-${Date.now()}@ornek.com`;
  const origin = new URL(page.url()).origin;
  expect((await page.request.post("/v1/auth/register", { data: { email, password: PASSWORD, display_name: "Sanal Test", accept_terms: true }, headers: { Origin: origin } })).status()).toBe(202);
  grantPlan(email, "PRO");
  expect((await page.request.post("/v1/auth/login", { data: { email, password: PASSWORD }, headers: { Origin: origin } })).status()).toBe(200);
}

async function generateCoupon(page: Page): Promise<boolean> {
  await page.goto("/kuponlar");
  for (const day of ["Bugün", "Yarın"]) {
    await page.getByRole("button", { name: day, exact: true }).click();
    for (const profile of ["Dengeli", "Yüksek risk", "Düşük risk"]) {
      await page.getByText(profile, { exact: true }).click();
      await page.getByRole("button", { name: "Kupon oluştur" }).click();
      const ok = page.getByRole("heading", { name: "Önerilen kupon" });
      await expect(ok.or(page.getByRole("alert").filter({ hasText: "uygun maç" }))).toBeVisible();
      if (await ok.isVisible()) return true;
    }
  }
  return false;
}

test("sanal portföy: aç → kupon → sanal bilet → bakiye ve geçmiş", async ({ page }) => {
  await loginNew(page, "sanal");
  await page.goto("/sanal");
  await expect(page.getByText("Sanal portföy oluşturun")).toBeVisible();
  const open = page.getByRole("button", { name: "Sanal portföyü aç" });
  await expect(open).toBeDisabled();
  await page.getByRole("checkbox").check();
  await open.click();
  await expect(page.getByText("10.000,00 SB").first()).toBeVisible();

  test.skip(!(await generateCoupon(page)), "Demo verisinde uygun yayımlanmış tahmin yok");
  await page.getByRole("button", { name: "Kuponu kaydet" }).click();
  await expect(page.getByText("Sanal bilet aç", { exact: false }).first()).toBeVisible();
  await page.getByRole("button", { name: "Sanal bilet aç" }).click();
  await expect(page.getByText(/Sanal bilet açıldı: 100,00 SB/)).toBeVisible();

  await page.getByRole("link", { name: "Sanal Portföy" }).last().click();
  await expect(page.getByText("9.900,00 SB").first()).toBeVisible();
  await expect(page.getByText("Bekliyor").first()).toBeVisible();
  await expect(page.getByText(/gerçek para değildir/).first()).toBeVisible();
  await expectAccessible(page, "/sanal (açık portföy)");
  await page.goto("/kuponlar");
  await expectAccessible(page, "/kuponlar (PRO)");
});
