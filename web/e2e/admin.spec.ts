import { expect, test } from "@playwright/test";

import { sql } from "./support";
import { freshTotp } from "./totp";

const PASSWORD = "E2e-Guclu-Parola-2026";
const used = new Set<number>();

test("yönetim: Command Center → Ctrl+K → Action Center → Data Explorer + CSV → bayrak → sistem/güvenlik", async ({ page }) => {
  await page.goto("/");
  const origin = new URL(page.url()).origin;
  const email = `ops-${Date.now()}@ornek.com`;
  expect((await page.request.post("/v1/auth/register", { data: { email, password: PASSWORD, display_name: "Ops Yönetici", accept_terms: true }, headers: { Origin: origin } })).status()).toBe(202);
  expect((await page.request.post("/v1/auth/login", { data: { email, password: PASSWORD }, headers: { Origin: origin } })).status()).toBe(200);
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

  // Command Center: izinli bölümler, gerçek değer yoksa "Veri yok".
  await expect(page.getByRole("heading", { name: "Platform durumu" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Futbol operasyonları" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "İşletme" })).toBeVisible();
  await expect(page.getByText("Maliyet verisi bağlı değil")).toBeVisible();

  // Komut paleti: modül ve kayıt araması.
  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Komut paleti" });
  await expect(palette).toBeVisible();
  await palette.getByRole("combobox").fill(email.slice(0, 12));
  await expect(palette.getByRole("option").filter({ hasText: email })).toBeVisible();
  await palette.getByRole("combobox").fill("action");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Action Center" })).toBeVisible();

  // Action Center: sağlayıcı uyarısı → görüldü.
  const issue = page.getByTestId("issue-football_provider:none");
  await expect(issue).toBeVisible();
  await issue.getByRole("button", { name: "Görüldü" }).click();
  await expect(issue).toHaveCount(0);

  // Data Explorer: arama + CSV (data.export, denetim kaydı).
  await page.getByRole("link", { name: "Data Explorer" }).click();
  await page.getByRole("tab", { name: "Kullanıcılar" }).click();
  await page.getByRole("textbox", { name: "Ara" }).fill(email);
  await page.getByRole("button", { name: "Ara", exact: true }).click();
  await expect(page.getByText("1 kayıt")).toBeVisible();
  await expect(page.getByRole("cell", { name: email })).toBeVisible();
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "CSV dışa aktar" }).click()]);
  expect(download.suggestedFilename()).toBe("users.csv");
  expect(sql("SELECT count(*) FROM audit_log WHERE action = 'admin.data_exported'")).not.toBe("0");

  // Bayrak: duyuru şeridi (backend'de uygulanır) — testten sonra kapatılır.
  await page.getByRole("link", { name: "Özellik Bayrakları" }).click();
  const notice = page.getByTestId("flag-maintenance_notice");
  await notice.getByRole("textbox").fill("E2E: planlı bakım duyurusu");
  page.once("dialog", (d) => d.accept());
  await notice.getByRole("button", { name: "Aç" }).click();
  await expect(notice.getByText("Açık")).toBeVisible();
  await page.goto("/");
  await expect(page.getByTestId("site-notice")).toHaveText("E2E: planlı bakım duyurusu");
  sql("UPDATE feature_flags SET enabled = false WHERE key = 'maintenance_notice'");

  // Sistem sağlığı ve güvenlik merkezi gerçek ölçümlerle açılır.
  await page.goto("/yonetim/sistem");
  await expect(page.getByRole("heading", { name: "Servis durumu" })).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "PostgreSQL" }).getByText("Çalışıyor")).toBeVisible();
  await page.goto("/yonetim/guvenlik");
  await expect(page.getByText("Yönetici MFA")).toBeVisible();
  await page.goto("/yonetim/roller");
  await expect(page.getByRole("cell", { name: /finance\.refund/ })).toBeVisible();
});
