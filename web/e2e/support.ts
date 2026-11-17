import { execFileSync } from "node:child_process";
import path from "node:path";

const apiDir = process.env.E2E_API_DIR ?? path.resolve(__dirname, "../../api");

/** Test kullanıcısına ödemesiz paket verir (mi-admin grant-plan; denetim kaydına yazılır). */
export function grantPlan(email: string, plan: "PRO" | "ELITE", days = 30): void {
  execFileSync("uv", ["run", "mi-admin", "grant-plan", "--email", email, "--plan", plan, "--days", String(days)], { cwd: apiDir, encoding: "utf8" });
}

/** Test veritabanında doğrudan SQL (yalnızca kurulum: fiyat tanımı, e-posta doğrulama). */
export function sql(query: string): string {
  const url = process.env.MI_DATABASE_URL;
  if (!url) throw new Error("MI_DATABASE_URL gerekli (E2E test veritabanı)");
  return execFileSync("psql", [url, "-qtAc", query], { encoding: "utf8" }).trim();
}
