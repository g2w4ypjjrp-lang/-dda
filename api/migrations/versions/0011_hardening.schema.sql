-- Faz 10: dört göz onayı (kritik işlemler) ve yedek kayıtları.

CREATE TABLE approval_requests (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    action         varchar(48) NOT NULL,
    permission     varchar(48) NOT NULL,
    target         varchar(120) NOT NULL,
    summary        text NOT NULL CHECK (length(summary) <= 300),
    payload        jsonb NOT NULL,
    status         varchar(10) NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'executed', 'rejected', 'cancelled', 'expired', 'failed')),
    requested_by   uuid NOT NULL REFERENCES users(id),
    requested_at   timestamptz NOT NULL,
    expires_at     timestamptz NOT NULL,
    decided_by     uuid REFERENCES users(id),
    decided_at     timestamptz,
    decision_note  text CHECK (length(decision_note) <= 300),
    result         jsonb,
    -- İkinci kişi kuralı veritabanında da: onaylayan/reddeden talep sahibi olamaz (iptal hariç).
    CHECK (decided_by IS NULL OR status = 'cancelled' OR decided_by <> requested_by),
    CHECK ((status = 'pending') = (decided_at IS NULL))
);
CREATE INDEX ix_approval_requests_pending ON approval_requests (status, requested_at) WHERE status = 'pending';
-- Aynı hedefe aynı işlem için tek bekleyen talep.
CREATE UNIQUE INDEX ux_approval_requests_open ON approval_requests (action, target) WHERE status = 'pending';

CREATE FUNCTION approval_requests_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'approval_requests silinemez' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF OLD.status <> 'pending' THEN
        RAISE EXCEPTION 'Karara bağlanmış onay talebi değiştirilemez' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF (NEW.id, NEW.action, NEW.permission, NEW.target, NEW.summary, NEW.payload, NEW.requested_by, NEW.requested_at, NEW.expires_at)
       IS DISTINCT FROM
       (OLD.id, OLD.action, OLD.permission, OLD.target, OLD.summary, OLD.payload, OLD.requested_by, OLD.requested_at, OLD.expires_at) THEN
        RAISE EXCEPTION 'Onay talebinin içeriği değiştirilemez' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER trg_approval_requests_guard BEFORE UPDATE OR DELETE ON approval_requests
    FOR EACH ROW EXECUTE FUNCTION approval_requests_guard();

INSERT INTO feature_flags (key, enabled, description) VALUES
    ('dual_control', false, 'Dört göz: iade, incelemedeki sipariş kararı ve rol atama ikinci yönetici onayı ister');

CREATE TABLE backups (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at   timestamptz NOT NULL,
    file_name    text NOT NULL,
    size_bytes   bigint,
    sha256       char(64),
    status       varchar(8) NOT NULL CHECK (status IN ('ok', 'failed', 'pruned')),
    duration_ms  integer,
    error        text,
    verified_at  timestamptz,
    verify_ok    boolean,
    verify       jsonb,
    trigger      varchar(8) NOT NULL CHECK (trigger IN ('cli', 'schedule'))
);
CREATE INDEX ix_backups_created ON backups (created_at DESC);
