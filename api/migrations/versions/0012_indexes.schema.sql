-- Faz 10: EXPLAIN incelemesi (enable_seqscan=off ile "indeks yolu var mı?" denetimi) bulguları.
-- Not: büyük tablolarda üretimde CONCURRENTLY ile elle oluşturulabilir (docs/calistirma-kilavuzu.md).

-- Giriş uyarısı (engage.notify.login_alert): kullanıcının son 90 gündeki tüm oturumları
-- (iptal edilenler dahil). Mevcut kısmi indeks yalnızca açık oturumları kapsıyordu → tam tarama.
CREATE INDEX ix_user_sessions_user_created ON user_sessions (user_id, created_at);

-- Denetim kaydı listesi yalnızca actor_id ya da target_id ile süzülür ve id'ye göre sıralanır;
-- (actor_type, actor_id, ...) / (target_type, target_id) indeksleri ilk sütun olmadan tüm indeksi tarıyordu.
CREATE INDEX ix_audit_log_actor_id ON audit_log (actor_id, id DESC) WHERE actor_id IS NOT NULL;
CREATE INDEX ix_audit_log_target_id ON audit_log (target_id, id DESC) WHERE target_id IS NOT NULL;
-- Eylem öneki (LIKE 'auth.%'): veritabanı harmanlaması C değilse btree önek araması yapamaz.
CREATE INDEX ix_audit_log_action_prefix ON audit_log (action text_pattern_ops);

-- "Aboneliğiniz bitiyor" taraması: etkin aboneliklerin bitiş tarihi.
CREATE INDEX ix_subscriptions_active_end ON subscriptions (current_period_end) WHERE status = 'active';
