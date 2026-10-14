"""Copia de seguridad de la base de datos: todas las tablas en CSV dentro de un .zip cifrado (AES-256) con
una clave que escoge el administrador. Se restaura con db/mantenimiento/restaurar_copia.py.

Las fotos y PDF de las órdenes (Supabase Storage) no van aquí: se respaldan aparte.
"""
import csv
import io
import json
from datetime import datetime, timezone

import pyzipper

from app import config

MIN_CLAVE = 10


def tablas_en_orden(conn) -> list[str]:
    """Tablas de public ordenadas para que cada una vaya después de las que referencia (para restaurar)."""
    tablas = [r["tablename"] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")]
    deps = {t: set() for t in tablas}
    for r in conn.execute(
            """SELECT c.conrelid::regclass::text AS hija, c.confrelid::regclass::text AS madre
                 FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
                WHERE c.contype = 'f' AND n.nspname = 'public'"""):
        if r["hija"] in deps and r["madre"] != r["hija"]:
            deps[r["hija"]].add(r["madre"])
    orden, hechas = [], set()
    while len(orden) < len(tablas):
        listas = [t for t in tablas if t not in hechas and deps[t] <= hechas]
        if not listas:  # ciclo (no debería haber): el resto en orden alfabético
            listas = [t for t in tablas if t not in hechas]
        for t in listas:
            orden.append(t)
            hechas.add(t)
    return orden


def crear_copia(conn, clave: str) -> tuple[bytes, dict]:
    """Devuelve el .zip cifrado y el resumen (tablas y filas)."""
    if len(clave or "") < MIN_CLAVE:
        raise ValueError(f"La clave debe tener al menos {MIN_CLAVE} caracteres.")
    resumen = {"app": "Auditorías AP", "version": config.VERSION,
               "creada_en": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tablas": {}}
    salida = io.BytesIO()
    with pyzipper.AESZipFile(salida, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as z:
        z.setpassword(clave.encode())
        orden = tablas_en_orden(conn)
        for t in orden:
            with conn.cursor().copy(f'COPY (SELECT * FROM "{t}") TO STDOUT WITH (FORMAT csv, HEADER true)') as copia:
                datos = b"".join(bytes(b) for b in copia)
            filas = contar_filas_csv(datos)
            z.writestr(f"tablas/{t}.csv", datos)
            resumen["tablas"][t] = filas
        resumen["orden"] = orden
        z.writestr("copia.json", json.dumps(resumen, ensure_ascii=False, indent=2))
    return salida.getvalue(), resumen


def contar_filas_csv(datos: bytes) -> int:
    """Filas de datos (un texto con saltos de línea entre comillas cuenta como una sola fila)."""
    return max(0, sum(1 for _ in csv.reader(io.StringIO(datos.decode("utf-8")))) - 1) if datos else 0


def restaurar(conn, contenido: bytes, clave: str, vaciar: bool = False) -> dict:
    """Carga una copia en una base que ya tiene el esquema (db/schema.sql). Si `vaciar`, primero BORRA todos
    los datos actuales; si no, las tablas deben estar vacías. Devuelve las filas cargadas por tabla."""
    with pyzipper.AESZipFile(io.BytesIO(contenido)) as z:
        z.setpassword(clave.encode())
        try:
            resumen = json.loads(z.read("copia.json"))
        except RuntimeError as e:
            raise ValueError("La clave de la copia no es correcta.") from e
        cargadas = {}
        if vaciar:
            todas = ", ".join(f'"{t}"' for t in tablas_en_orden(conn))
            conn.execute(f"TRUNCATE {todas} RESTART IDENTITY CASCADE")
        for t in resumen["orden"]:
            if conn.execute("SELECT 1 FROM \"%s\" LIMIT 1" % t.replace('"', "")).fetchone():
                raise ValueError(f"La tabla {t} ya tiene datos: restaure sobre una base vacía.")
        for t in resumen["orden"]:
            datos = z.read(f"tablas/{t}.csv")
            columnas = next(csv.reader(io.StringIO(datos.decode("utf-8").split("\n", 1)[0])))
            lista = ", ".join(f'"{c}"' for c in columnas)
            with conn.cursor().copy(f'COPY "{t}" ({lista}) FROM STDIN WITH (FORMAT csv, HEADER true)') as copia:
                copia.write(datos)
            cargadas[t] = contar_filas_csv(datos)
        # los contadores (BIGSERIAL) siguen después del mayor id cargado
        for r in conn.execute(
                """SELECT c.table_name, c.column_name, pg_get_serial_sequence(format('%I', c.table_name), c.column_name) AS seq
                     FROM information_schema.columns c
                    WHERE c.table_schema = 'public' AND c.column_default LIKE 'nextval%'""").fetchall():
            if r["seq"]:
                conn.execute(f"""SELECT setval('{r["seq"]}', COALESCE((SELECT max("{r["column_name"]}")
                                 FROM "{r["table_name"]}"), 0) + 1, false)""")
    return cargadas
