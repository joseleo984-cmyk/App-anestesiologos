"""Preparación de la base de datos al arrancar la app.

Crea las tablas si la base está vacía (primer despliegue) y deja listo el
usuario inicial con ADMIN_EMAIL / ADMIN_PASSWORD.
"""
import csv
import hashlib
import logging
from pathlib import Path

from psycopg import sql

from app import auth, config, repositorio

log = logging.getLogger(__name__)
ESQUEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
MIGRACIONES = ESQUEMA.with_name("migraciones.sql")
CLINICAS_BASE = ESQUEMA.parent / "seeds" / "clinicas.csv"
FUENTES_NOTICIAS = ESQUEMA.parent / "seeds" / "fuentes_noticias.csv"


def preparar_base_de_datos() -> None:
    with repositorio.conectar() as conn:
        # Si una tabla está bloqueada por otra conexión, fallar con un mensaje claro en vez de quedarse esperando
        # (Render mostraría la app "inicializando" sin fin)
        conn.execute("SET lock_timeout = '30s'")
        log.info("Preparando la base de datos…")
        # Evita que dos procesos creen las tablas al mismo tiempo
        conn.execute("SELECT pg_advisory_xact_lock(4207001)")
        if conn.execute("SELECT to_regclass('public.anestesiologo') AS t").fetchone()["t"] is None:
            log.info("Base de datos vacía: creando tablas")
            conn.execute(ESQUEMA.read_text())
        # Lleva las bases creadas con versiones anteriores al esquema actual. Solo corre cuando el archivo de
        # migraciones cambió: un reinicio normal no toca (ni bloquea) ninguna tabla.
        migraciones = MIGRACIONES.read_text()
        huella_mig = hashlib.sha256(migraciones.encode()).hexdigest()
        conn.execute("""CREATE TABLE IF NOT EXISTS migracion_aplicada (
                            huella VARCHAR(64) PRIMARY KEY, aplicada_en TIMESTAMPTZ NOT NULL DEFAULT now())""")
        if conn.execute("SELECT 1 FROM migracion_aplicada WHERE huella = %s", (huella_mig,)).fetchone():
            log.info("Migraciones al día")
        else:
            conn.execute(migraciones)
            conn.execute("INSERT INTO migracion_aplicada (huella) VALUES (%s)", (huella_mig,))
            log.info("Migraciones aplicadas")

        # Supabase publica las tablas de "public" en su API REST. Con RLS activo y sin
        # políticas, esa API no ve ninguna fila; la app entra como dueña de las tablas
        # y no se ve afectada.
        tablas = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND NOT rowsecurity"
        ).fetchall()
        for t in tablas:
            conn.execute(sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(sql.Identifier(t["tablename"])))

        # Clínicas conocidas, para que el nombre se sugiera desde la primera cirugía
        with open(CLINICAS_BASE, encoding="utf-8") as archivo:
            nuevas = repositorio.cargar_clinicas_base(conn, list(csv.DictReader(archivo)))
        if nuevas:
            log.info("Clínicas del listado base agregadas: %s", nuevas)

        # Fuentes de noticias propuestas: se cargan una sola vez; después las administra el administrador
        if not conn.execute("SELECT 1 FROM noticia_revision WHERE clave = 'semilla'").fetchone():
            with open(FUENTES_NOTICIAS, encoding="utf-8") as archivo:
                for f in csv.DictReader(archivo):
                    conn.execute("""INSERT INTO noticia_fuente (nombre, tipo, url) SELECT %(nombre)s, %(tipo)s, %(url)s::varchar
                                    WHERE NOT EXISTS (SELECT 1 FROM noticia_fuente WHERE url = %(url)s::varchar)""", f)
            conn.execute("INSERT INTO noticia_revision (clave, revisada_en) VALUES ('semilla', now())")
            log.info("Fuentes de noticias iniciales cargadas")

        if config.ADMIN_EMAIL and config.ADMIN_PASSWORD:
            if len(config.ADMIN_PASSWORD) < 10:
                raise RuntimeError("ADMIN_PASSWORD debe tener al menos 10 caracteres")
            # La clave de Render se aplica al crear la cuenta y cada vez que se CAMBIA en Render;
            # si el administrador la cambia desde la app, reiniciar no la devuelve a la de Render.
            huella = hashlib.sha256(config.ADMIN_PASSWORD.encode()).hexdigest()
            conn.execute(
                """INSERT INTO anestesiologo (nombre, email, password_hash, es_admin, clave_env_aplicada)
                   VALUES (%(nombre)s, %(email)s, %(hash)s, TRUE, %(huella)s)
                   ON CONFLICT (email) DO UPDATE SET
                       es_admin = TRUE, activo = TRUE,
                       password_hash = CASE WHEN anestesiologo.clave_env_aplicada IS DISTINCT FROM %(huella)s
                                            THEN %(hash)s ELSE anestesiologo.password_hash END,
                       debe_cambiar_clave = CASE WHEN anestesiologo.clave_env_aplicada IS DISTINCT FROM %(huella)s
                                                 THEN FALSE ELSE anestesiologo.debe_cambiar_clave END,
                       version_sesion = CASE WHEN anestesiologo.clave_env_aplicada IS DISTINCT FROM %(huella)s
                                             THEN anestesiologo.version_sesion + 1
                                             ELSE anestesiologo.version_sesion END,
                       clave_env_aplicada = %(huella)s""",
                {"nombre": config.ADMIN_NOMBRE, "email": config.ADMIN_EMAIL.strip().lower(),
                 "hash": auth.hash_password(config.ADMIN_PASSWORD), "huella": huella},
            )
    log.info("Base de datos lista")
