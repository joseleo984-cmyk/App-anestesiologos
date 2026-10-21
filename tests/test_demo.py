"""Cuenta de demostración: datos ficticios recargables, documentos para la presentación y opción de ocultar
las herramientas clínicas."""
import io
from datetime import date

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import auth, demo, extraccion, main
from tests.conftest import EMAIL


@pytest.fixture
def cliente(db_url):
    c = TestClient(main.app)
    c.cookies.set(auth.COOKIE, auth.crear_sesion(1))
    return c


def marcar_demo(conn, anestesiologo_id=1):
    conn.execute("UPDATE anestesiologo SET es_demo = TRUE WHERE anestesiologo_id = %s", (anestesiologo_id,))
    conn.commit()


def texto_pdf(datos: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(datos)).pages)


def test_solo_cuentas_de_demostracion(cliente):
    assert cliente.post("/api/demo/recargar").status_code == 403
    assert cliente.get("/api/demo/orden.pdf").status_code == 403


def test_recargar_crea_datos_ficticios_y_se_puede_repetir(cliente, conn):
    marcar_demo(conn)
    for _ in range(2):   # la segunda vez borra y vuelve a crear lo mismo
        r = cliente.post("/api/demo/recargar")
        assert r.status_code == 200, r.text
        estados = {f["estado"]: f["n"] for f in conn.execute(
            "SELECT estado, count(*) AS n FROM cirugia WHERE anestesiologo_id = 1 GROUP BY estado").fetchall()}
        assert estados == {"PAGADA": 7, "FACTURADA": 2, "PROGRAMADA": 2, "REALIZADA": 8}
        assert conn.execute("SELECT count(*) AS n FROM reporte_pago WHERE anestesiologo_id = 1").fetchone()["n"] == 2
        assert conn.execute("SELECT count(*) AS n FROM cirujano").fetchone()["n"] == len(demo.CIRUJANOS)
        assert conn.execute("SELECT count(*) AS n FROM volante_pago").fetchone()["n"] == 6
    # todos los documentos de pacientes son del rango ficticio
    docs = [f["numero_documento"] for f in conn.execute("SELECT numero_documento FROM paciente").fetchall()]
    assert docs and all(d.startswith("9990") and len(d) == 10 for d in docs)
    inicio = cliente.get("/api/inicio").json()
    assert inicio["por_cobrar"]
    fin = cliente.get("/api/finanzas").json()
    assert fin["ingreso_base"] and float(fin["ingreso_base"]) > 0
    assert cliente.get("/api/yo").json()["demo_fecha"] == date.today().isoformat()


def test_reporte_y_volante_de_la_presentacion_cuadran(cliente, conn, monkeypatch):
    marcar_demo(conn)
    cliente.post("/api/demo/recargar")
    base = date.today()
    for nombre in ("orden", "reporte", "volante"):
        r = cliente.get(f"/api/demo/{nombre}.pdf")
        assert r.status_code == 200 and r.content.startswith(b"%PDF")
        assert "FICTICIO" in texto_pdf(r.content)
    rep = demo.reporte_en_vivo(base)
    assert rep.filas[0].documento_paciente in texto_pdf(cliente.get("/api/demo/reporte.pdf").content)

    # subir el reporte «en vivo»: cruza las cuatro cirugías recientes y deja dos líneas sin cirugía
    monkeypatch.setattr(extraccion, "extraer_reporte_pago", lambda datos, tipo: rep)
    r = cliente.post("/api/pagos", files={"archivo": ("r.pdf", cliente.get("/api/demo/reporte.pdf").content, "application/pdf")})
    assert r.status_code == 201, r.text
    resultados = [f["resultado"] for f in r.json()["filas"]]
    assert resultados.count("COINCIDE") == 4 and resultados.count("SIN_CIRUGIA") == 2

    # y el volante ficticio cuadra con la liquidación de ese reporte
    monkeypatch.setattr(extraccion, "extraer_volante", lambda datos, tipo: demo._volante(rep)[0])
    v = cliente.post(f"/api/pagos/{r.json()['reporte_id']}/volante",
                     files={"archivo": ("v.pdf", cliente.get("/api/demo/volante.pdf").content, "application/pdf")})
    assert v.status_code == 200, v.text
    assert {f["estado"] for f in v.json()["comparacion"]} == {"COINCIDE"}


def test_cirujanos_ficticios_no_se_sugieren_a_otros(cliente, conn):
    marcar_demo(conn)
    cliente.post("/api/demo/recargar")
    propios = {c["nombre"] for c in cliente.get("/api/sugerencias").json()["cirujanos"]}
    assert len(propios) == len(demo.CIRUJANOS)
    conn.execute("INSERT INTO anestesiologo (nombre, email, password_hash) VALUES ('Dr. Otro', 'otro@ejemplo.com', 'x')")
    conn.commit()
    otro = TestClient(main.app)
    otro.cookies.set(auth.COOKIE, auth.crear_sesion(2))
    assert otro.get("/api/sugerencias").json()["cirujanos"] == []


def test_admin_marca_la_cuenta_y_se_ocultan_las_herramientas(cliente, conn):
    conn.execute("UPDATE anestesiologo SET es_admin = TRUE WHERE email = %s", (EMAIL,))
    conn.execute("INSERT INTO anestesiologo (nombre, email, password_hash) VALUES ('Dra. Demo', 'demo@ejemplo.com', 'x')")
    conn.commit()
    assert cliente.put("/api/usuarios/2/demo", json={"es_demo": True}).status_code == 200
    fila = conn.execute("SELECT es_demo, ocultar_clinicas FROM anestesiologo WHERE anestesiologo_id = 2").fetchone()
    assert fila["es_demo"] and fila["ocultar_clinicas"]
    assert cliente.put("/api/usuarios/1/demo", json={"es_demo": True}).status_code == 404   # un administrador no


def test_preferencia_de_ocultar_herramientas_clinicas(cliente):
    assert cliente.get("/api/yo").json()["ocultar_clinicas"] is False
    assert cliente.put("/api/cuenta/preferencias", json={"ocultar_clinicas": True}).status_code == 200
    assert cliente.get("/api/yo").json()["ocultar_clinicas"] is True
