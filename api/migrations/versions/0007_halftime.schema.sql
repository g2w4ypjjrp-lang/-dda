-- İlk yarı modeli: sonuçlandırmada İY skoru ve İY 1X2 olasılık skorları (performans şeffaflığı).
-- Kayıt değiştirilemez kalır (mevcut tetikleyici); sütunlar yalnızca eklenir.
ALTER TABLE ml_prediction_outcomes
    ADD COLUMN ht_home     smallint CHECK (ht_home >= 0),
    ADD COLUMN ht_away     smallint CHECK (ht_away >= 0),
    ADD COLUMN ht_brier    double precision,
    ADD COLUMN ht_log_loss double precision,
    ADD CHECK ((ht_home IS NULL) = (ht_away IS NULL)),
    ADD CHECK (ht_home IS NULL OR (ht_home <= home_goals AND ht_away <= away_goals));
