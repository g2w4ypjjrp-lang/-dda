import Link from "next/link";

import { Logo } from "./Logo";

export function SiteFooter() {
  return (
    <footer className="mt-24 border-t border-line pb-24 md:pb-10">
      <div className="mx-auto grid max-w-(--mi-page) gap-10 px-4 py-12 sm:px-6 md:grid-cols-[1.4fr_1fr_1fr]">
        <div>
          <Logo />
          <p className="mt-4 max-w-sm text-[13px] leading-relaxed text-muted">
            Gerçek futbol verisi, açıklanabilir modeller ve şeffaf olasılıklar. Belirsizliği saklamayız;
            yeterli veri yoksa tahmin vermeyiz.
          </p>
        </div>
        <div>
          <div className="eyebrow mb-3">Platform</div>
          <ul className="space-y-2 text-[13px] text-text-2">
            <li><Link href="/maclar" className="hover:text-text">Maç Merkezi</Link></li>
            <li><Link href="/performans" className="hover:text-text">Model Şeffaflığı</Link></li>
            <li><Link href="/paketler" className="hover:text-text">Paketler</Link></li>
            <li><Link href="/sss" className="hover:text-text">Sık sorulan sorular</Link></li>
            <li><Link href="/kayit" className="hover:text-text">Hesap oluştur</Link></li>
          </ul>
        </div>
        <div>
          <div className="eyebrow mb-3">Yasal</div>
          <ul className="space-y-2 text-[13px] text-text-2">
            <li><Link href="/risk" className="hover:text-text">Risk bildirimi</Link></li>
            <li><Link href="/yasal/kullanim-kosullari" className="hover:text-text">Kullanım koşulları</Link></li>
            <li><Link href="/yasal/gizlilik" className="hover:text-text">Gizlilik ve KVKK</Link></li>
            <li><Link href="/yasal/mesafeli-satis" className="hover:text-text">Mesafeli satış sözleşmesi</Link></li>
            <li><Link href="/yasal/cerezler" className="hover:text-text">Çerez politikası</Link></li>
          </ul>
        </div>
      </div>
      <div className="mx-auto max-w-(--mi-page) px-4 sm:px-6">
        <div className="hairline" />
        <p className="py-6 text-[12px] leading-relaxed text-muted">
          Match Intelligence AI bir analiz ve sanal simülasyon platformudur; gerçek para ile bahis işlemi
          yapmaz ve aracılık etmez. Olasılıklar istatistiksel tahmindir, kesin sonuç veya kazanç garantisi
          değildir. 18 yaşından küçükler için değildir.
        </p>
      </div>
    </footer>
  );
}
