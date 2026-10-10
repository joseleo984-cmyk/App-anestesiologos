"""Preparación de la base de datos al arrancar la app.

Crea las tablas si la base está vacía (primer despliegue) y deja listo el
usuario inicial con ADMIN_EMAIL / ADMIN_PASSWORD.
"""
import logging
from pathlib import Path

from psycopg import sql

from app import auth, config, repositorio

log = logging.getLogger(__name__)
ESQUEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def preparar_base_de_datos() -> None:
    with repositorio.conectar() as conn:
        # Evita que dos procesos creen las tablas al mismo tiempo
        conn.execute("SELECT pg_advisory_xact_lock(4207001)")
        if conn.execute("SELECT to_regclass('public.anestesiologo') AS t").fetchone()["t"] is None:
            log.info("Base de datos vacía: creando tablas")
            conn.execute(ESQUEMA.read_text())
        # Bases creadas antes de existir el inicio de sesión
        conn.execute("ALTER TABLE anestesiologo ADD COLUMN IF NOT EXISTS password_hash TEXT")

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
            conn.execute(
                """INSERT INTO anestesiologo (nombre, email, password_hash) VALUES (%s, %s, %s)
                   ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash""",
                (config.ADMIN_NOMBRE, config.ADMIN_EMAIL.strip().lower(), auth.hash_password(config.ADMIN_PASSWORD)),
            )
