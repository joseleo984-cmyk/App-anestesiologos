"""Preparación de la base de datos al arrancar la app.

Crea las tablas si la base está vacía (primer despliegue) y deja listo el
usuario inicial con ADMIN_EMAIL / ADMIN_PASSWORD.
"""
import hashlib
import logging
from pathlib import Path

from psycopg import sql

from app import auth, config, repositorio

log = logging.getLogger(__name__)
ESQUEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
MIGRACIONES = ESQUEMA.with_name("migraciones.sql")


def preparar_base_de_datos() -> None:
    with repositorio.conectar() as conn:
        # Evita que dos procesos creen las tablas al mismo tiempo
        conn.execute("SELECT pg_advisory_xact_lock(4207001)")
        if conn.execute("SELECT to_regclass('public.anestesiologo') AS t").fetchone()["t"] is None:
            log.info("Base de datos vacía: creando tablas")
            conn.execute(ESQUEMA.read_text())
        # Lleva las bases creadas con versiones anteriores al esquema actual
        conn.execute(MIGRACIONES.read_text())

        # Supabase publica las tablas de "public" en su API REST. Con RLS activo y sin
        # políticas, esa API no ve ninguna fila; la app entra como dueña de las tablas
        # y no se ve afectada.
        tablas = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND NOT rowsecurity"
        ).fetchall()
        for t in tablas:
            conn.execute(sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(sql.Identifier(t["tablename"])))

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
