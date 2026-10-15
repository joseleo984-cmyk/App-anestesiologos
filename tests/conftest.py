import os
from pathlib import Path

import psycopg
import pytest

from app import auth, config

RAIZ = Path(__file__).resolve().parent.parent
EMAIL, PASSWORD = "prueba@ejemplo.com", "clave-de-prueba"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql:///anestesia_test")


@pytest.fixture
def db_url(monkeypatch, tmp_path):
    """Base de datos de prueba recreada desde cero en cada prueba."""
    try:
        conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL de prueba no disponible: {e}")
    with conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        conn.execute((RAIZ / "db/schema.sql").read_text())
        conn.execute("INSERT INTO anestesiologo (nombre, email, password_hash) VALUES (%s, %s, %s)",
                     ("Dra. Prueba", EMAIL, auth.hash_password(PASSWORD)))
    monkeypatch.setattr(config, "DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    return TEST_DATABASE_URL


@pytest.fixture
def conn(db_url):
    from app.repositorio import conectar
    with conectar() as c:
        yield c


@pytest.fixture(autouse=True)
def limites_limpios():
    """Los límites por conexión (intentos fallidos, registros) viven en memoria: cada prueba empieza de cero."""
    from app import main
    main._fallos_por_ip.clear()
    main._registros_por_ip.clear()
    yield
