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

-- ---------------------------------------------------------------------
-- 10. Reportes de pago (relación de pacientes pagados que entrega la
--     asociación o el pagador) y su detalle, cruzado con las cirugías
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reporte_pago (
    reporte_id         BIGSERIAL PRIMARY KEY,
    anestesiologo_id   BIGINT NOT NULL REFERENCES anestesiologo(anestesiologo_id),
    pagador            VARCHAR(200),                 -- ej. la asociación que paga
    fecha_proceso      DATE,                         -- fecha del pago / proceso
    periodo_desde      DATE,
    periodo_hasta      DATE,
    total_neto         NUMERIC(14,2),
    url_archivo        TEXT NOT NULL,
    hash_sha256        CHAR(64) NOT NULL,
    estado             VARCHAR(10) NOT NULL DEFAULT 'LEIDO'
                       CHECK (estado IN ('LEIDO','APLICADO')),
    datos_extraidos    JSONB,
    subido_en          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (anestesiologo_id, hash_sha256)
);

CREATE TABLE IF NOT EXISTS pago_detalle (
    detalle_id         BIGSERIAL PRIMARY KEY,
    reporte_id         BIGINT NOT NULL REFERENCES reporte_pago(reporte_id) ON DELETE CASCADE,
    empresa            VARCHAR(200),                 -- aseguradora / IPS que pagó
    documento_paciente VARCHAR(30),
    paciente           VARCHAR(200),
    fecha_servicio     DATE,
    factura            VARCHAR(50),
    autorizacion       VARCHAR(80),
    total              NUMERIC(14,2),
    glosas             NUMERIC(14,2) NOT NULL DEFAULT 0,
    descuentos         NUMERIC(14,2) NOT NULL DEFAULT 0,
    neto               NUMERIC(14,2),
    es_paciente        BOOLEAN NOT NULL DEFAULT TRUE,   -- FALSE = otro concepto (ej. honorarios globales)
    cirugia_id         BIGINT REFERENCES cirugia(cirugia_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_pago_detalle_reporte ON pago_detalle (reporte_id);
CREATE INDEX IF NOT EXISTS idx_pago_detalle_cirugia ON pago_detalle (cirugia_id);
