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

-- 18. Noticias de anestesia: fuentes curadas (RSS o búsqueda de PubMed), noticias resumidas por la IA y lo que cada uno leyó
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

-- 19. Documento normalizado para cruzar pagos con cirugías: sin puntos ni espacios, sin "CC"/"TI"… delante
--     y sin ceros a la izquierda ("CC 01.063.074.207" = "1063074207")
CREATE OR REPLACE FUNCTION doc_norm(t TEXT) RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN d ~ '^[0-9]+$' THEN ltrim(d, '0') ELSE d END
    FROM (SELECT regexp_replace(upper(regexp_replace(coalesce(t, ''), '[^A-Za-z0-9]', '', 'g')),
                                '^(CC|TI|CE|RC|PA|PPT|CN|MS|AS|NUIP)(?=[0-9])', '') AS d) x
$$;

-- 20. Relación o liquidación de AP de clínicas que pagan el total de lo entregado (ej. Santa Ana)
ALTER TABLE reporte_pago ADD COLUMN IF NOT EXISTS tipo VARCHAR(10) NOT NULL DEFAULT 'PAGOS'
    CHECK (tipo IN ('PAGOS','RELACION'));
ALTER TABLE reporte_pago ADD COLUMN IF NOT EXISTS numero VARCHAR(50);
ALTER TABLE pago_detalle ADD COLUMN IF NOT EXISTS numero_orden VARCHAR(100);
ALTER TABLE pago_detalle ADD COLUMN IF NOT EXISTS procedimiento VARCHAR(300);

-- 21. Noticias en infografía (historias y boletín semanal)
ALTER TABLE noticia ADD COLUMN IF NOT EXISTS relevancia SMALLINT;
ALTER TABLE noticia ADD COLUMN IF NOT EXISTS cifra VARCHAR(40);
ALTER TABLE noticia ADD COLUMN IF NOT EXISTS cifra_etiqueta VARCHAR(160);
ALTER TABLE noticia ADD COLUMN IF NOT EXISTS pacientes INTEGER;
ALTER TABLE noticia ADD COLUMN IF NOT EXISTS conclusion TEXT;
ALTER TABLE noticia ADD COLUMN IF NOT EXISTS diseno VARCHAR(24);
ALTER TABLE noticia ADD COLUMN IF NOT EXISTS poblacion TEXT;
ALTER TABLE noticia ADD COLUMN IF NOT EXISTS intervencion TEXT;
ALTER TABLE noticia ADD COLUMN IF NOT EXISTS comparador TEXT;
ALTER TABLE noticia ADD COLUMN IF NOT EXISTS grupo_a VARCHAR(120);
ALTER TABLE noticia ADD COLUMN IF NOT EXISTS valor_a NUMERIC(6,2);
ALTER TABLE noticia ADD COLUMN IF NOT EXISTS grupo_b VARCHAR(120);
ALTER TABLE noticia ADD COLUMN IF NOT EXISTS valor_b NUMERIC(6,2);
ALTER TABLE noticia ADD COLUMN IF NOT EXISTS evento VARCHAR(160);

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

-- 24. Pacientes y coberturas aislados por anestesiólogo. Antes un paciente se identificaba solo por su
--     documento y la orden de un anestesiólogo podía cambiar el nombre que veía otro. Cada anestesiólogo que
--     tiene cirugías de un paciente compartido recibe su propia copia del paciente y de sus coberturas.
ALTER TABLE paciente ADD COLUMN IF NOT EXISTS anestesiologo_id BIGINT REFERENCES anestesiologo(anestesiologo_id) ON DELETE CASCADE;
ALTER TABLE paciente DROP CONSTRAINT IF EXISTS paciente_tipo_documento_numero_documento_key;
DO $$
DECLARE
  par RECORD; cob RECORD; dueno BIGINT; nuevo BIGINT; nueva_cob BIGINT;
