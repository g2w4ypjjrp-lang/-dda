import { expect, test } from "@playwright/test";
import { expectAccessible } from "./a11y";

const PASSWORD = "E2e-Guclu-Parola-2026";

test("panel: maçı kaydet → widget → düzenle/kaydet → bildirim zili → SSS/yasal → PWA çevrimdışı", async ({ page, context }) => {
  await page.goto("/");
  const origin = new URL(page.url()).origin;
  const email = `panel-${Date.now()}@ornek.com`;
  expect((await page.request.post("/v1/auth/register", { data: { email, password: PASSWORD, display_name: "Panel Test", accept_terms: true }, headers: { Origin: origin } })).status()).toBe(202);
  expect((await page.request.post("/v1/auth/login", { data: { email, password: PASSWORD }, headers: { Origin: origin } })).status()).toBe(200);

  // Bugünün bir maçını kaydet ve ev sahibini favorilere ekle.
  const day = new Date().toLocaleDateString("en-CA", { timeZone: "Europe/Istanbul" });
  const fixtures = (await (await page.request.get(`/v1/football/fixtures?date=${day}`)).json()).items as { id: number; home: { name: string }; away: { name: string } }[];
  test.skip(fixtures.length === 0, "Demo verisinde bugün maç yok");
  const fx = fixtures[0]!;
  await page.goto(`/maclar/${fx.id}`);
  await page.getByRole("button", { name: `${fx.home.name} – ${fx.away.name}: favorilere ekle` }).click();
  await expect(page.getByRole("button", { name: `${fx.home.name} – ${fx.away.name}: favorilerden çıkar` })).toHaveText("Kaydedildi");
  await page.getByRole("button", { name: `${fx.home.name}: favorilere ekle` }).click();

  // Panel bileşenleri gerçek veriyle; düzenle → kaldır → kaydet → yeniden yükle.
  await page.goto("/panel");
  const saved = page.locator('[data-widget="saved_matches"]');
  await expect(saved.getByText(fx.home.name).first()).toBeVisible();
  await expect(page.locator('[data-widget="favorite_teams"]').getByText(fx.home.name).first()).toBeVisible();
  await page.getByRole("button", { name: "Paneli düzenle" }).click();
  await page.getByRole("button", { name: "Hesap özeti kaldır" }).click();
  await page.locator('[data-widget="today"]').getByRole("button", { name: "Orta" }).click();
  await page.getByRole("button", { name: "Düzeni kaydet" }).click();
  await page.reload();
  await expect(page.locator('[data-widget="account"]')).toHaveCount(0);
  await expect(page.locator('[data-widget="today"]')).toHaveClass(/lg:col-span-6/);
  await page.getByRole("button", { name: "Paneli düzenle" }).click();
  await page.getByRole("button", { name: "Hesap özeti", exact: true }).click();
  await page.getByRole("button", { name: "Düzeni kaydet" }).click();
  await expect(page.locator('[data-widget="account"]')).toHaveCount(1);
  await expectAccessible(page, "/panel");

  // Güvenlik bildirimi → zil.
  expect((await page.request.post("/v1/auth/password/change", { data: { current_password: PASSWORD, new_password: "E2e-Yeni-Parola-2027" }, headers: { Origin: origin } })).status()).toBe(200);
  await page.reload();
  const bell = page.getByRole("button", { name: "Bildirimler 1 okunmamış" });
  await expect(bell).toBeVisible();
  await bell.click();
  await expect(page.getByRole("dialog", { name: "Bildirimler" }).getByText("Parolanız değiştirildi")).toBeVisible();
  await page.getByRole("link", { name: "Tümü ve tercihler" }).click();
  await expect(page.getByRole("checkbox", { name: "Güvenlik uygulama içi" })).toBeDisabled();
  await expectAccessible(page, "/bildirimler");
  await page.getByRole("button", { name: "Tümünü okundu say" }).first().click();
  await expect(page.getByRole("button", { name: "Bildirimler", exact: true })).toBeVisible();

  // İçerik: SSS ve henüz yayımlanmamış yasal metin.
  await page.goto("/sss");
  await expect(page.getByText("Sanal portföy gerçek para mı?")).toBeVisible();
  await page.goto("/yasal/gizlilik");
  await expect(page.getByText("Henüz yayımlanmadı")).toBeVisible();

  // PWA: manifest ikonları, servis çalışanı, çevrimdışı sayfa (önbellekten canlı veri yok).
  const manifest = await (await page.request.get("/manifest.webmanifest")).json();
  expect(manifest.icons.map((i: { sizes: string }) => i.sizes)).toEqual(expect.arrayContaining(["192x192", "512x512"]));
  await page.goto("/");
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.reload();
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true);
  await context.setOffline(true);
  await page.goto("/maclar");
  await expect(page.getByRole("heading", { name: "İnternet bağlantısı yok" })).toBeVisible();
  await context.setOffline(false);
});
