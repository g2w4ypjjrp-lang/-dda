"use client";

import Link from "next/link";
import { useState } from "react";

import { AuthShell } from "@/components/AuthShell";
import { Button, FormError, Input } from "@/components/ui";
import { post } from "@/lib/api";

export default function ResetPage() {
  const [password, setPassword] = useState("");
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const [error, setError] = useState<unknown>(null);
  return (
    <AuthShell title="Yeni parola belirleyin" subtitle="Parola değişince tüm cihazlardaki oturumlar kapatılır.">
      {state === "done" ? (
        <>
          <p className="text-[13.5px] text-teal">Parolanız güncellendi.</p>
          <Link href="/giris" className="mt-5 inline-flex h-10 w-full items-center justify-center rounded-ctl bg-gold text-sm font-semibold text-[#14110a]">Giriş yap</Link>
        </>
      ) : (
        <form
          className="space-y-4"
          onSubmit={async (e) => {
            e.preventDefault();
            setError(null);
            setState("busy");
            try {
              const token = new URLSearchParams(window.location.search).get("token") ?? "";
              await post("/v1/auth/password/reset", { token, password });
              setState("done");
            } catch (err) {
              setError(err);
              setState("idle");
            }
          }}
        >
          <Input label="Yeni parola" type="password" name="password" autoComplete="new-password" minLength={10} required value={password} onChange={(e) => setPassword(e.target.value)} hint="En az 10 karakter" />
          <FormError error={error} />
          <Button type="submit" className="w-full" loading={state === "busy"}>Parolayı kaydet</Button>
        </form>
      )}
    </AuthShell>
  );
}
