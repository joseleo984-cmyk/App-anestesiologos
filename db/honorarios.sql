-- =====================================================================
-- App Anestesiólogos - Módulo de honorarios
-- Ejecutar DESPUÉS de schema.sql
--
-- Permite que cada anestesiólogo vea cuánto le van a pagar por cirugía,
-- según el convenio pactado con la aseguradora y/o la clínica:
--   * UVR          -> UVR del procedimiento x valor UVR (+/- % de ajuste)
--                     (típico EPS: "ISS 2001 + 30 %")
--   * TARIFA_FIJA  -> valor pactado por código (típico prepagadas/pólizas)
-- =====================================================================

-- ---------------------------------------------------------------------
-- 10. Manual tarifario (ISS 2001, ISS 2004, SOAT, propio de la aseguradora...)
-- ---------------------------------------------------------------------
CREATE TABLE manual_tarifario (
    manual_id          BIGSERIAL PRIMARY KEY,
    nombre             VARCHAR(50)    NOT NULL UNIQUE,     -- ej. 'ISS 2001'
    valor_uvr_anestesia NUMERIC(12,2),                     -- $ por UVR para el anestesiólogo
    descripcion        TEXT
);

-- ---------------------------------------------------------------------
-- 11. Tabla UVR: cuántas UVR vale cada procedimiento en cada manual
--     Los manuales ISS usan su propio código; aquí se homologa a CUPS.
-- ---------------------------------------------------------------------
CREATE TABLE tarifa_uvr (
    manual_id          BIGINT       NOT NULL REFERENCES manual_tarifario(manual_id) ON DELETE CASCADE,
    codigo             VARCHAR(10)  NOT NULL REFERENCES procedimiento(codigo),   -- CUPS
    codigo_manual      VARCHAR(10),                         -- código original del manual (ISS)
    uvr                NUMERIC(8,2) NOT NULL CHECK (uvr > 0),
    PRIMARY KEY (manual_id, codigo)
);

-- ---------------------------------------------------------------------
-- 12. Convenio: qué le paga cada aseguradora y/o clínica al anestesiólogo
--     aseguradora_id NULL -> aplica a cualquier aseguradora (o particular)
--     clinica_id     NULL -> aplica en cualquier clínica
--     Prioridad al buscar: aseguradora+clínica > aseguradora > clínica > general
-- ---------------------------------------------------------------------
CREATE TABLE convenio (
    convenio_id        BIGSERIAL PRIMARY KEY,
    anestesiologo_id   BIGINT NOT NULL REFERENCES anestesiologo(anestesiologo_id) ON DELETE CASCADE,
    aseguradora_id     BIGINT          REFERENCES aseguradora(aseguradora_id),
    clinica_id         BIGINT          REFERENCES clinica(clinica_id),
    nombre             VARCHAR(100),                        -- ej. 'Sura EPS 2026'
    modalidad          VARCHAR(12) NOT NULL CHECK (modalidad IN ('UVR','TARIFA_FIJA')),
    manual_id          BIGINT          REFERENCES manual_tarifario(manual_id),
    valor_uvr          NUMERIC(12,2),                       -- NULL = usa el del manual
    porcentaje_ajuste  NUMERIC(6,2) NOT NULL DEFAULT 0,     -- +30 = ISS +30 %, -10 = ISS -10 %
    porcentaje_adicional NUMERIC(5,2) NOT NULL DEFAULT 50,  -- % que se paga por cada procedimiento no principal
    dias_pago          INTEGER,                             -- plazo de pago pactado
    vigente_desde      DATE NOT NULL,
    vigente_hasta      DATE,
    CHECK (modalidad <> 'UVR' OR manual_id IS NOT NULL),
    CHECK (vigente_hasta IS NULL OR vigente_hasta >= vigente_desde)
);
CREATE INDEX idx_convenio_busqueda ON convenio (anestesiologo_id, aseguradora_id, clinica_id);

-- ---------------------------------------------------------------------
-- 13. Tarifa fija por código dentro de un convenio
-- ---------------------------------------------------------------------
CREATE TABLE convenio_tarifa (
    convenio_id        BIGINT        NOT NULL REFERENCES convenio(convenio_id) ON DELETE CASCADE,
    codigo             VARCHAR(10)   NOT NULL REFERENCES procedimiento(codigo),
    valor              NUMERIC(14,2) NOT NULL CHECK (valor >= 0),
    PRIMARY KEY (convenio_id, codigo)
);

-- ---------------------------------------------------------------------
-- Cambios a tablas existentes
-- El valor calculado se guarda como "foto" (snapshot): si después cambia
-- el convenio o la tabla UVR, las cirugías ya liquidadas no se alteran.
-- ---------------------------------------------------------------------
-- valor_honorarios, fecha_pago y el estado PAGADA ya vienen en schema.sql
ALTER TABLE cirugia
    ADD COLUMN convenio_id       BIGINT REFERENCES convenio(convenio_id),
    ADD COLUMN honorarios_completos BOOLEAN;      -- FALSE = algún código quedó sin tarifa

ALTER TABLE cirugia_procedimiento
    ADD COLUMN uvr               NUMERIC(8,2),
    ADD COLUMN valor_unitario    NUMERIC(14,2),   -- valor UVR aplicado o tarifa fija
    ADD COLUMN porcentaje        NUMERIC(5,2),    -- 100 principal / % adicional
    ADD COLUMN valor_calculado   NUMERIC(14,2);   -- NULL = no hay tarifa para el código

