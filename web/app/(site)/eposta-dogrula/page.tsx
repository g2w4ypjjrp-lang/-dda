"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect } from "react";

import { AuthShell } from "@/components/AuthShell";
import { FormError } from "@/components/ui";
import { post } from "@/lib/api";

export default function VerifyEmailPage() {
  const verify = useMutation({ mutationFn: (token: string) => post("/v1/auth/verify-email", { token }) });
  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("token");
    if (token) verify.mutate(token);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <AuthShell title="E-posta doğrulama">
      {verify.isPending && <p className="text-[13.5px] text-muted">Doğrulanıyor…</p>}
      {verify.isSuccess && <p className="text-[13.5px] text-teal">E-posta adresiniz doğrulandı.</p>}
      {verify.isError && <FormError error={verify.error} />}
      {verify.isIdle && <p className="text-[13.5px] text-muted">Bağlantı geçersiz.</p>}
      <Link href="/panel" className="mt-6 inline-flex h-10 w-full items-center justify-center rounded-ctl border border-line-strong text-sm">Panele git</Link>
    </AuthShell>
  );
}
