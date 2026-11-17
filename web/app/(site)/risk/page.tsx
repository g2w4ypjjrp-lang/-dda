import type { Metadata } from "next";

export const metadata: Metadata = { title: "Risk bildirimi" };

export default function RiskPage() {
  return (
    <article className="mx-auto max-w-2xl py-12 text-[14px] leading-relaxed text-text-2">
      <div className="eyebrow mb-2">Yasal</div>
      <h1 className="text-[28px] font-semibold tracking-tight text-text">Risk bildirimi</h1>
      <p className="mt-6">
        Match Intelligence AI bir futbol veri analizi ve <strong className="text-text">sanal</strong> simülasyon
        platformudur. Gerçek para ile bahis işlemi yapmaz, bahis şirketlerine aracılık etmez ve kullanıcı adına
        işlem gerçekleştirmez.
      </p>
      <p className="mt-4">
        Tüm olasılıklar istatistiksel modellerin çıktısıdır ve hata payı taşır. Hiçbir tahmin kesin sonuç veya
        kazanç garantisi değildir. Geçmiş model performansı gelecekteki sonuçların göstergesi değildir.
      </p>
      <p className="mt-4">
        Sanal bakiye gerçek para değildir; çekilemez, transfer edilemez ve hiçbir ödeme aracı yerine geçmez.
      </p>
      <p className="mt-4">Platform 18 yaşından küçükler için değildir.</p>
      <p className="mt-8 text-[12px] text-muted">Bu metin taslaktır; yayın öncesi hukuk incelemesinden geçecektir.</p>
    </article>
  );
}
