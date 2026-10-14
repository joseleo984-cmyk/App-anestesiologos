-- Une aseguradoras y cirujanos duplicados (mismo nombre sin tildes, mayúsculas, puntos ni "Dr.").
-- Se corre una vez en Supabase → SQL Editor. Si se corre de nuevo no pasa nada.
DO $$
DECLARE g RECORD; movidas int := 0; unidas int := 0; n int;
BEGIN
  -- 1. Aseguradoras: mismo nombre (sin tildes, mayúsculas ni puntos) y mismo tipo; se queda la más antigua
  FOR g IN
    WITH c AS (
      SELECT aseguradora_id, tipo, nombre,
             trim(regexp_replace(translate(upper(nombre), 'ÁÉÍÓÚÜÑ', 'AEIOUUN'), '[^A-Z0-9]+', ' ', 'g')) AS clave
        FROM aseguradora)
    SELECT c.aseguradora_id AS sale, k.queda
      FROM c JOIN (SELECT clave, tipo, min(aseguradora_id) AS queda FROM c GROUP BY clave, tipo HAVING count(*) > 1) k
           ON k.clave = c.clave AND k.tipo = c.tipo
     WHERE c.aseguradora_id <> k.queda
  LOOP
    -- la cobertura del paciente con la aseguradora que sale pasa a la que queda (o se une a la que ya tenga)
    UPDATE cirugia ci SET cobertura_id = d.cobertura_id
      FROM cobertura o JOIN cobertura d
           ON d.paciente_id = o.paciente_id AND d.aseguradora_id = g.queda
          AND d.numero_poliza IS NOT DISTINCT FROM o.numero_poliza
     WHERE o.aseguradora_id = g.sale AND ci.cobertura_id = o.cobertura_id;
    GET DIAGNOSTICS n = ROW_COUNT; movidas := movidas + n;
    DELETE FROM cobertura o USING cobertura d
     WHERE o.aseguradora_id = g.sale AND d.paciente_id = o.paciente_id AND d.aseguradora_id = g.queda
       AND d.numero_poliza IS NOT DISTINCT FROM o.numero_poliza;
    UPDATE cobertura SET aseguradora_id = g.queda WHERE aseguradora_id = g.sale;
    DELETE FROM aseguradora WHERE aseguradora_id = g.sale;
    unidas := unidas + 1;
  END LOOP;
  RAISE NOTICE 'Aseguradoras unidas: %', unidas;

  -- 2. Cirujanos: mismo nombre sin tildes, mayúsculas, puntos ni "Dr."; se queda el más antiguo
  unidas := 0;
  FOR g IN
    WITH c AS (
      SELECT cirujano_id,
             regexp_replace(trim(regexp_replace(translate(upper(nombre), 'ÁÉÍÓÚÜÑ', 'AEIOUUN'), '[^A-Z0-9]+', ' ', 'g')),
                            '^(DR|DRA|DOCTOR|DOCTORA) ', '') AS clave
        FROM cirujano)
    SELECT c.cirujano_id AS sale, k.queda
      FROM c JOIN (SELECT clave, min(cirujano_id) AS queda FROM c GROUP BY clave HAVING count(*) > 1) k ON k.clave = c.clave
     WHERE c.cirujano_id <> k.queda
  LOOP
    UPDATE cirugia SET cirujano_id = g.queda WHERE cirujano_id = g.sale;
    GET DIAGNOSTICS n = ROW_COUNT; movidas := movidas + n;
    DELETE FROM cirujano WHERE cirujano_id = g.sale;
    unidas := unidas + 1;
  END LOOP;
  RAISE NOTICE 'Cirujanos unidos: %. Cirugías actualizadas: %', unidas, movidas;
END $$;
