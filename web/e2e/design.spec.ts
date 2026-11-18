import { expect, test, type Page } from "@playwright/test";

import { sql } from "./support";
import { freshTotp } from "./totp";

const PASSWORD = "E2e-Guclu-Parola-2026";
const used = new Set<number>();

async function register(page: Page, prefix: string): Promise<string> {
  await page.goto("/");
  const origin = new URL(page.url()).origin;
  const email = `${prefix}-${Date.now()}@ornek.com`;
  expect((await page.request.post("/v1/auth/register", { data: { email, password: PASSWORD, display_name: "Tasarım Test", accept_terms: true }, headers: { Origin: origin } })).status()).toBe(202);
  expect((await page.request.post("/v1/auth/login", { data: { email, password: PASSWORD }, headers: { Origin: origin } })).status()).toBe(200);
  return email;
}

test("kullanıcı tasarım seçer: kabuk ve yerleşim değişir, varsayılana döner", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-shell", /topbar|sidebar|terminal|masthead/);
  await register(page, "gorunum");
  await page.goto("/panel");
  await page.getByRole("radio", { name: "Quantum Terminal" }).click();
  await page.waitForLoadState("load");
  await expect(page.locator("html")).toHaveAttribute("data-design", "quantum-terminal");
  await expect(page.locator("html")).toHaveAttribute("data-shell", "terminal");
  await page.goto("/");
  await expect(page.getByLabel("Veri durumu").getByText("KAYNAK")).toBeVisible(); // terminal durum şeridi
  await expect(page.getByText("Günün tahtası · 1X2 model olasılıkları")).toBeVisible();

  await page.goto("/panel");
  await page.getByRole("radio", { name: "Editorial Sports" }).click();
  await page.waitForLoadState("load");
  await expect(page.locator("html")).toHaveAttribute("data-shell", "masthead");
  await page.getByRole("button", { name: "Site varsayılanı" }).click();
  await page.waitForLoadState("load");
  await expect(page.locator("html")).not.toHaveAttribute("data-design", "editorial-sports");
});

test("Design Studio: taslak → düzenle → yayınla → geçmiş → geri al", async ({ page }) => {
  const email = await register(page, "studio");
  await page.goto("/panel");
  await page.getByRole("button", { name: "Kurulumu başlat" }).click();
  const secret = (await page.locator("code").first().textContent())!.trim();
  await page.getByLabel("Uygulamadaki 6 haneli kod").fill(await freshTotp(secret, used));
  await page.getByRole("button", { name: "Etkinleştir" }).click();
  await expect(page.getByText("bir daha gösterilmez")).toBeVisible();
  sql(`INSERT INTO user_roles (user_id, role_code) SELECT id, 'ADMIN' FROM users WHERE email = '${email}'`);

  await page.goto("/yonetim/giris");
  await page.getByLabel("E-posta").fill(email);
  await page.getByLabel("Parola").fill(PASSWORD);
  await page.getByLabel("Doğrulama kodu").fill(await freshTotp(secret, used));
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await page.getByRole("link", { name: "Design Studio" }).click();
  await expect(page.getByRole("heading", { name: "Design Studio" })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(10);

  // Önizleme: gerçek sayfa iframe içinde, seçilen tasarımla.
  const swiss = page.getByRole("article").filter({ hasText: "Swiss Intelligence" });
  await swiss.getByRole("button", { name: "Önizle" }).click();
  const frame = page.frameLocator("iframe[title$='önizlemesi']");
  await expect(frame.locator("html")).toHaveAttribute("data-design", "swiss-intelligence");
  await page.getByRole("button", { name: "Kapat" }).click();

  // Taslak → vurgu rengini değiştir → kaydet → yayınla (onay).
  await swiss.getByRole("button", { name: "Düzenle" }).click();
  await page.getByRole("button", { name: "Taslak oluştur" }).click();
  // Erişilebilirlik kapısı: düşük kontrastlı vurgu uyarı verir ve yayını kapatır.
  await page.getByRole("textbox", { name: "Vurgu", exact: true }).fill("#ffcc00");
  await expect(page.getByTestId("contrast-issues")).toContainText("WCAG AA kontrastının altında");
  await expect(page.getByRole("button", { name: "Yayınla" })).toBeDisabled();
  await page.getByRole("textbox", { name: "Vurgu", exact: true }).fill("#0047d6");
  await expect(page.getByTestId("contrast-issues")).toHaveCount(0);
  await page.getByLabel("Ana sayfa", { exact: true }).selectOption("institutional");
  await page.getByRole("button", { name: "Taslağı kaydet" }).click();
  await expect(page.getByText("Taslak kaydedildi.")).toBeVisible();
  await page.getByRole("button", { name: "Yayınla" }).click();
  await page.getByRole("button", { name: "Onaylıyorum, yayınla" }).click();
  await expect(swiss.getByText("v2 yayında")).toBeVisible();

  const pub = await (await page.request.get("/v1/design")).json();
  expect(pub.designs["swiss-intelligence"].version).toBe(2);
  expect(pub.designs["swiss-intelligence"].config.colors.accent).toBe("#0047d6");

  // Geçmiş → v1'e dön (yeni sürüm v3 olarak yayımlanır).
  await swiss.getByRole("button", { name: "Geçmiş" }).click();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("listitem").filter({ hasText: "v1" }).getByRole("button", { name: "Bu sürüme dön" }).click();
  await expect(swiss.getByText("v3 yayında")).toBeVisible();
  const after = await (await page.request.get("/v1/design")).json();
  expect(after.designs["swiss-intelligence"].config.colors.accent).toBe("#b22419");
});
