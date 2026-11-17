-- Faz 7: kullanıcı etkileşimi — favoriler, bildirimler ve tercihleri, panel düzeni, içerik.

CREATE TABLE user_favorites (
    user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       varchar(12) NOT NULL CHECK (kind IN ('team', 'competition', 'fixture')),
    ref_id     bigint NOT NULL CHECK (ref_id > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, kind, ref_id)
);
CREATE INDEX ix_user_favorites_ref ON user_favorites (kind, ref_id);

-- Uygulama içi bildirimler. dedupe_key aynı olayın aynı kullanıcıya iki kez gitmesini önler.
CREATE TABLE notifications (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category    varchar(16) NOT NULL CHECK (category IN ('system', 'match', 'result', 'subscription', 'security', 'coupon')),
    title       text NOT NULL CHECK (length(title) <= 160),
    body        text NOT NULL CHECK (length(body) <= 600),
    link        text CHECK (link IS NULL OR link ~ '^/[A-Za-z0-9/_?=&.%-]*$'),
    dedupe_key  varchar(120),
    created_at  timestamptz NOT NULL DEFAULT now(),
    read_at     timestamptz
);
CREATE UNIQUE INDEX ux_notifications_dedupe ON notifications (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE INDEX ix_notifications_user ON notifications (user_id, created_at DESC);

-- Kategori başına kanal tercihi. Satır yoksa varsayılan: uygulama içi açık, e-posta yalnızca güvenlik.
CREATE TABLE notification_prefs (
    user_id   uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category  varchar(16) NOT NULL,
    in_app    boolean NOT NULL,
    email     boolean NOT NULL,
    PRIMARY KEY (user_id, category)
);

CREATE TABLE dashboard_layouts (
    user_id    uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    layout     jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- İçerik: SSS ve sayfalar (yasal metinler M-G4 hukuk onayıyla yayımlanır).
CREATE TABLE content_pages (
    slug         varchar(48) PRIMARY KEY CHECK (slug ~ '^[a-z0-9-]{2,48}$'),
    title        text NOT NULL CHECK (length(title) <= 120),
    body         text NOT NULL CHECK (length(body) <= 60000),
    kind         varchar(8) NOT NULL CHECK (kind IN ('legal', 'info')),
    published    boolean NOT NULL DEFAULT false,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    updated_by   uuid REFERENCES users(id),
    published_at timestamptz
);
INSERT INTO content_pages (slug, title, body, kind) VALUES
    ('kullanim-kosullari', 'Kullanım Koşulları', '', 'legal'),
    ('gizlilik', 'Gizlilik ve KVKK Aydınlatma Metni', '', 'legal'),
    ('mesafeli-satis', 'Mesafeli Satış Sözleşmesi', '', 'legal'),
    ('on-bilgilendirme', 'Ön Bilgilendirme Formu', '', 'legal'),
    ('cerezler', 'Çerez Politikası', '', 'legal');

CREATE TABLE faq_items (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    question   text NOT NULL CHECK (length(question) BETWEEN 5 AND 200),
    answer     text NOT NULL CHECK (length(answer) BETWEEN 5 AND 2000),
    sort       integer NOT NULL DEFAULT 0,
    published  boolean NOT NULL DEFAULT true,
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO faq_items (question, answer, sort) VALUES
    ('Tahminler kazanç garantisi veriyor mu?', 'Hayır. Olasılıklar istatistiksel tahmindir; en iyi model bile sık sık yanılır. Platform gerçek para ile bahis yapmaz ve aracılık etmez.', 1),
    ('Model neden bazı maçlarda tahmin vermiyor?', 'Takım geçmişi yetersizse, veri eskiyse, modeller birbirinden çok farklı düşünüyorsa veya belirsizlik çok genişse tahmin yayımlanmaz ve nedeni gösterilir.', 2),
    ('Model performansını nereden görebilirim?', 'Model Şeffaflığı sayfasında; yalnızca maçtan önce yayımlanmış ve sonuçlanmış tahminlerden hesaplanan Brier skoru, log loss ve kalibrasyon grafiği yer alır.', 3),
    ('Verileriniz nereden geliyor?', 'Lisanslı futbol veri sağlayıcılarından. Her maç sayfasında kaynak ve son güncelleme zamanı yazar.', 4),
    ('Sanal portföy gerçek para mı?', 'Hayır. Sanal birim (SB) gerçek para değildir; yatırılamaz, çekilemez ve transfer edilemez. Yalnızca stratejilerin simülasyonu içindir.', 5);
