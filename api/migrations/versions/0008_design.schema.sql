-- Faz 8: tasarım sistemleri ve Design Studio sürümleri.
-- Yayımlanmış/arşivlenmiş sürümün yapılandırması değiştirilemez (geçmiş korunur); geri alma, eski
-- yapılandırmayı yeni sürüm olarak yayımlar. Tasarım başına tek yayımlanmış ve tek açık taslak.
CREATE TABLE design_versions (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    design_key    varchar(32) NOT NULL CHECK (design_key ~ '^[a-z0-9-]{3,32}$'),
    version       integer NOT NULL CHECK (version >= 1),
    status        varchar(10) NOT NULL CHECK (status IN ('draft', 'published', 'archived', 'discarded')),
    config        jsonb NOT NULL,
    note          text CHECK (length(note) <= 300),
    based_on      bigint REFERENCES design_versions(id),
    created_at    timestamptz NOT NULL DEFAULT now(),
    created_by    uuid REFERENCES users(id),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    published_at  timestamptz,
    published_by  uuid REFERENCES users(id),
    UNIQUE (design_key, version),
    CHECK ((status IN ('published', 'archived')) = (published_at IS NOT NULL))
);
CREATE UNIQUE INDEX ux_design_published ON design_versions (design_key) WHERE status = 'published';
CREATE UNIQUE INDEX ux_design_open_draft ON design_versions (design_key) WHERE status = 'draft';

CREATE FUNCTION design_versions_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'design_versions silinemez' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF (NEW.id, NEW.design_key, NEW.version, NEW.created_at, NEW.created_by, NEW.based_on)
       IS DISTINCT FROM (OLD.id, OLD.design_key, OLD.version, OLD.created_at, OLD.created_by, OLD.based_on) THEN
        RAISE EXCEPTION 'Sürüm kimliği değiştirilemez' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF OLD.status = 'draft' THEN
        IF NEW.status NOT IN ('draft', 'published', 'discarded') THEN
            RAISE EXCEPTION 'Geçersiz durum geçişi' USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END IF;
    -- Yayımlanmış/arşivlenmiş/atılmış: içerik dondurulmuş; yalnızca published → archived.
    IF NEW.config IS DISTINCT FROM OLD.config OR NEW.note IS DISTINCT FROM OLD.note
       OR NEW.published_at IS DISTINCT FROM OLD.published_at OR NEW.published_by IS DISTINCT FROM OLD.published_by
       OR NOT (NEW.status = OLD.status OR (OLD.status = 'published' AND NEW.status = 'archived')) THEN
        RAISE EXCEPTION 'Yayımlanmış tasarım sürümü değiştirilemez' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER trg_design_versions_guard BEFORE UPDATE OR DELETE ON design_versions
    FOR EACH ROW EXECUTE FUNCTION design_versions_guard();

CREATE TABLE design_settings (
    id             smallint PRIMARY KEY CHECK (id = 1),
    default_design varchar(32) NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    updated_by     uuid REFERENCES users(id)
);
