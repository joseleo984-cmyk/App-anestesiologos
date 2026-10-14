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


-- Varios anestesiólogos: administración de cuentas y cierre de sesiones
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS es_admin BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS debe_cambiar_clave BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS version_sesion INTEGER NOT NULL DEFAULT 0;
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS clave_env_aplicada CHAR(64);

-- El mismo archivo puede subirlo cada anestesiólogo (antes era único para todos)
ALTER TABLE documento_fuente DROP CONSTRAINT IF EXISTS documento_fuente_hash_sha256_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_documento_anest_hash ON documento_fuente (anestesiologo_id, hash_sha256);

-- ---------------------------------------------------------------------
-- 11. Páginas de un documento (una orden puede llegar en varias fotos)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documento_pagina (
    documento_id       BIGINT  NOT NULL REFERENCES documento_fuente(documento_id) ON DELETE CASCADE,
    numero             INTEGER NOT NULL CHECK (numero >= 1),
    url_archivo        TEXT    NOT NULL,
    tipo_archivo       VARCHAR(10) NOT NULL CHECK (tipo_archivo IN ('IMAGEN','PDF')),
    PRIMARY KEY (documento_id, numero)
);

-- ---------------------------------------------------------------------
-- 12. Número de la orden o autorización (para la relación de órdenes)
-- ---------------------------------------------------------------------
ALTER TABLE cirugia ADD COLUMN IF NOT EXISTS numero_orden VARCHAR(100);

-- ---------------------------------------------------------------------
-- 13. Finanzas personales de cada anestesiólogo (solo las ve él mismo)
-- ---------------------------------------------------------------------
-- Volante de pago de AP, uno por mes: es el ingreso real del mes
CREATE TABLE IF NOT EXISTS volante_pago (
    volante_id         BIGSERIAL PRIMARY KEY,
    anestesiologo_id   BIGINT NOT NULL REFERENCES anestesiologo(anestesiologo_id) ON DELETE CASCADE,
    periodo            DATE NOT NULL,                  -- primer día del mes liquidado
    neto               NUMERIC(14,2) NOT NULL,         -- neto del volante (ya con retención descontada)
    probienestar       NUMERIC(14,2) NOT NULL DEFAULT 0,
    datos_extraidos    JSONB,
    subido_en          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (anestesiologo_id, periodo)
);