-- ---------------------------------------------------------------------
-- Busca el convenio que aplica a una cirugía
-- ---------------------------------------------------------------------
CREATE FUNCTION buscar_convenio(p_cirugia_id BIGINT) RETURNS BIGINT
LANGUAGE sql STABLE AS $$
    SELECT cv.convenio_id
    FROM cirugia c
    LEFT JOIN cobertura cb ON cb.cobertura_id = c.cobertura_id
    JOIN convenio cv
      ON cv.anestesiologo_id = c.anestesiologo_id
     AND (cv.aseguradora_id IS NULL OR cv.aseguradora_id = cb.aseguradora_id)
     AND (cv.clinica_id     IS NULL OR cv.clinica_id     = c.clinica_id)
     AND c.fecha_procedimiento >= cv.vigente_desde
     AND (cv.vigente_hasta IS NULL OR c.fecha_procedimiento <= cv.vigente_hasta)
    WHERE c.cirugia_id = p_cirugia_id
    ORDER BY (cv.aseguradora_id IS NOT NULL) DESC,
             (cv.clinica_id     IS NOT NULL) DESC,
             cv.vigente_desde DESC
    LIMIT 1;
$$;

-- ---------------------------------------------------------------------
-- Calcula y guarda los honorarios de una cirugía. Devuelve el total.
-- Se llama al crear/editar la cirugía (después de validar la foto/PDF).
-- ---------------------------------------------------------------------
CREATE FUNCTION calcular_honorarios(p_cirugia_id BIGINT) RETURNS NUMERIC
LANGUAGE plpgsql AS $$
DECLARE
    v_convenio convenio%ROWTYPE;
    v_total    NUMERIC(14,2);
    v_completo BOOLEAN;
BEGIN
    SELECT * INTO v_convenio FROM convenio WHERE convenio_id = buscar_convenio(p_cirugia_id);

    IF v_convenio.convenio_id IS NULL THEN
        UPDATE cirugia_procedimiento
           SET uvr = NULL, valor_unitario = NULL, porcentaje = NULL, valor_calculado = NULL
         WHERE cirugia_id = p_cirugia_id;
        UPDATE cirugia SET convenio_id = NULL, valor_honorarios = NULL, honorarios_completos = FALSE
         WHERE cirugia_id = p_cirugia_id;
        RETURN NULL;
    END IF;

    UPDATE cirugia_procedimiento cp
       SET uvr            = t.uvr,
           valor_unitario = t.valor_unitario,
           porcentaje     = t.porcentaje,
           valor_calculado = ROUND(
               CASE WHEN v_convenio.modalidad = 'UVR'
                    THEN t.uvr * t.valor_unitario * (1 + v_convenio.porcentaje_ajuste / 100)
                    ELSE t.valor_unitario
               END * t.porcentaje / 100, 0)
      FROM (
        SELECT p.codigo,
               tu.uvr,
               CASE WHEN v_convenio.modalidad = 'UVR'
                    THEN COALESCE(v_convenio.valor_uvr, m.valor_uvr_anestesia)
                    ELSE ct.valor
               END AS valor_unitario,
               CASE WHEN p.es_principal THEN 100
                    ELSE v_convenio.porcentaje_adicional END AS porcentaje
          FROM cirugia_procedimiento p
          LEFT JOIN tarifa_uvr tu       ON tu.manual_id = v_convenio.manual_id AND tu.codigo = p.codigo
          LEFT JOIN manual_tarifario m  ON m.manual_id  = v_convenio.manual_id
          LEFT JOIN convenio_tarifa ct  ON ct.convenio_id = v_convenio.convenio_id AND ct.codigo = p.codigo
         WHERE p.cirugia_id = p_cirugia_id
      ) t
     WHERE cp.cirugia_id = p_cirugia_id AND cp.codigo = t.codigo;

    SELECT SUM(valor_calculado), bool_and(valor_calculado IS NOT NULL)
      INTO v_total, v_completo
      FROM cirugia_procedimiento WHERE cirugia_id = p_cirugia_id;

    UPDATE cirugia SET convenio_id = v_convenio.convenio_id, valor_honorarios = v_total,
                       honorarios_completos = COALESCE(v_completo, FALSE)
     WHERE cirugia_id = p_cirugia_id;
    RETURN v_total;
END;
$$;

-- ---------------------------------------------------------------------
-- Vista para el tablero del anestesiólogo: cuánto le van a pagar,
-- agrupado por mes, clínica y aseguradora.
-- ---------------------------------------------------------------------
CREATE VIEW v_honorarios AS
SELECT c.anestesiologo_id,
       date_trunc('month', c.fecha_procedimiento)::date             AS mes,
       cl.nombre                                                    AS clinica,
       COALESCE(a.nombre, 'Particular')                             AS aseguradora,
       COALESCE(a.tipo, 'PARTICULAR')                               AS tipo_aseguradora,
       COUNT(*)                                                     AS cirugias,
       SUM(c.valor_honorarios)                                      AS total,
       SUM(c.valor_honorarios) FILTER (WHERE c.estado = 'PAGADA')   AS pagado,
       SUM(c.valor_honorarios) FILTER (WHERE c.estado <> 'PAGADA')  AS por_cobrar,
       COUNT(*) FILTER (WHERE NOT COALESCE(c.honorarios_completos, FALSE)) AS sin_tarifa
  FROM cirugia c
  JOIN clinica cl        ON cl.clinica_id = c.clinica_id
  LEFT JOIN cobertura cb ON cb.cobertura_id = c.cobertura_id
  LEFT JOIN aseguradora a ON a.aseguradora_id = cb.aseguradora_id
 WHERE c.estado <> 'CANCELADA'
 GROUP BY 1, 2, 3, 4, 5;
