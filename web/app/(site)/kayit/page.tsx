"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { MailCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AuthShell } from "@/components/AuthShell";
import { Button, FormError, Input } from "@/components/ui";
import { post } from "@/lib/api";

const schema = z.object({
  display_name: z.string().trim().min(1, "Adınızı girin").max(80),
  email: z.string().email("Geçerli bir e-posta girin"),
  password: z.string().min(10, "Parola en az 10 karakter olmalı").max(256),
  accept_terms: z.literal(true, { message: "Devam etmek için onaylamanız gerekiyor" }),
});

export default function RegisterPage() {
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const form = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });

  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      await post("/v1/auth/register", values);
      setSent(true);
    } catch (e) {
      setError(e);
    }
  });

  if (sent) {
    return (
      <AuthShell title="Hesabınız hazır" subtitle="E-posta adresinizi doğrulamak için gelen kutunuzu kontrol edin. Bu sırada giriş yapabilirsiniz.">
        <div className="flex items-center gap-3 rounded-ctl border border-teal/30 bg-teal-soft px-4 py-3 text-[13px]">
          <MailCheck className="size-5 text-teal" aria-hidden /> Doğrulama bağlantısı e-posta adresinize gönderilecek.
        </div>
        <Link href="/giris" className="mt-5 inline-flex h-10 w-full items-center justify-center rounded-ctl bg-gold text-sm font-semibold text-[#14110a]">Giriş yap</Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Ücretsiz hesap oluşturun"
      subtitle="Günün maçları, temel istatistikler ve sınırlı AI analizleri ücretsizdir."
      footer={<>Zaten hesabınız var mı? <Link href="/giris" className="font-medium text-gold hover:underline">Giriş yapın</Link></>}
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <Input label="Ad" autoComplete="name" {...form.register("display_name")} error={form.formState.errors.display_name?.message} />
        <Input label="E-posta" type="email" autoComplete="email" {...form.register("email")} error={form.formState.errors.email?.message} />
        <Input label="Parola" type="password" autoComplete="new-password" hint="En az 10 karakter; kolay tahmin edilen parolalar kabul edilmez." {...form.register("password")} error={form.formState.errors.password?.message} />
        <label className="flex items-start gap-2.5 text-[12.5px] leading-relaxed text-text-2">
          <input type="checkbox" className="mt-0.5 size-4 accent-[var(--mi-gold)]" {...form.register("accept_terms")} />
          <span>
            18 yaşından büyük olduğumu, <Link href="/risk" className="text-gold hover:underline">risk bildirimini</Link> okuduğumu ve tahminlerin kazanç garantisi olmadığını anladığımı onaylıyorum.
          </span>
        </label>
        {form.formState.errors.accept_terms && <p className="text-xs text-red">{form.formState.errors.accept_terms.message}</p>}
        <FormError error={error} />
        <Button type="submit" className="w-full" loading={form.formState.isSubmitting}>Hesap oluştur</Button>
      </form>
    </AuthShell>
  );
}
