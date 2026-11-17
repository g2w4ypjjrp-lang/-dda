"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, Empty, ErrorState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

export default function FaqPage() {
  const q = useQuery({ queryKey: ["content", "faq"], queryFn: () => api<{ items: { id: number; question: string; answer: string }[] }>("/v1/content/faq") });
  return (
    <div className="mx-auto max-w-3xl py-10">
      <div className="eyebrow mb-2">Yardım</div>
      <h1 className="text-[30px] font-semibold tracking-tight">Sık sorulan sorular</h1>
      <div className="mt-8">
        {q.isLoading ? <Skeleton className="h-64" /> : q.error ? <Card><ErrorState error={q.error} /></Card> : !q.data?.items.length ? <Card><Empty title="Henüz soru eklenmedi" /></Card> : (
          <div className="divide-y divide-line rounded-card border border-line bg-surface">
            {q.data.items.map((f) => (
              <details key={f.id} className="group px-5 py-4">
                <summary className="cursor-pointer list-none text-[14.5px] font-medium marker:hidden">
                  <span className="flex items-center justify-between gap-4">{f.question}<span className="text-gold transition-transform group-open:rotate-45" aria-hidden>+</span></span>
                </summary>
                <p className="mt-3 whitespace-pre-line text-[13.5px] leading-relaxed text-text-2">{f.answer}</p>
              </details>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
