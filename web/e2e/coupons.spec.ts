import { expect, test } from "@playwright/test";

const PASSWORD = "E2e-Guclu-Parola-2026";

test("kupon merkezi: giriş → kupon oluştur → kaydet → geçmiş", async ({ page }) => {
  await page.goto("/kuponlar");
  await expect(page.getByText("Kupon oluşturmak için giriş yapın")).toBeVisible();

  const email = `kupon-${Date.now()}@ornek.com`;
  const reg = await page.request.post("/v1/auth/register", {
    data: { email, password: PASSWORD, display_name: "Kupon Test", accept_terms: true },
    headers: { Origin: new URL(page.url()).origin },
  });
  expect(reg.status()).toBe(202);
  await page.goto("/giris?next=/kuponlar");
  await page.getByLabel("E-posta").fill(email);
  await page.getByLabel("Parola").fill(PASSWORD);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "Model tabanlı kupon oluşturucu" })).toBeVisible();

  // Demo verisinde hangi profilin uygun maç bulacağı modele bağlı: sırayla dene.
  let found = false;
  for (const day of ["Bugün", "Yarın"]) {
    await page.getByRole("button", { name: day, exact: true }).click();
    for (const profile of ["Dengeli", "Yüksek risk", "Düşük risk"]) {
      await page.getByText(profile, { exact: true }).click();
      await page.getByRole("button", { name: "Kupon oluştur" }).click();
      const ok = page.getByRole("heading", { name: "Önerilen kupon" });
      const err = page.getByRole("alert").filter({ hasText: "uygun maç" });
      await expect(ok.or(err)).toBeVisible();
      if (await ok.isVisible()) { found = true; break; }
    }
    if (found) break;
  }
  test.skip(!found, "Demo verisinde bu profillere uygun yayımlanmış tahmin yok");

  await expect(page.getByText("Birleşik olasılık", { exact: true })).toBeVisible();
  await expect(page.getByText("Simülasyon doğruladı")).toBeVisible();
  await expect(page.getByText(/beklenen değer \(EV\) hesaplanmaz/)).toBeVisible();
  await page.getByRole("button", { name: "Kuponu kaydet" }).click();
  await expect(page.getByRole("button", { name: "Kaydedildi" })).toBeVisible();
  await expect(page.getByText("Bekliyor").first()).toBeVisible();
});