BEGIN
  FOR par IN SELECT DISTINCT paciente_id, anestesiologo_id FROM cirugia ORDER BY paciente_id, anestesiologo_id LOOP
    SELECT anestesiologo_id INTO dueno FROM paciente WHERE paciente_id = par.paciente_id;
    IF dueno IS NULL THEN
      UPDATE paciente SET anestesiologo_id = par.anestesiologo_id WHERE paciente_id = par.paciente_id;
    ELSIF dueno <> par.anestesiologo_id THEN
      SELECT n.paciente_id INTO nuevo FROM paciente n JOIN paciente o ON o.paciente_id = par.paciente_id
       WHERE n.anestesiologo_id = par.anestesiologo_id AND n.tipo_documento = o.tipo_documento
         AND n.numero_documento = o.numero_documento;
      IF nuevo IS NULL THEN
        INSERT INTO paciente (anestesiologo_id, tipo_documento, numero_documento, nombres, apellidos, creado_en)
        SELECT par.anestesiologo_id, tipo_documento, numero_documento, nombres, apellidos, creado_en
          FROM paciente WHERE paciente_id = par.paciente_id
        RETURNING paciente_id INTO nuevo;
      END IF;
      FOR cob IN SELECT DISTINCT cb.cobertura_id, cb.aseguradora_id, cb.numero_poliza, cb.plan, cb.activa
                   FROM cirugia c JOIN cobertura cb ON cb.cobertura_id = c.cobertura_id
                  WHERE c.paciente_id = par.paciente_id AND c.anestesiologo_id = par.anestesiologo_id LOOP
        SELECT cobertura_id INTO nueva_cob FROM cobertura
         WHERE paciente_id = nuevo AND aseguradora_id = cob.aseguradora_id AND numero_poliza IS NOT DISTINCT FROM cob.numero_poliza;
        IF nueva_cob IS NULL THEN
          INSERT INTO cobertura (paciente_id, aseguradora_id, numero_poliza, plan, activa)
          VALUES (nuevo, cob.aseguradora_id, cob.numero_poliza, cob.plan, cob.activa) RETURNING cobertura_id INTO nueva_cob;
        END IF;
        UPDATE cirugia SET cobertura_id = nueva_cob
         WHERE cobertura_id = cob.cobertura_id AND anestesiologo_id = par.anestesiologo_id;
      END LOOP;
      UPDATE cirugia SET paciente_id = nuevo WHERE paciente_id = par.paciente_id AND anestesiologo_id = par.anestesiologo_id;
      RAISE NOTICE 'Paciente % compartido: copia % para el anestesiólogo %', par.paciente_id, nuevo, par.anestesiologo_id;
    END IF;
  END LOOP;
END $$;
-- pacientes sin ninguna cirugía (no tienen dueño posible)
DELETE FROM paciente WHERE anestesiologo_id IS NULL AND NOT EXISTS (SELECT 1 FROM cirugia c WHERE c.paciente_id = paciente.paciente_id);
ALTER TABLE paciente ALTER COLUMN anestesiologo_id SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS paciente_anestesiologo_documento ON paciente (anestesiologo_id, tipo_documento, numero_documento);

-- 25. Bloqueo temporal de la cuenta tras varios intentos fallidos de contraseña
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS intentos_fallidos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS bloqueado_hasta TIMESTAMPTZ;

-- 26. «Olvidé mi contraseña»: enlaces de un solo uso (se guarda solo la huella del token)
CREATE TABLE IF NOT EXISTS restablecimiento_clave (
    token_hash         CHAR(64) PRIMARY KEY,
    anestesiologo_id   BIGINT NOT NULL REFERENCES anestesiologo(anestesiologo_id) ON DELETE CASCADE,
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now(),
    expira_en          TIMESTAMPTZ NOT NULL,
    usado_en           TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_restablecimiento_anest ON restablecimiento_clave (anestesiologo_id, creado_en);

-- 27. Aceptación de los términos de uso y de la política de datos: versión y fecha
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS terminos_version VARCHAR(20);
ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS terminos_aceptados_en TIMESTAMPTZ;
