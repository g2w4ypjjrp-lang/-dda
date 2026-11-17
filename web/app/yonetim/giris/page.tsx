"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AuthShell } from "@/components/AuthShell";
import { Button, FormError, Input } from "@/components/ui";
import { ApiError, post } from "@/lib/api";

export default function AdminLoginPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [values, setValues] = useState({ email: "", password: "", code: "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof values) => (e: React.ChangeEvent<HTMLInputElement>) => setValues({ ...values, [k]: e.target.value });
  return (
    <div className="px-4">
      <AuthShell title="Yönetim paneli" subtitle="Yalnızca yetkili personel. Her giriş ve işlem denetim kaydına yazılır.">
        <form
          className="space-y-4"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError(null);
            try {
              await post("/admin/v1/auth/login", values);
              await qc.invalidateQueries({ queryKey: ["admin-me"] });
              router.push("/yonetim");
            } catch (err) {
              setError(
                err instanceof ApiError && err.code === "mfa_enrollment_required"
                  ? new ApiError(403, err.code, "Önce kullanıcı panelinizden (Panelim → İki adımlı doğrulama) doğrulamayı açın.")
                  : err,
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          <Input label="E-posta" type="email" name="email" autoComplete="username" required value={values.email} onChange={set("email")} />
          <Input label="Parola" type="password" name="password" autoComplete="current-password" required value={values.password} onChange={set("password")} />
          <Input label="Doğrulama kodu" name="code" inputMode="numeric" autoComplete="one-time-code" required value={values.code} onChange={set("code")} />
          <FormError error={error} />
          <Button type="submit" className="w-full" loading={busy}>Giriş yap</Button>
        </form>
      </AuthShell>
    </div>
  );
}
