import os
from pathlib import Path

import psycopg
import pytest

from app import config

RAIZ = Path(__file__).resolve().parent.parent
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
        conn.execute((RAIZ / "db/seeds/demo.sql").read_text())
    monkeypatch.setattr(config, "DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    return TEST_DATABASE_URL


@pytest.fixture
def conn(db_url):
    from app.repositorio import conectar
    with conectar() as c:
        yield c
