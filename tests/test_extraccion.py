import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from app import extraccion

RESPUESTA = {
    "paciente": {"tipo_documento": "CC", "numero_documento": "1020304050", "nombres": "María", "apellidos": "Gómez"},
    "aseguradora": {"nombre": "Sura", "tipo": "EPS", "numero_poliza": None, "plan": None},
    "clinica": {"nombre": "Clínica Las Américas", "ciudad": "Medellín"},
    "procedimientos": [{"codigo": "471100", "nombre": "Apendicectomía", "es_principal": True}],
    "fecha_procedimiento": "2026-10-15",
    "confianza": 0.93,
    "campos_dudosos": ["paciente.numero_documento"],
    "observaciones": None,
}


class ClienteFalso:
    def __init__(self, texto=json.dumps(RESPUESTA), stop_reason="end_turn"):
        self.llamadas = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self._respuesta = SimpleNamespace(stop_reason=stop_reason,
                                          content=[SimpleNamespace(type="text", text=texto)])

    def _create(self, **kwargs):
        self.llamadas.append(kwargs)
        return self._respuesta


def foto(ancho=800, alto=600, formato="JPEG"):
    buf = io.BytesIO()
    Image.new("RGB", (ancho, alto), "white").save(buf, format=formato)
    return buf.getvalue()


def test_pdf_se_envia_como_documento():
    cliente = ClienteFalso()
    orden = extraccion.extraer_orden(b"%PDF-1.7 ...", "application/pdf", client=cliente)
    bloque = cliente.llamadas[0]["messages"][0]["content"][0]
    assert bloque["type"] == "document" and bloque["source"]["media_type"] == "application/pdf"
    assert orden.paciente.numero_documento == "1020304050"
    assert orden.procedimientos[0].codigo == "471100"
    assert str(orden.fecha_procedimiento) == "2026-10-15"


def test_solicitud_usa_salida_estructurada_y_fallback():
    cliente = ClienteFalso()
    extraccion.extraer_orden(foto(), "image/jpeg", client=cliente)
    kw = cliente.llamadas[0]
    assert kw["output_config"]["format"]["schema"] is extraccion.ESQUEMA
    assert kw["fallbacks"] == "default"
    assert kw["messages"][0]["content"][0]["type"] == "image"


def test_foto_grande_se_reduce():
    datos, tipo = extraccion.preparar_imagen(foto(5000, 3000, "PNG"))
    img = Image.open(io.BytesIO(datos))
    assert tipo == "image/jpeg" and max(img.size) <= extraccion.MAX_LADO_PX


def test_rechazo_lanza_error():
    with pytest.raises(extraccion.ExtraccionError):
        extraccion.extraer_orden(foto(), "image/jpeg", client=ClienteFalso(stop_reason="refusal"))


def test_tipo_no_soportado():
    with pytest.raises(extraccion.ExtraccionError):
        extraccion.extraer_orden(b"hola", "text/plain", client=ClienteFalso())


def test_esquema_exige_todos_los_campos():
    """La salida estructurada exige required + additionalProperties=false en cada objeto."""
    def revisar(nodo):
        if isinstance(nodo, dict):
            if nodo.get("type") == "object":
                assert nodo["additionalProperties"] is False
                assert set(nodo["required"]) == set(nodo["properties"])
            for v in nodo.values():
                revisar(v)
        elif isinstance(nodo, list):
            for v in nodo:
                revisar(v)
    revisar(extraccion.ESQUEMA)


def test_foto_heic_se_convierte_a_jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), "white").save(buf, format="HEIF")
    cliente = ClienteFalso()
    extraccion.extraer_orden(buf.getvalue(), "image/heic", client=cliente)
    bloque = cliente.llamadas[0]["messages"][0]["content"][0]
    assert bloque["type"] == "image" and bloque["source"]["media_type"] == "image/jpeg"


def test_clave_invalida_da_mensaje_claro():
    import anthropic
    import httpx

    class ClienteSinClave(ClienteFalso):
        def _create(self, **kwargs):
            r = httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
            raise anthropic.AuthenticationError("invalid x-api-key", response=r, body=None)

    with pytest.raises(extraccion.ExtraccionError, match="ANTHROPIC_API_KEY"):
        extraccion.extraer_orden(b"%PDF-1.7", "application/pdf", client=ClienteSinClave())
