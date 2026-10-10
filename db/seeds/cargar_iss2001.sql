-- =====================================================================
-- Carga la tabla UVR del Manual Tarifario ISS 2001 (Acuerdo 256 de 2001)
-- Artículos 1 a 16: intervenciones y procedimientos médico-quirúrgicos.
--
-- Ejecutar desde la raíz del repositorio, después de schema.sql y honorarios.sql:
--   psql -d <base> -f db/seeds/cargar_iss2001.sql
--
-- valor_uvr_anestesia queda en NULL hasta registrar el valor en pesos por UVR
-- del anestesiólogo; mientras tanto los convenios pueden fijar su propio valor_uvr.
-- =====================================================================
BEGIN;

INSERT INTO manual_tarifario (nombre, descripcion)
VALUES ('ISS 2001', 'Acuerdo 256 de 2001 - Manual de Tarifas EPS-ISS')
ON CONFLICT (nombre) DO NOTHING;

CREATE TEMP TABLE tmp_iss2001 (
    codigo_cups   VARCHAR(10),
    codigo_iss    VARCHAR(10),
    descripcion   TEXT,
    uvr           NUMERIC(8,2),
    articulo      INTEGER,
    especialidad  VARCHAR(100)
) ON COMMIT DROP;

\copy tmp_iss2001 FROM 'db/seeds/iss2001_uvr.csv' WITH (FORMAT csv, HEADER true)

-- Catálogo de procedimientos: solo agrega los códigos que no existan
INSERT INTO procedimiento (codigo, nombre)
SELECT codigo_cups, LEFT(descripcion, 255) FROM tmp_iss2001
ON CONFLICT (codigo) DO NOTHING;

INSERT INTO tarifa_uvr (manual_id, codigo, codigo_manual, uvr)
SELECT m.manual_id, t.codigo_cups, t.codigo_iss, t.uvr
  FROM tmp_iss2001 t
  JOIN manual_tarifario m ON m.nombre = 'ISS 2001'
ON CONFLICT (manual_id, codigo) DO UPDATE
   SET codigo_manual = EXCLUDED.codigo_manual,
       uvr           = EXCLUDED.uvr;

COMMIT;
