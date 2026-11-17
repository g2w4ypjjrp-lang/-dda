"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AuthShell } from "@/components/AuthShell";
import { Button, FormError, Input } from "@/components/ui";
import { post } from "@/lib/api";

const schema = z.object({
  email: z.string().email("Geçerli bir e-posta girin"),
  password: z.string().min(1, "Parolanızı girin"),
});
const codeSchema = z.object({ code: z.string().min(6, "6 haneli kodu veya kurtarma kodunu girin").max(16) });

export default function LoginPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [step, setStep] = useState<"password" | "mfa">("password");
  const [error, setError] = useState<unknown>(null);
  const form = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });
  const codeForm = useForm<z.infer<typeof codeSchema>>({ resolver: zodResolver(codeSchema) });

  const done = async () => {
    await qc.invalidateQueries({ queryKey: ["me"] });
    const next = new URLSearchParams(window.location.search).get("next");
    router.push(next && next.startsWith("/") && !next.startsWith("//") ? next : "/panel");
  };

  const onPassword = form.handleSubmit(async (values) => {
    setError(null);
    try {
      const res = await post<{ mfa_required: boolean }>("/v1/auth/login", values);
      if (res.mfa_required) setStep("mfa");
      else await done();
    } catch (e) {
      setError(e);
    }
  });

  const onCode = codeForm.handleSubmit(async (values) => {
    setError(null);
    try {
      await post("/v1/auth/login/mfa", values);
      await done();
    } catch (e) {
      setError(e);
    }
  });

  if (step === "mfa") {
    return (
      <AuthShell title="İki adımlı doğrulama" subtitle="Doğrulama uygulamanızdaki 6 haneli kodu veya bir kurtarma kodunu girin.">
        <form onSubmit={onCode} className="space-y-4" noValidate>
          <Input label="Doğrulama kodu" inputMode="numeric" autoComplete="one-time-code" autoFocus {...codeForm.register("code")} error={codeForm.formState.errors.code?.message} />
          <FormError error={error} />
          <Button type="submit" className="w-full" loading={codeForm.formState.isSubmitting}>Doğrula ve giriş yap</Button>
        </form>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Giriş yapın"
      subtitle="Analizlerinize ve panelinize erişin."
      footer={<>Hesabınız yok mu? <Link href="/kayit" className="font-medium text-gold hover:underline">Ücretsiz hesap oluşturun</Link></>}
    >
      <form onSubmit={onPassword} className="space-y-4" noValidate>
        <Input label="E-posta" type="email" autoComplete="email" {...form.register("email")} error={form.formState.errors.email?.message} />
        <Input label="Parola" type="password" autoComplete="current-password" {...form.register("password")} error={form.formState.errors.password?.message} />
        <div className="flex justify-end">
          <Link href="/sifremi-unuttum" className="text-[12.5px] text-text-2 hover:text-text">Parolamı unuttum</Link>
        </div>
        <FormError error={error} />
        <Button type="submit" className="w-full" loading={form.formState.isSubmitting}>Giriş yap</Button>
      </form>
    </AuthShell>
  );
}
