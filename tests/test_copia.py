"""Copia de seguridad: descarga cifrada (solo administrador) y restauración completa en otra base."""
import io

import psycopg
import pytest
import pyzipper
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app import auth, copia, main
from tests.conftest import RAIZ, TEST_DATABASE_URL
from tests.test_api import CONFIRMAR, cliente  # noqa: F401  (fixture)

CLAVE = "clave-de-la-copia-123"


@pytest.fixture
def otra_base():
    """Una segunda base vacía con el esquema, para restaurar."""
    url = TEST_DATABASE_URL + "_restaurar"
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as c:
        c.execute("DROP DATABASE IF EXISTS anestesia_test_restaurar")
        c.execute("CREATE DATABASE anestesia_test_restaurar")
    with psycopg.connect(url, autocommit=True) as c:
        c.execute((RAIZ / "db/schema.sql").read_text())
    yield url
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as c:
        c.execute("DROP DATABASE IF EXISTS anestesia_test_restaurar")


def test_copia_cifrada_y_restauracion(cliente, conn, otra_base):
    conn.execute("UPDATE anestesiologo SET es_admin = TRUE WHERE anestesiologo_id = 1")
    conn.commit()
    for doc in ("1001", "1002"):
        assert cliente.post("/api/cirugias", json={**CONFIRMAR, "paciente": {**CONFIRMAR["paciente"], "numero_documento": doc},
                                                   }).status_code == 201
    cliente.post("/api/finanzas/partidas", json={"clase": "GASTO", "categoria": "VIVIENDA", "nombre": "Arriendo",
                                                "valor_mensual": "2.000.000"})
    # un texto con salto de línea, coma y comillas debe volver igual
    conn.execute("""UPDATE cirugia SET observaciones = E'línea 1\\nlínea 2, con coma y "comillas"'""")
    conn.commit()
    assert cliente.post("/api/copia-seguridad", json={"clave": "corta"}).status_code == 422
    r = cliente.post("/api/copia-seguridad", json={"clave": CLAVE})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "copia-auditorias-ap-" in r.headers["content-disposition"]

    # sin la clave no se lee
    with pyzipper.AESZipFile(io.BytesIO(r.content)) as z:
        assert "tablas/cirugia.csv" in z.namelist()
        with pytest.raises(RuntimeError):
            z.read("copia.json")

    with psycopg.connect(otra_base, row_factory=dict_row) as destino:
        with pytest.raises(ValueError, match="clave"):
            copia.restaurar(destino, r.content, "otra-clave-errada")
        destino.rollback()
        filas = copia.restaurar(destino, r.content, CLAVE)
        destino.commit()
        assert filas["cirugia"] == 2 and filas["fin_partida"] == 1 and filas["anestesiologo"] == 1
        obs = destino.execute("SELECT observaciones FROM cirugia ORDER BY cirugia_id").fetchall()
        assert obs[0]["observaciones"] == 'línea 1\nlínea 2, con coma y "comillas"'
        # los contadores siguen después de lo restaurado
        nuevo = destino.execute("INSERT INTO clinica (nombre) VALUES ('NUEVA') RETURNING clinica_id").fetchone()
        assert nuevo["clinica_id"] > max(r["clinica_id"] for r in destino.execute("SELECT clinica_id FROM clinica WHERE nombre <> 'NUEVA'"))
        destino.rollback()
        # sobre una base con datos no se restaura, salvo que se pida vaciarla
        with pytest.raises(ValueError, match="ya tiene datos"):
            copia.restaurar(destino, r.content, CLAVE)
        destino.rollback()
        assert copia.restaurar(destino, r.content, CLAVE, vaciar=True)["cirugia"] == 2


def test_solo_el_administrador_descarga_la_copia(cliente):
    assert cliente.post("/api/copia-seguridad", json={"clave": CLAVE}).status_code == 403
