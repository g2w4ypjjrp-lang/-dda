"use client";

import { useState } from "react";

import { AuthShell } from "@/components/AuthShell";
import { Button, FormError, Input } from "@/components/ui";
import { post } from "@/lib/api";

export default function ForgotPage() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "busy" | "sent">("idle");
  const [error, setError] = useState<unknown>(null);
  return (
    <AuthShell title="Parola sıfırlama" subtitle="Hesabınıza kayıtlı e-postayı girin; sıfırlama bağlantısı gönderelim.">
      {state === "sent" ? (
        <p className="text-[13.5px] leading-relaxed text-text-2">Bu adrese kayıtlı bir hesap varsa sıfırlama bağlantısı gönderildi. Bağlantı 1 saat geçerlidir.</p>
      ) : (
        <form
          className="space-y-4"
          onSubmit={async (e) => {
            e.preventDefault();
            setError(null);
            setState("busy");
            try {
              await post("/v1/auth/password/forgot", { email });
              setState("sent");
            } catch (err) {
              setError(err);
              setState("idle");
            }
          }}
        >
          <Input label="E-posta" type="email" name="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <FormError error={error} />
          <Button type="submit" className="w-full" loading={state === "busy"}>Bağlantı gönder</Button>
        </form>
      )}
    </AuthShell>
  );
}
