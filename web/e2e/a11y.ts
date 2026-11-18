import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

/** WCAG 2.1 A/AA ihlali olmamalı (axe). Hata mesajı kural, etki ve ilk öğeleri listeler. */
export async function expectAccessible(page: Page, label: string): Promise<void> {
  await page.waitForLoadState("networkidle");
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const found = r.violations.map(
    (v) => `${v.id} [${v.impact}] ×${v.nodes.length}: ${v.nodes.slice(0, 3).map((n) => `${n.target.join(" ")} — ${(n.any[0] ?? n.all[0] ?? n.none[0])?.message ?? ""}`).join(" | ")}`,
  );
  expect(found, `${label}: erişilebilirlik ihlalleri`).toEqual([]);
}
