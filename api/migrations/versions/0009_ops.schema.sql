-- Faz 9: yönetim operasyonları — özellik bayrakları, Action Center onayları, kayıtlı filtreler.

CREATE TABLE feature_flags (
    key          varchar(48) PRIMARY KEY CHECK (key ~ '^[a-z_]{3,48}$'),
    enabled      boolean NOT NULL,
    description  text NOT NULL,
    message      text CHECK (length(message) <= 300),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    updated_by   uuid REFERENCES users(id)
);
INSERT INTO feature_flags (key, enabled, description) VALUES
    ('registration_open', true, 'Yeni üye kaydı açık'),
    ('coupons_enabled', true, 'Kupon oluşturucu ve kupon kaydı açık'),
    ('virtual_enabled', true, 'Sanal portföy: yeni hesap ve sanal bilet açılabilir'),
    ('sales_enabled', true, 'Ödeme sayfası (satın alma) açık'),
    ('maintenance_notice', false, 'Sitede bakım/duyuru şeridi göster');

-- Action Center'da "görüldü" işaretlenen uyarılar. Anahtar uyarının kimliğini içerir
-- (ör. sync_run:123); aynı sorun yeniden oluşursa yeni anahtarla tekrar görünür.
CREATE TABLE admin_action_acks (
    issue_key  varchar(120) PRIMARY KEY,
    acked_by   uuid NOT NULL REFERENCES users(id),
    acked_at   timestamptz NOT NULL,
    note       text CHECK (length(note) <= 300)
);

CREATE TABLE admin_saved_filters (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(id),
    entity      varchar(32) NOT NULL,
    name        varchar(80) NOT NULL,
    params      jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, entity, name)
);
