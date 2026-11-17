import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { freshTotp } from "./totp";

const PASSWORD = "E2e-Guclu-Parola-2026";
const used = new Set<number>();

async function enableMfa(page: import("@playwright/test").Page): Promise<string> {
  await page.goto("/panel");
  await page.getByRole("button", { name: "Kurulumu başlat" }).click();
  const secret = (await page.locator("code").first().textContent())!.trim();
  await page.getByLabel("Uygulamadaki 6 haneli kod").fill(await freshTotp(secret, used));
  await page.getByRole("button", { name: "Etkinleştir" }).click();
  await expect(page.getByText("bir daha gösterilmez")).toBeVisible();
  return secret;
}

test("kayıt → giriş → MFA → iki adımlı giriş → oturumlar", async ({ page }) => {
  const email = `e2e-${Date.now()}@ornek.com`;
  await page.goto("/kayit");
  await page.getByLabel("Ad", { exact: true }).fill("E2E Kullanıcı");
  await page.getByLabel("E-posta").fill(email);
  await page.getByLabel("Parola").fill(PASSWORD);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Hesap oluştur" }).click();
  await expect(page.getByText("Hesabınız hazır")).toBeVisible();

  await page.goto("/giris");
  await page.getByLabel("E-posta").fill(email);
  await page.getByLabel("Parola").fill(PASSWORD);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: /Merhaba, E2E Kullanıcı/ })).toBeVisible();

  const secret = await enableMfa(page);
  await page.getByRole("button", { name: "Çıkış" }).click();
  await page.waitForURL("/");

  await page.goto("/giris");
  await page.getByLabel("E-posta").fill(email);
  await page.getByLabel("Parola").fill(PASSWORD);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "İki adımlı doğrulama" })).toBeVisible();
  await page.getByLabel("Doğrulama kodu").fill("000000");
  await page.getByRole("button", { name: "Doğrula ve giriş yap" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "hatalı" })).toBeVisible();
  await page.getByLabel("Doğrulama kodu").fill(await freshTotp(secret, used));
  await page.getByRole("button", { name: "Doğrula ve giriş yap" }).click();
  await expect(page.getByRole("heading", { name: /Merhaba/ })).toBeVisible();
  await expect(page.getByText("Bu cihaz")).toBeVisible();
});

test("ilk süper yönetici: parolasız kurulum → parola → MFA → yönetim paneli", async ({ page }) => {
  const apiDir = process.env.E2E_API_DIR ?? path.resolve(__dirname, "../../api");
  const email = `kurucu-${Date.now()}@ornek.com`;
  let out: string;
  try {
    out = execFileSync("uv", ["run", "mi-admin", "bootstrap", "--email", email, "--name", "E2E Kurucu"], { cwd: apiDir, encoding: "utf8" });
  } catch (e) {
    const err = e as { stdout?: string; stderr?: string };
    test.skip(`${err.stdout ?? ""}${err.stderr ?? ""}`.includes("Zaten aktif"), "Bu veritabanında zaten SUPER_ADMIN var (temiz DB gerekir)");
    throw e;
  }
  const token = /token=([A-Za-z0-9_-]+)/.exec(out)![1]!;

  await page.goto(`/sifre-sifirla?token=${token}`);
  await page.getByLabel("Yeni parola").fill(PASSWORD);
  await page.getByRole("button", { name: "Parolayı kaydet" }).click();
  await expect(page.getByText("Parolanız güncellendi")).toBeVisible();

  await page.goto("/giris");
  await page.getByLabel("E-posta").fill(email);
  await page.getByLabel("Parola").fill(PASSWORD);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: /Merhaba/ })).toBeVisible();
  const secret = await enableMfa(page);

  await page.goto("/yonetim/giris");
  await page.getByLabel("E-posta").fill(email);
  await page.getByLabel("Parola").fill(PASSWORD);
  await page.getByLabel("Doğrulama kodu").fill(await freshTotp(secret, used));
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "Platform durumu" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Dikkat gerektirenler" })).toBeVisible();

  await page.getByRole("link", { name: "Futbol Veri Merkezi" }).click();
  await expect(page.getByRole("heading", { name: "Veri işleri ve ligler" })).toBeVisible();
  await page.getByLabel("İş").selectOption("live");
  await page.getByRole("button", { name: "Çalıştır" }).click();
  await expect(page.getByRole("main").getByText(/yapılandırılmamış|Canlı veya başlamak üzere/).first()).toBeVisible();

  await page.getByRole("link", { name: "Model Lab" }).click();
  await expect(page.getByRole("heading", { name: "Model Lab" })).toBeVisible();
  await expect(page.getByText("Şampiyon").first()).toBeVisible();

  await page.getByRole("link", { name: "Kullanıcılar" }).click();
  await page.getByLabel("Ara").fill(email);
  await expect(page.getByRole("cell", { name: email })).toBeVisible();

  await page.getByRole("link", { name: "Denetim Kaydı" }).click();
  await page.getByRole("button", { name: "Zinciri doğrula" }).click();
  await expect(page.getByText("Zincir sağlam")).toBeVisible();
});
