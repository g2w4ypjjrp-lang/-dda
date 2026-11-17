"use client";

import { useQuery } from "@tanstack/react-query";
import { use } from "react";

import { Card, ErrorState, Notice, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDay } from "@/lib/format";

interface Page { slug: string; title: string; body: string | null; published: boolean; published_at: string | null; updated_at: string; pending_note?: string }

/** Yasal ve bilgi sayfaları. Metin düz yazıdır (HTML çalıştırılmaz); paragraflar boş satırla ayrılır. */
export default function LegalPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const q = useQuery({ queryKey: ["content", "page", slug], queryFn: () => api<Page>(`/v1/content/pages/${slug}`), retry: false });
  return (
    <div className="mx-auto max-w-3xl py-10">
      {q.isLoading ? <Skeleton className="h-96" /> : q.error || !q.data ? <Card><ErrorState error={q.error} /></Card> : (
        <article>
          <div className="eyebrow mb-2">Yasal</div>
          <h1 className="text-[30px] font-semibold tracking-tight">{q.data.title}</h1>
          {q.data.body ? (
            <>
              <p className="mt-2 text-[12px] text-muted">Yürürlük: {q.data.published_at ? fmtDay(q.data.published_at) : "—"} · Son güncelleme: {fmtDay(q.data.updated_at)}</p>
              <div className="mt-8 space-y-4 text-[14px] leading-relaxed text-text-2">
                {q.data.body.split(/\n{2,}/).map((para, i) => <p key={i} className="whitespace-pre-line">{para}</p>)}
              </div>
            </>
          ) : (
            <div className="mt-8"><Notice tone="amber" title="Henüz yayımlanmadı">{q.data.pending_note}</Notice></div>
          )}
        </article>
      )}
    </div>
  );
}
