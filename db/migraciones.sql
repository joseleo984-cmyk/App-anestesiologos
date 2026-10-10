-- =====================================================================
-- Actualizaciones para bases creadas con versiones anteriores de schema.sql.
-- Se ejecuta en cada arranque: cada instrucción es idempotente.
-- =====================================================================
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS password_hash TEXT;

CREATE TABLE IF NOT EXISTS cirujano (
    cirujano_id        BIGSERIAL PRIMARY KEY,
    nombre             VARCHAR(150) NOT NULL UNIQUE,
    especialidad       VARCHAR(100)
);

ALTER TABLE cirugia ADD COLUMN IF NOT EXISTS cirujano_id BIGINT REFERENCES cirujano(cirujano_id);
ALTER TABLE cirugia ADD COLUMN IF NOT EXISTS valor_honorarios NUMERIC(14,2) CHECK (valor_honorarios >= 0);
ALTER TABLE cirugia ADD COLUMN IF NOT EXISTS fecha_pago DATE;
ALTER TABLE cirugia ADD COLUMN IF NOT EXISTS observaciones TEXT;
CREATE INDEX IF NOT EXISTS idx_cirugia_cirujano ON cirugia (cirujano_id);

-- Estado PAGADA (no existía al principio)
ALTER TABLE cirugia DROP CONSTRAINT IF EXISTS cirugia_estado_check;
ALTER TABLE cirugia ADD CONSTRAINT cirugia_estado_check
    CHECK (estado IN ('PROGRAMADA','REALIZADA','CANCELADA','FACTURADA','PAGADA'));
