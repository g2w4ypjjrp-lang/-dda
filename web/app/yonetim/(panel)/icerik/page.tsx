"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Megaphone, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { PageTitle, can, useAdmin } from "@/components/admin";
import { Badge, Button, Card, CardHeader, ErrorState, FormError, Input, Notice, Skeleton } from "@/components/ui";
import { api, del, post, put } from "@/lib/api";
import { ago } from "@/lib/format";

interface Page { slug: string; title: string; body: string; kind: "legal" | "info"; published: boolean; updated_at: string; published_at: string | null }
interface Faq { id: number; question: string; answer: string; sort: number; published: boolean }

function PageEditor({ page }: { page: Page }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState(page.title);
  const [body, setBody] = useState(page.body);
  const save = useMutation({
    mutationFn: (published: boolean) => put(`/admin/v1/content/pages/${page.slug}`, { title, body, published }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "content"] }),
  });
  return (
    <details className="group px-5 py-4" data-testid={`page-${page.slug}`}>
      <summary className="flex cursor-pointer list-none items-center gap-3 text-[13.5px]">
        <span className="font-medium">{page.title}</span>
        <Badge tone={page.published ? "teal" : "amber"}>{page.published ? "Yayında" : "Taslak"}</Badge>
        <span className="ml-auto text-[11.5px] text-muted">/yasal/{page.slug} · {ago(page.updated_at)}</span>
      </summary>
      <div className="mt-4 space-y-3">
        {page.kind === "legal" && <Notice tone="amber" title="Hukuki inceleme (M-G4)">Yasal metinler hukukçu onayından sonra yayımlanmalıdır. Yayımlanana kadar sitede "hukuki inceleme sürecinde" uyarısı görünür.</Notice>}
        <Input label="Başlık" name={`title-${page.slug}`} value={title} onChange={(e) => setTitle(e.target.value)} />
        <label className="block text-[12.5px]">
          <span className="mb-1.5 block font-medium text-text-2">Metin (düz yazı; paragrafları boş satırla ayırın)</span>
          <textarea aria-label={`${page.title} metni`} value={body} onChange={(e) => setBody(e.target.value)} rows={12} className="w-full rounded-ctl border border-line-strong bg-bg-elevated p-3 font-mono text-[12.5px] leading-relaxed" />
        </label>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" loading={save.isPending && save.variables === false} onClick={() => save.mutate(false)}>Taslak olarak kaydet</Button>
          <Button size="sm" loading={save.isPending && save.variables === true} disabled={body.trim().length < 50}
            onClick={() => { if (window.confirm(`"${title}" yayımlansın mı?${page.kind === "legal" ? " Hukuki onay alındığından emin olun." : ""}`)) save.mutate(true); }}>Yayımla</Button>
        </div>
        <FormError error={save.error} />
      </div>
    </details>
  );
}

function FaqRow({ f }: { f: Faq }) {
  const qc = useQueryClient();
  const [q, setQ] = useState(f.question);
  const [a, setA] = useState(f.answer);
  const refresh = () => qc.invalidateQueries({ queryKey: ["admin", "content"] });
  const save = useMutation({ mutationFn: (published: boolean) => put(`/admin/v1/content/faq/${f.id}`, { question: q, answer: a, sort: f.sort, published }), onSuccess: refresh });
  const remove = useMutation({ mutationFn: () => del(`/admin/v1/content/faq/${f.id}`), onSuccess: refresh });
  return (
    <div className="space-y-2 px-5 py-4">
      <div className="flex items-center gap-2"><Badge tone={f.published ? "teal" : "neutral"}>{f.published ? "Yayında" : "Gizli"}</Badge><span className="text-[11.5px] text-muted">Sıra {f.sort}</span></div>
      <Input label="Soru" name={`q-${f.id}`} value={q} onChange={(e) => setQ(e.target.value)} />
      <textarea aria-label="Yanıt" value={a} onChange={(e) => setA(e.target.value)} rows={3} className="w-full rounded-ctl border border-line-strong bg-bg-elevated p-2.5 text-[13px]" />
      <div className="flex gap-2">
        <Button size="sm" variant="secondary" loading={save.isPending} onClick={() => save.mutate(f.published)}>Kaydet</Button>
        <Button size="sm" variant="ghost" onClick={() => save.mutate(!f.published)}>{f.published ? "Gizle" : "Yayımla"}</Button>
        <Button size="sm" variant="ghost" loading={remove.isPending} onClick={() => { if (window.confirm("Soru silinsin mi?")) remove.mutate(); }}><Trash2 className="size-3.5" aria-hidden />Sil</Button>
      </div>
      <FormError error={save.error ?? remove.error} />
    </div>
  );
}

