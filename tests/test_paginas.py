"""Órdenes en varias fotos o páginas, y la ciudad de la clínica."""
import pytest

from app import extraccion
from app.modelos import OrdenExtraida
from tests.test_api import CONFIRMAR, cliente  # noqa: F401  (fixture)
from tests.test_extraccion import RESPUESTA, ClienteFalso, foto


def varios(*contenidos):
    return [("archivos", (f"pagina{i}.{'pdf' if c.startswith(b'%PDF') else 'jpg'}", c,
                          "application/pdf" if c.startswith(b"%PDF") else "image/jpeg"))
            for i, c in enumerate(contenidos, start=1)]


def test_orden_en_varias_fotos(cliente):
    paginas = [foto(300, 200), foto(320, 200), b"%PDF-1.7 autorizacion"]
    r = cliente.post("/api/documentos", files=varios(*paginas))
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["paginas"] == 3
    assert cliente.llamadas == ["image/jpeg", "image/jpeg", "application/pdf"]  # se leen juntas, en orden
    for numero, contenido in enumerate(paginas, start=1):
        assert cliente.get(f"/api/documentos/{doc['documento_id']}/archivo?pagina={numero}").content == contenido
    assert cliente.get(f"/api/documentos/{doc['documento_id']}/archivo?pagina=4").status_code == 404

    cid = cliente.post(f"/api/documentos/{doc['documento_id']}/confirmar", json=CONFIRMAR).json()["cirugia_id"]
    assert cliente.get(f"/api/cirugias/{cid}").json()["paginas"] == 3
    assert cliente.post("/api/documentos", files=varios(*paginas)).status_code == 409  # la misma orden otra vez


def test_limite_de_fotos(cliente):
    r = cliente.post("/api/documentos", files=varios(*[foto(300 + i, 200) for i in range(9)]))
    assert r.status_code == 413 and cliente.llamadas == []


def test_una_sola_foto_sigue_igual(cliente):
    doc = cliente.post("/api/documentos", files={"archivo": ("orden.jpg", foto(), "image/jpeg")}).json()
    assert doc["paginas"] == 1
    assert cliente.get(f"/api/documentos/{doc['documento_id']}/archivo").status_code == 200
    cid = cliente.post(f"/api/documentos/{doc['documento_id']}/confirmar", json=CONFIRMAR).json()["cirugia_id"]
    assert cliente.get(f"/api/cirugias/{cid}").json()["paginas"] == 1
    sin_foto = cliente.post("/api/cirugias", json=CONFIRMAR).json()["cirugia_id"]
    assert cliente.get(f"/api/cirugias/{sin_foto}").json()["paginas"] == 0


def test_lectura_conjunta_con_claude():
    cliente = ClienteFalso()
    extraccion.extraer_orden([(foto(), "image/jpeg"), (b"%PDF-1.7", "application/pdf")], client=cliente)
    contenido = cliente.llamadas[0]["messages"][0]["content"]
    assert [b["type"] for b in contenido] == ["image", "document", "text"]
    assert "MISMA orden" in contenido[-1]["text"]


@pytest.fixture
def orden_sin_ciudad(cliente, monkeypatch):
    def lectura(ciudad):
        datos = {**RESPUESTA, "clinica": {"nombre": "Clínica del Caribe", "ciudad": ciudad}}
        monkeypatch.setattr(extraccion, "extraer_orden", lambda archivos: OrdenExtraida.model_validate(datos))
    cliente.lectura = lectura
    return cliente


def test_ciudad_de_la_clinica_ya_conocida(orden_sin_ciudad):
    c = orden_sin_ciudad
    c.post("/api/cirugias", json={**CONFIRMAR, "clinica": {"nombre": "clínica del caribe", "ciudad": "Barranquilla"}})
    c.lectura(None)
    assert c.post("/api/documentos", files=varios(foto(301, 200))).json()["datos"]["clinica"]["ciudad"] == "BARRANQUILLA"
    c.lectura("Santa Marta")  # si la orden trae la ciudad, se respeta
    assert c.post("/api/documentos", files=varios(foto(302, 200))).json()["datos"]["clinica"]["ciudad"] == "Santa Marta"


def test_clinica_nueva_sin_ciudad_queda_vacia(orden_sin_ciudad):
    orden_sin_ciudad.lectura(None)
    assert orden_sin_ciudad.post("/api/documentos", files=varios(foto())).json()["datos"]["clinica"]["ciudad"] is None


def test_instruccion_de_no_deducir_la_ciudad():
    assert "no la deduzcas" in extraccion.INSTRUCCIONES
