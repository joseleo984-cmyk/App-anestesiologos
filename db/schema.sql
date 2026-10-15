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
    -- cada anestesiólogo tiene su propia ficha del paciente: lo que escribe uno no cambia lo que ve otro
    anestesiologo_id   BIGINT NOT NULL REFERENCES anestesiologo(anestesiologo_id) ON DELETE CASCADE,
    tipo_documento     VARCHAR(5)   NOT NULL DEFAULT 'CC'
                       CHECK (tipo_documento IN ('CC','TI','CE','RC','PA','PPT','CN','MS','AS')),
    numero_documento   VARCHAR(20)  NOT NULL,
    nombres            VARCHAR(100) NOT NULL,
    apellidos          VARCHAR(100) NOT NULL,
    creado_en          TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS paciente_anestesiologo_documento ON paciente (anestesiologo_id, tipo_documento, numero_documento);

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
    numero_orden       VARCHAR(100),                     -- nº de orden / autorización de la aseguradora
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
    -- PAGOS: reporte de pagos de la asociación. RELACION: relación o liquidación de AP de una clínica que
    -- paga el total de lo entregado (no paciente por paciente); marca las cirugías pagadas pero no es ingreso
    -- aparte (el pago global ya viene en el reporte de pagos)
    tipo               VARCHAR(10) NOT NULL DEFAULT 'PAGOS' CHECK (tipo IN ('PAGOS','RELACION')),
    numero             VARCHAR(50),                  -- nº de la relación / radicado
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
    numero_orden       VARCHAR(100),                 -- en las relaciones de AP
    procedimiento      VARCHAR(300),
    cirugia_id         BIGINT REFERENCES cirugia(cirugia_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_pago_detalle_reporte ON pago_detalle (reporte_id);
CREATE INDEX IF NOT EXISTS idx_pago_detalle_cirugia ON pago_detalle (cirugia_id);

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

-- Índices para las consultas más frecuentes
-- Cada anestesiólogo puede subir su propia copia de un archivo que otro también tenga
CREATE UNIQUE INDEX idx_documento_anest_hash ON documento_fuente (anestesiologo_id, hash_sha256);
CREATE INDEX idx_cirugia_fecha        ON cirugia (anestesiologo_id, fecha_procedimiento);
CREATE INDEX idx_cirugia_paciente     ON cirugia (paciente_id);
CREATE INDEX idx_cirugia_clinica      ON cirugia (clinica_id);
CREATE INDEX idx_cirugia_cirujano     ON cirugia (cirujano_id);
CREATE INDEX idx_cobertura_paciente   ON cobertura (paciente_id);
CREATE INDEX idx_procedimiento_nombre ON procedimiento (nombre);
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
    saldo              NUMERIC(14,2),                  -- créditos: saldo pendiente
    tasa_ea            NUMERIC(6,2),                   -- créditos: tasa efectiva anual (%)
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
    compromiso_mensual NUMERIC(14,2),                  -- lo que se compromete a ahorrar cada mes
    comprometido_en    DATE,
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_meta_anest ON fin_meta (anestesiologo_id);

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

-- Extractos bancarios: cuentas y tarjetas, importaciones leídas por partes y reglas de categoría aprendidas
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

-- Noticias de anestesia: fuentes curadas (RSS o búsqueda de PubMed), noticias resumidas por la IA y lo que cada uno leyó
CREATE TABLE IF NOT EXISTS noticia_fuente (
    fuente_id          BIGSERIAL PRIMARY KEY,
    nombre             VARCHAR(120) NOT NULL,
    tipo               VARCHAR(10) NOT NULL CHECK (tipo IN ('RSS', 'PUBMED')),
    url                VARCHAR(600) NOT NULL,          -- dirección del RSS, o la búsqueda de PubMed
    activa             BOOLEAN NOT NULL DEFAULT TRUE,
    revisada_en        TIMESTAMPTZ,
    ultimo_error       TEXT,
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS noticia (
    noticia_id         BIGSERIAL PRIMARY KEY,
    fuente_id          BIGINT NOT NULL REFERENCES noticia_fuente(fuente_id) ON DELETE CASCADE,
    guid               VARCHAR(600) NOT NULL,
    titulo             TEXT NOT NULL,
    enlace             TEXT,
    publicado_en       TIMESTAMPTZ,
    contenido          TEXT,                           -- resumen original; se borra después de resumir
    estado             VARCHAR(12) NOT NULL DEFAULT 'PENDIENTE' CHECK (estado IN ('PENDIENTE', 'LISTA', 'DESCARTADA')),
    tipo               VARCHAR(12),
    temas              TEXT[] NOT NULL DEFAULT '{}',
    titulo_es          TEXT,
    resumen_es         TEXT,
    -- para la infografía: relevancia (1–5), la cifra principal, cuántos pacientes y la conclusión en una frase
    relevancia         SMALLINT,
    cifra              VARCHAR(40),
    cifra_etiqueta     VARCHAR(160),
    pacientes          INTEGER,
    conclusion         TEXT,
    diseno             VARCHAR(24),                    -- ECA, METAANALISIS, COHORTE…: nivel de evidencia
    poblacion          TEXT,
    intervencion       TEXT,
    comparador         TEXT,
    grupo_a            VARCHAR(120),                   -- comparación en porcentajes (de cada 100 pacientes)
    valor_a            NUMERIC(6,2),
    grupo_b            VARCHAR(120),
    valor_b            NUMERIC(6,2),
    evento             VARCHAR(160),
    intentos           INTEGER NOT NULL DEFAULT 0,
    listo_en           TIMESTAMPTZ,
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fuente_id, guid)
);
CREATE INDEX IF NOT EXISTS idx_noticia_lista ON noticia (estado, listo_en);
CREATE TABLE IF NOT EXISTS noticia_lectura (
    anestesiologo_id   BIGINT NOT NULL REFERENCES anestesiologo(anestesiologo_id) ON DELETE CASCADE,
    noticia_id         BIGINT NOT NULL REFERENCES noticia(noticia_id) ON DELETE CASCADE,
    leida_en           TIMESTAMPTZ,
    favorita           BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (anestesiologo_id, noticia_id)
);
CREATE TABLE IF NOT EXISTS noticia_revision (
    clave              VARCHAR(20) PRIMARY KEY,
    revisada_en        TIMESTAMPTZ NOT NULL
);
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS noticias_temas TEXT[];          -- null: todos los temas
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS noticias_leido_hasta TIMESTAMPTZ; -- «marcar todo como leído»
-- Título normalizado para no repetir una publicación que llega por dos fuentes
CREATE OR REPLACE FUNCTION clave_titulo(t TEXT) RETURNS TEXT LANGUAGE sql IMMUTABLE AS
$$ SELECT left(regexp_replace(lower(t), '[^a-z0-9]+', '', 'g'), 200) $$;
CREATE INDEX IF NOT EXISTS idx_noticia_clave_titulo ON noticia (clave_titulo(titulo));
CREATE INDEX IF NOT EXISTS idx_noticia_enlace ON noticia (enlace);

-- Documento normalizado para cruzar pagos con cirugías: sin puntos ni espacios, sin "CC"/"TI"… delante
--     y sin ceros a la izquierda ("CC 01.063.074.207" = "1063074207")
CREATE OR REPLACE FUNCTION doc_norm(t TEXT) RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN d ~ '^[0-9]+$' THEN ltrim(d, '0') ELSE d END
    FROM (SELECT regexp_replace(upper(regexp_replace(coalesce(t, ''), '[^A-Za-z0-9]', '', 'g')),
                                '^(CC|TI|CE|RC|PA|PPT|CN|MS|AS|NUIP)(?=[0-9])', '') AS d) x
$$;

-- 22. Anestesia regional: imágenes ecográficas propias de AP por bloqueo (las sube el administrador)
CREATE TABLE IF NOT EXISTS regional_imagen (
    imagen_id          BIGSERIAL PRIMARY KEY,
    bloque             VARCHAR(40) NOT NULL,
    url_archivo        TEXT NOT NULL,
    descripcion        VARCHAR(200),
    subida_por         BIGINT REFERENCES anestesiologo(anestesiologo_id) ON DELETE SET NULL,
    subida_en          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_regional_imagen_bloque ON regional_imagen (bloque);

-- 23. Registro propio: el anestesiólogo se registra y el administrador aprueba la cuenta
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS estado_registro VARCHAR(10) NOT NULL DEFAULT 'APROBADA'
    CHECK (estado_registro IN ('PENDIENTE', 'APROBADA'));
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS telefono VARCHAR(30);
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS autoriza_datos_en TIMESTAMPTZ;  -- autorización de tratamiento de datos (Ley 1581)

-- 25. Bloqueo temporal de la cuenta tras varios intentos fallidos de contraseña
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS intentos_fallidos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS bloqueado_hasta TIMESTAMPTZ;