function Broadcast() {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [link, setLink] = useState("");
  const send = useMutation({ mutationFn: () => post<{ recipients: number }>("/admin/v1/notifications/broadcast", { title, body, link: link || null, confirm: true }) });
  return (
    <Card>
      <CardHeader eyebrow="Bildirim yönetimi" title="Sistem duyurusu gönder" />
      <form className="space-y-3 p-5" onSubmit={(e) => { e.preventDefault(); if (window.confirm("Duyuru tüm aktif kullanıcılara uygulama içi bildirim olarak gönderilsin mi?")) send.mutate(); }}>
        <Input label="Başlık" name="b-title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <textarea aria-label="Duyuru metni" placeholder="Duyuru metni" value={body} onChange={(e) => setBody(e.target.value)} rows={3} className="w-full rounded-ctl border border-line-strong bg-bg-elevated p-2.5 text-[13px]" />
        <Input label="Bağlantı (isteğe bağlı, site içi yol: /maclar)" name="b-link" value={link} onChange={(e) => setLink(e.target.value)} />
        <Button type="submit" loading={send.isPending} disabled={title.trim().length < 3 || body.trim().length < 3}><Megaphone className="size-4" aria-hidden />Gönder</Button>
        {send.data && <p className="text-[12.5px] text-teal">{send.data.recipients} kullanıcıya gönderildi.</p>}
        <FormError error={send.error} />
        <p className="text-[11.5px] text-muted">Sistem duyurularını kapatmış kullanıcılara gönderilmez. Push bildirimi ve e-posta duyurusu yok (M-G6).</p>
      </form>
    </Card>
  );
}

export default function ContentAdmin() {
  const me = useAdmin();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "content"], queryFn: () => api<{ pages: Page[]; faq: Faq[] }>("/admin/v1/content"), enabled: can(me, "content.manage") });
  const add = useMutation({
    mutationFn: () => post("/admin/v1/content/faq", { question: "Yeni soru?", answer: "Yanıtı buraya yazın.", sort: (q.data?.faq.length ?? 0) + 1, published: false }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "content"] }),
  });
  return (
    <div className="space-y-6">
      <PageTitle eyebrow="Platform" title="İçerik & Duyurular" />
      {can(me, "notifications.manage") && <Broadcast />}
      {can(me, "content.manage") && (q.isLoading ? <Skeleton className="h-64" /> : q.error || !q.data ? <Card><ErrorState error={q.error} /></Card> : (
        <>
          <Card>
            <CardHeader eyebrow="Sayfalar" title="Yasal ve bilgi sayfaları" />
            <div className="mt-3 divide-y divide-line border-t border-line">{q.data.pages.map((p) => <PageEditor key={`${p.slug}-${p.updated_at}`} page={p} />)}</div>
          </Card>
          <Card>
            <CardHeader eyebrow="SSS" title="Sık sorulan sorular" action={<Button size="sm" variant="secondary" loading={add.isPending} onClick={() => add.mutate()}><Plus className="size-3.5" aria-hidden />Soru ekle</Button>} />
            <div className="mt-3 divide-y divide-line border-t border-line">{q.data.faq.map((f) => <FaqRow key={`${f.id}-${f.published}`} f={f} />)}</div>
          </Card>
        </>
      ))}
    </div>
  );
}
