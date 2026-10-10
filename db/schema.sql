-- =====================================================================
-- App Anestesiólogos - Esquema de base de datos (PostgreSQL)
-- Fuente de datos: extracción automática desde foto o PDF de la orden
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Anestesiólogo (usuario dueño de los registros)
-- ---------------------------------------------------------------------
CREATE TABLE anestesiologo (
    anestesiologo_id   BIGSERIAL PRIMARY KEY,
    nombre             VARCHAR(150) NOT NULL,
    registro_medico    VARCHAR(30)  UNIQUE,
    email              VARCHAR(150) NOT NULL UNIQUE,
    password_hash      TEXT,                       -- scrypt; NULL = no puede iniciar sesión
    es_admin           BOOLEAN NOT NULL DEFAULT FALSE,  -- administra las cuentas de los demás
    activo             BOOLEAN NOT NULL DEFAULT TRUE,
    debe_cambiar_clave BOOLEAN NOT NULL DEFAULT FALSE,  -- clave temporal: cambiarla al entrar
    version_sesion     INTEGER NOT NULL DEFAULT 0,      -- al subirla se cierran sus sesiones abiertas
    clave_env_aplicada CHAR(64),                        -- huella de ADMIN_PASSWORD ya aplicada
    creado_en          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 2. Paciente
-- ---------------------------------------------------------------------
CREATE TABLE paciente (
    paciente_id        BIGSERIAL PRIMARY KEY,
    tipo_documento     VARCHAR(5)   NOT NULL DEFAULT 'CC'
                       CHECK (tipo_documento IN ('CC','TI','CE','RC','PA','PPT','MS','AS')),
    numero_documento   VARCHAR(20)  NOT NULL,
    nombres            VARCHAR(100) NOT NULL,
    apellidos          VARCHAR(100) NOT NULL,
    creado_en          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (tipo_documento, numero_documento)
);

-- ---------------------------------------------------------------------
-- 3. Aseguradora (EPS, medicina prepagada o compañía de pólizas)
-- ---------------------------------------------------------------------
CREATE TABLE aseguradora (
    aseguradora_id     BIGSERIAL PRIMARY KEY,
    nombre             VARCHAR(150) NOT NULL,
    nit                VARCHAR(20)  UNIQUE,
    tipo               VARCHAR(10)  NOT NULL
                       CHECK (tipo IN ('EPS','PREPAGADA','POLIZA')),
    UNIQUE (nombre, tipo)
);

-- ---------------------------------------------------------------------
-- 4. Cobertura: relación paciente <-> aseguradora
--    (un paciente puede tener EPS + prepagada + póliza al mismo tiempo)
-- ---------------------------------------------------------------------
CREATE TABLE cobertura (
    cobertura_id       BIGSERIAL PRIMARY KEY,
    paciente_id        BIGINT NOT NULL REFERENCES paciente(paciente_id) ON DELETE CASCADE,
    aseguradora_id     BIGINT NOT NULL REFERENCES aseguradora(aseguradora_id),
    numero_poliza      VARCHAR(50),          -- nº póliza / contrato / afiliación
    plan               VARCHAR(100),         -- ej. "Plan Oro", "Contributivo"
    activa             BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (paciente_id, aseguradora_id, numero_poliza)
);

-- ---------------------------------------------------------------------
-- 5. Clínica donde se realiza el procedimiento
-- ---------------------------------------------------------------------
CREATE TABLE clinica (
    clinica_id         BIGSERIAL PRIMARY KEY,
    nombre             VARCHAR(150) NOT NULL,
    nit                VARCHAR(20)  UNIQUE,
    ciudad             VARCHAR(80),
    UNIQUE (nombre, ciudad)
);

-- ---------------------------------------------------------------------
-- 6. Catálogo de procedimientos (códigos CUPS)
-- ---------------------------------------------------------------------
CREATE TABLE procedimiento (
    codigo             VARCHAR(10)  PRIMARY KEY,   -- código CUPS, ej. '470100'
    nombre             VARCHAR(255) NOT NULL
);

-- ---------------------------------------------------------------------
-- 7. Documento fuente (foto o PDF subido) + resultado de la extracción
-- ---------------------------------------------------------------------
CREATE TABLE documento_fuente (
    documento_id       BIGSERIAL PRIMARY KEY,
    anestesiologo_id   BIGINT NOT NULL REFERENCES anestesiologo(anestesiologo_id),
    tipo_archivo       VARCHAR(10) NOT NULL CHECK (tipo_archivo IN ('IMAGEN','PDF')),
    url_archivo        TEXT        NOT NULL,       -- ruta en el storage
    hash_sha256        CHAR(64),                   -- evita que un anestesiólogo cargue dos veces el mismo archivo
    estado             VARCHAR(15) NOT NULL DEFAULT 'PENDIENTE'
                       CHECK (estado IN ('PENDIENTE','EXTRAIDO','VALIDADO','ERROR')),
    datos_extraidos    JSONB,                      -- JSON crudo devuelto por la IA
    confianza          NUMERIC(4,3),               -- 0.000 - 1.000
    subido_en          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 7b. Cirujano (para saber con quién opera más y cuánto genera cada uno)
-- ---------------------------------------------------------------------
CREATE TABLE cirujano (
    cirujano_id        BIGSERIAL PRIMARY KEY,
    nombre             VARCHAR(150) NOT NULL UNIQUE,   -- en mayúsculas, sin espacios dobles
    especialidad       VARCHAR(100)
);

-- ---------------------------------------------------------------------
-- 8. Cirugía / evento quirúrgico  (TABLA CENTRAL)
--    Une paciente + cobertura + clínica + anestesiólogo + documento
-- ---------------------------------------------------------------------
CREATE TABLE cirugia (
    cirugia_id         BIGSERIAL PRIMARY KEY,
    paciente_id        BIGINT NOT NULL REFERENCES paciente(paciente_id),
    cobertura_id       BIGINT          REFERENCES cobertura(cobertura_id),  -- NULL = particular
    clinica_id         BIGINT NOT NULL REFERENCES clinica(clinica_id),
    anestesiologo_id   BIGINT NOT NULL REFERENCES anestesiologo(anestesiologo_id),
    documento_id       BIGINT          REFERENCES documento_fuente(documento_id),
    cirujano_id        BIGINT          REFERENCES cirujano(cirujano_id),
    fecha_procedimiento DATE   NOT NULL,
    estado             VARCHAR(15) NOT NULL DEFAULT 'PROGRAMADA'
                       CONSTRAINT cirugia_estado_check
                       CHECK (estado IN ('PROGRAMADA','REALIZADA','CANCELADA','FACTURADA','PAGADA')),
    valor_honorarios   NUMERIC(14,2)   CHECK (valor_honorarios >= 0),   -- lo que se cobra al anestesiólogo
    fecha_pago         DATE,
    observaciones      TEXT,
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 9. Procedimientos de cada cirugía (una orden puede traer varios códigos)
-- ---------------------------------------------------------------------
CREATE TABLE cirugia_procedimiento (
    cirugia_id         BIGINT      NOT NULL REFERENCES cirugia(cirugia_id) ON DELETE CASCADE,
    codigo             VARCHAR(10) NOT NULL REFERENCES procedimiento(codigo),
    es_principal       BOOLEAN     NOT NULL DEFAULT FALSE,
    PRIMARY KEY (cirugia_id, codigo)
);

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

-- Índices para las consultas más frecuentes
-- Cada anestesiólogo puede subir su propia copia de un archivo que otro también tenga
CREATE UNIQUE INDEX idx_documento_anest_hash ON documento_fuente (anestesiologo_id, hash_sha256);
CREATE INDEX idx_cirugia_fecha        ON cirugia (anestesiologo_id, fecha_procedimiento);
CREATE INDEX idx_cirugia_paciente     ON cirugia (paciente_id);
CREATE INDEX idx_cirugia_clinica      ON cirugia (clinica_id);
CREATE INDEX idx_cirugia_cirujano     ON cirugia (cirujano_id);
CREATE INDEX idx_cobertura_paciente   ON cobertura (paciente_id);
CREATE INDEX idx_procedimiento_nombre ON procedimiento (nombre);