-- Gastos mensuales e ingresos adicionales (arriendos, consulta particular, otro empleo…)
CREATE TABLE IF NOT EXISTS fin_partida (
    partida_id         BIGSERIAL PRIMARY KEY,
    anestesiologo_id   BIGINT NOT NULL REFERENCES anestesiologo(anestesiologo_id) ON DELETE CASCADE,
    clase              VARCHAR(10) NOT NULL CHECK (clase IN ('GASTO', 'INGRESO')),
    categoria          VARCHAR(20) NOT NULL,
    nombre             VARCHAR(120) NOT NULL,
    valor_mensual      NUMERIC(14,2) NOT NULL CHECK (valor_mensual >= 0),
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_partida_anest ON fin_partida (anestesiologo_id);

-- Metas de ahorro: fondo de emergencias, viajes, carro, casa…
CREATE TABLE IF NOT EXISTS fin_meta (
    meta_id            BIGSERIAL PRIMARY KEY,
    anestesiologo_id   BIGINT NOT NULL REFERENCES anestesiologo(anestesiologo_id) ON DELETE CASCADE,
    tipo               VARCHAR(12) NOT NULL,
    nombre             VARCHAR(120) NOT NULL,
    valor_objetivo     NUMERIC(14,2) NOT NULL CHECK (valor_objetivo > 0),
    ahorrado           NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (ahorrado >= 0),
    fecha_objetivo     DATE,
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_meta_anest ON fin_meta (anestesiologo_id);

-- 14. Créditos: saldo y tasa efectiva anual de las cuotas de deudas
ALTER TABLE fin_partida ADD COLUMN IF NOT EXISTS saldo NUMERIC(14,2);
ALTER TABLE fin_partida ADD COLUMN IF NOT EXISTS tasa_ea NUMERIC(6,2);

-- 15. Compromiso de ahorro mensual por meta, y lo que realmente se gasta y se aporta cada mes
ALTER TABLE fin_meta ADD COLUMN IF NOT EXISTS compromiso_mensual NUMERIC(14,2);
ALTER TABLE fin_meta ADD COLUMN IF NOT EXISTS comprometido_en DATE;
CREATE TABLE IF NOT EXISTS fin_movimiento (
    movimiento_id      BIGSERIAL PRIMARY KEY,
    anestesiologo_id   BIGINT NOT NULL REFERENCES anestesiologo(anestesiologo_id) ON DELETE CASCADE,
    fecha              DATE NOT NULL,
    clase              VARCHAR(10) NOT NULL CHECK (clase IN ('GASTO', 'APORTE')),
    categoria          VARCHAR(20),                    -- gastos: la categoría del presupuesto
    meta_id            BIGINT REFERENCES fin_meta(meta_id) ON DELETE CASCADE,  -- aportes: la meta
    descripcion        VARCHAR(160),
    valor              NUMERIC(14,2) NOT NULL CHECK (valor > 0),
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((clase = 'GASTO' AND categoria IS NOT NULL) OR (clase = 'APORTE' AND meta_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_fin_mov_anest_fecha ON fin_movimiento (anestesiologo_id, fecha);

-- 16. Extractos bancarios: cuentas y tarjetas, importaciones leídas por partes y reglas de categoría aprendidas
CREATE TABLE IF NOT EXISTS fin_cuenta (
    cuenta_id          BIGSERIAL PRIMARY KEY,
    anestesiologo_id   BIGINT NOT NULL REFERENCES anestesiologo(anestesiologo_id) ON DELETE CASCADE,
    banco              VARCHAR(60) NOT NULL,
    tipo               VARCHAR(20) NOT NULL CHECK (tipo IN ('TARJETA_CREDITO', 'CUENTA_AHORROS', 'CUENTA_CORRIENTE',
                                                            'CREDITO', 'OTRO')),
    ultimos_digitos    VARCHAR(4),
    nombre             VARCHAR(80),
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_cuenta_anest ON fin_cuenta (anestesiologo_id);
CREATE TABLE IF NOT EXISTS fin_importacion (
    importacion_id     BIGSERIAL PRIMARY KEY,
    anestesiologo_id   BIGINT NOT NULL REFERENCES anestesiologo(anestesiologo_id) ON DELETE CASCADE,
    estado             VARCHAR(12) NOT NULL DEFAULT 'PROCESANDO'
                       CHECK (estado IN ('PROCESANDO', 'LISTO', 'ERROR', 'CONFIRMADA')),
    nombre_archivo     VARCHAR(200),
    partes_total       INTEGER NOT NULL DEFAULT 0,
    partes_leidas      INTEGER NOT NULL DEFAULT 0,
    paginas_total      INTEGER NOT NULL DEFAULT 0,
    resultado          JSONB,
    error              TEXT,
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_importacion_anest ON fin_importacion (anestesiologo_id);
CREATE TABLE IF NOT EXISTS fin_regla_categoria (
    anestesiologo_id   BIGINT NOT NULL REFERENCES anestesiologo(anestesiologo_id) ON DELETE CASCADE,
    clave              VARCHAR(80) NOT NULL,           -- comercio normalizado (ej. "EXITO", "TERPEL")
    categoria          VARCHAR(20),                    -- null: no es un gasto (se desmarca al importar)
    actualizado_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (anestesiologo_id, clave)
);
ALTER TABLE fin_movimiento ADD COLUMN IF NOT EXISTS cuenta_id BIGINT REFERENCES fin_cuenta(cuenta_id) ON DELETE SET NULL;
ALTER TABLE fin_movimiento ADD COLUMN IF NOT EXISTS huella VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fin_mov_huella ON fin_movimiento (anestesiologo_id, huella) WHERE huella IS NOT NULL;

-- 17. Tipo de documento CN (certificado de nacido vivo)
ALTER TABLE paciente DROP CONSTRAINT IF EXISTS paciente_tipo_documento_check;
ALTER TABLE paciente ADD CONSTRAINT paciente_tipo_documento_check
    CHECK (tipo_documento IN ('CC','TI','CE','RC','PA','PPT','CN','MS','AS'));
