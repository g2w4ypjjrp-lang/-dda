import { expect, test } from "@playwright/test";

import { sql } from "./support";
import { freshTotp } from "./totp";
import { expectAccessible } from "./a11y";

const PASSWORD = "E2e-Guclu-Parola-2026";
const used = new Set<number>();

// Faz 10: dört göz onayı ve yedekler sayfası. İkinci yöneticinin talebi SQL ile hazırlanır
// (E2E kayıt hız sınırını aşmamak için); onay, kural kapatma talebi ve görünüm arayüzden.
test("yönetim: başka yöneticinin talebini onayla → rol atanır; kuralı kapatmak da onaya gider; yedekler", async ({ page }) => {
  const stamp = Date.now();
  await page.goto("/");
  const origin = new URL(page.url()).origin;
  const email = `kurucu-${stamp}@ornek.com`;
  expect((await page.request.post("/v1/auth/register", { data: { email, password: PASSWORD, display_name: "Kurucu", accept_terms: true }, headers: { Origin: origin } })).status()).toBe(202);
  expect((await page.request.post("/v1/auth/login", { data: { email, password: PASSWORD }, headers: { Origin: origin } })).status()).toBe(200);
  await page.goto("/panel");
  await page.getByRole("button", { name: "Kurulumu başlat" }).click();
  const secret = (await page.locator("code").first().textContent())!.trim();
  await page.getByLabel("Uygulamadaki 6 haneli kod").fill(await freshTotp(secret, used));
  await page.getByRole("button", { name: "Etkinleştir" }).click();
  await expect(page.getByText("bir daha gösterilmez")).toBeVisible();
  sql(`INSERT INTO user_roles (user_id, role_code) SELECT id, 'SUPER_ADMIN' FROM users WHERE email = '${email}'`);

  // Talep eden ikinci yönetici ve rol atanacak aday (MFA açık).
  const requester = `talep-${stamp}@ornek.com`;
  const candidate = `aday-${stamp}@ornek.com`;
  sql(`INSERT INTO users (id, email, display_name, status, email_verified_at, mfa_secret_enc, mfa_enabled_at) VALUES
       (gen_random_uuid(), '${requester}', 'Talep Eden', 'active', now(), '\\x00', now()),
       (gen_random_uuid(), '${candidate}', 'Aday', 'active', now(), '\\x00', now())`);
  const approvalId = sql(`INSERT INTO approval_requests (action, permission, target, summary, payload, requested_by, requested_at, expires_at)
       SELECT 'roles.set', 'roles.assign', 'user:' || c.id, '${candidate} rolleri: +SUPPORT',
              jsonb_build_object('user', c.id::text, 'roles', jsonb_build_array('SUPPORT')), r.id, now(), now() + interval '1 day'
       FROM users c, users r WHERE c.email = '${candidate}' AND r.email = '${requester}' RETURNING id`);
  sql("UPDATE feature_flags SET enabled = true WHERE key = 'dual_control'");

  try {
    await page.goto("/yonetim/giris");
    await page.getByLabel("E-posta").fill(email);
    await page.getByLabel("Parola").fill(PASSWORD);
    await page.getByLabel("Doğrulama kodu").fill(await freshTotp(secret, used));
    await page.getByRole("button", { name: "Giriş yap" }).click();
    await expect(page.getByRole("heading", { name: "Platform durumu" })).toBeVisible();

    // Action Center bekleyen talebi gösterir; Onaylar sayfasından karar verilir.
    await page.getByRole("link", { name: "Onaylar (dört göz)" }).click();
    const row = page.getByTestId(`approval-${approvalId}`);
    await expect(row).toContainText("Yönetici rolü değişikliği");
    await expect(row).toContainText(requester);
    page.once("dialog", (d) => d.accept());
    await row.getByRole("button", { name: "Onayla ve yürüt" }).click();
    await expect(page.getByTestId(`approval-${approvalId}`)).toHaveCount(0);
    await page.getByRole("tab", { name: "Karara bağlanan" }).click();
    await expect(page.getByTestId(`approval-${approvalId}`)).toContainText("Onaylandı, yürütüldü");
    expect(sql(`SELECT string_agg(role_code, ',') FROM user_roles ur JOIN users u ON u.id = ur.user_id WHERE u.email = '${candidate}'`)).toBe("SUPPORT");

    // Kural açıkken kapatmak da ikinci onay ister: işlem yapılmaz, talep açılır.
    await page.getByRole("link", { name: "Özellik Bayrakları" }).click();
    const flag = page.getByTestId("flag-dual_control");
    page.once("dialog", (d) => d.accept());
    await flag.getByRole("button", { name: "Kapat" }).click();
    await expect(flag.getByTestId("approval-sent")).toContainText("ikinci bir yöneticinin onayına gönderildi");
    expect(sql("SELECT enabled FROM feature_flags WHERE key = 'dual_control'")).toBe("t");
    await page.getByRole("link", { name: "Onaylar (dört göz)" }).click();
    const own = page.locator("[data-testid^='approval-']").filter({ hasText: "Dört göz kuralını kapatma" });
    await expect(own).toContainText("Sizin talebiniz");
    await expect(own).toContainText("Kendi talebinizi onaylayamazsınız");
    await expect(own.getByRole("button", { name: "Onayla ve yürüt" })).toHaveCount(0);
    await own.getByRole("button", { name: "Talebi iptal et" }).click();
    await expect(own).toHaveCount(0);

    // Yedekler: yapılandırma yoksa açıkça söylenir; kayıtlar ve doğrulama sonucu listelenir.
    sql(`INSERT INTO backups (created_at, file_name, size_bytes, sha256, status, duration_ms, verified_at, verify_ok, verify, trigger)
         VALUES (now(), 'mi-e2e-${stamp}.dump', 1048576, repeat('a', 64), 'ok', 1200, now(), true,
                 '{"ok": true, "file_present": true, "sha256_ok": true, "archive_ok": true, "restore_tested": true, "restore_ok": true, "tables": 61, "alembic_version": "0012", "audit_chain_intact": true}', 'cli')`);
    await page.getByRole("link", { name: "Yedekler" }).click();
    await expect(page.getByText("Yedekleme yapılandırılmamış")).toBeVisible();
    await expect(page.getByRole("cell", { name: new RegExp(`mi-e2e-${stamp}`) })).toBeVisible();
    await expect(page.getByText("Geri yüklendi, sağlam")).toBeVisible();
    await expect(page.getByText(/61 tablo · şema 0012 · denetim zinciri sağlam/)).toBeVisible();

    // Erişilebilirlik: tüm yönetim modülleri (SUPER_ADMIN her birini görür).
    for (const p of ["/yonetim", "/yonetim/aksiyon", "/yonetim/onaylar", "/yonetim/veri", "/yonetim/modeller", "/yonetim/kuponlar",
      "/yonetim/sanal", "/yonetim/abonelikler", "/yonetim/finans", "/yonetim/kullanicilar", "/yonetim/roller", "/yonetim/guvenlik",
      "/yonetim/denetim", "/yonetim/veri-gezgini", "/yonetim/sistem", "/yonetim/yedekler", "/yonetim/bayraklar", "/yonetim/tasarim", "/yonetim/icerik"]) {
      await page.goto(p);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expectAccessible(page, p);
    }
  } finally {
    sql("UPDATE feature_flags SET enabled = false WHERE key = 'dual_control'");
    sql("UPDATE approval_requests SET status = 'cancelled', decided_at = now(), decided_by = requested_by WHERE status = 'pending'");
  }
});
