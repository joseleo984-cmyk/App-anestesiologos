import pytest
from fastapi.testclient import TestClient

from app import auth, extraccion, main
from app.modelos import OrdenExtraida
from tests.test_extraccion import RESPUESTA, foto

CONFIRMAR = {
    "paciente": {"tipo_documento": "CC", "numero_documento": "1020304050", "nombres": "María", "apellidos": "Gómez"},
    "aseguradora": {"nombre": "Sura", "tipo": "EPS"},
    "clinica": {"nombre": "Clínica Las Américas", "ciudad": "Medellín"},
    "procedimientos": [{"codigo": "471100", "nombre": "Apendicectomía", "es_principal": True}],
    "fecha_procedimiento": "2026-10-15",
}


@pytest.fixture
def cliente(db_url, monkeypatch):
    llamadas = []

    def extraer_falso(datos, media_type):
        llamadas.append(media_type)
        return OrdenExtraida.model_validate(RESPUESTA)

    monkeypatch.setattr(extraccion, "extraer_orden", extraer_falso)
    c = TestClient(main.app)
    c.cookies.set(auth.COOKIE, auth.crear_sesion(1))
    c.llamadas = llamadas
    return c


def subir(cliente, datos=None, nombre="orden.jpg", tipo="image/jpeg"):
    return cliente.post("/api/documentos", files={"archivo": (nombre, datos or foto(), tipo)})


def test_flujo_completo_foto_a_cirugia(cliente):
    r = subir(cliente)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["datos"]["paciente"]["numero_documento"] == "1020304050"

    r = cliente.post(f"/api/documentos/{doc['documento_id']}/confirmar", json=CONFIRMAR)
    assert r.status_code == 201, r.text
    cirugia_id = r.json()["cirugia_id"]

    estado = cliente.get(f"/api/documentos/{doc['documento_id']}").json()
    assert estado["estado"] == "VALIDADO" and estado["cirugia_id"] == cirugia_id
    assert estado["datos_extraidos"]["confianza"] == 0.93

    lista = cliente.get("/api/cirugias").json()
    assert [c["cirugia_id"] for c in lista] == [cirugia_id]


def test_no_guarda_dos_veces_la_misma_orden(cliente):
    doc = subir(cliente).json()
    url = f"/api/documentos/{doc['documento_id']}/confirmar"
    assert cliente.post(url, json=CONFIRMAR).status_code == 201
    r = cliente.post(url, json=CONFIRMAR)
    assert r.status_code == 409
    assert len(cliente.get("/api/cirugias").json()) == 1


def test_mismo_archivo_dos_veces(cliente):
    datos = foto()
    primero = subir(cliente, datos).json()
    r = subir(cliente, datos)
    assert r.status_code == 409
    assert r.json()["detail"]["documento_id"] == primero["documento_id"]
    assert len(cliente.llamadas) == 1  # no se paga una segunda lectura


def test_reintento_tras_error_de_lectura(cliente, monkeypatch):
    def falla(datos, media_type):
        raise extraccion.ExtraccionError("borrosa")
    monkeypatch.setattr(extraccion, "extraer_orden", falla)
    datos = foto()
    r = subir(cliente, datos)
    assert r.status_code == 422 and r.json()["detail"]["mensaje"] == "borrosa"
    doc_id = r.json()["detail"]["documento_id"]
    assert cliente.get(f"/api/documentos/{doc_id}").json()["estado"] == "ERROR"

    monkeypatch.setattr(extraccion, "extraer_orden", lambda d, t: OrdenExtraida.model_validate(RESPUESTA))
    r = subir(cliente, datos)
    assert r.status_code == 201 and r.json()["documento_id"] == doc_id


def test_rechaza_archivos_que_no_son_foto_ni_pdf(cliente):
    r = subir(cliente, b"MZ\x90\x00 ejecutable", "orden.jpg", "image/jpeg")
    assert r.status_code == 415
    assert cliente.llamadas == []


def test_pdf_detectado_por_contenido(cliente):
    assert subir(cliente, b"%PDF-1.7 contenido", "orden.bin", "application/octet-stream").status_code == 201
    assert cliente.llamadas == ["application/pdf"]


def test_confirmar_valida_datos(cliente):
    doc = subir(cliente).json()
    malo = {**CONFIRMAR, "procedimientos": []}
    r = cliente.post(f"/api/documentos/{doc['documento_id']}/confirmar", json=malo)
    assert r.status_code == 422
    assert cliente.get(f"/api/documentos/{doc['documento_id']}").json()["estado"] == "EXTRAIDO"


def test_documento_inexistente(cliente):
    assert cliente.post("/api/documentos/999/confirmar", json=CONFIRMAR).status_code == 404


def test_registro_manual(cliente):
    r = cliente.post("/api/cirugias", json={**CONFIRMAR, "aseguradora": None})
    assert r.status_code == 201
    assert cliente.get("/api/cirugias").json()[0]["aseguradora"] == "PARTICULAR"


def test_pagina_principal(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "Órdenes de cirugía" in r.text


def test_foto_heic_aceptada(cliente):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "white").save(buf, format="HEIF")
    assert subir(cliente, buf.getvalue(), "IMG_0001.HEIC", "image/heic").status_code == 201
    assert cliente.llamadas == ["image/heic"]


def test_el_selector_no_filtra_tipos(cliente):
    """Con accept, Safari dejaba los PDF sin poder elegirse; el servidor valida el tipo."""
    import re
    html = cliente.get("/").text
    for campo in re.findall(r'<input[^>]*type="file"[^>]*>', html):
        assert "accept" not in campo


def test_yo_incluye_version(cliente):
    assert cliente.get("/api/yo").json()["version"] == "local"
