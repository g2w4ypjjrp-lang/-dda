import Link from "next/link";

export default function NotFound() {
  return (
    <main className="grid min-h-dvh place-items-center px-4">
      <div className="text-center">
        <div className="eyebrow mb-3">404</div>
        <h1 className="text-2xl font-semibold">Sayfa bulunamadı</h1>
        <Link href="/" className="mt-6 inline-flex h-10 items-center rounded-ctl bg-gold px-4 text-sm font-semibold text-accent-text">Ana sayfa</Link>
      </div>
    </main>
  );
}
