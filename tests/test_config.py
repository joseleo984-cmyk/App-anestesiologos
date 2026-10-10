import importlib
import os

from app import config


def test_contrasena_aparte_se_inserta_codificada(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", " postgresql://postgres.abc:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres ")
    monkeypatch.setenv("DATABASE_PASSWORD", "clave-con@y/raro")
    try:
        importlib.reload(config)
        assert config.DATABASE_URL == "postgresql://postgres.abc:clave-con%40y%2Fraro@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
    finally:
        monkeypatch.delenv("DATABASE_URL"); monkeypatch.delenv("DATABASE_PASSWORD")
        importlib.reload(config)
