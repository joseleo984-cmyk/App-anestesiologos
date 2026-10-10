"""Código CUPS sugerido desde el Manual ISS cuando la orden trae solo el nombre del procedimiento."""
from app import catalogo, extraccion
from app.modelos import OrdenExtraida
from tests.test_api import cliente  # noqa: F401  (fixture)
from tests.test_extraccion import RESPUESTA, foto


def test_coincidencia_clara_pone_el_codigo():
    elegido, sugerencias = catalogo.codigo_probable("Apendicectomía")
    assert elegido["codigo"] == "471100"
    assert sugerencias[0]["codigo"] == "471100"
    assert catalogo.codigo_probable("colecistectomia laparoscopica")[0]["codigo"] == "512104"


def test_nombre_ambiguo_solo_muestra_opciones():
    elegido, sugerencias = catalogo.codigo_probable("CESAREA")
    assert elegido is None and len(sugerencias) >= 2


def test_no_sugiere_paquetes_ni_servicios():
    for nombre in ("anestesiologia", "apendicectomia", "cesarea"):
        assert not any(s["codigo"].startswith(catalogo.NO_PROCEDIMIENTOS) for s in catalogo.buscar(nombre))
    assert catalogo.por_codigo("S41201")["descripcion"] == "ESPECIALISTAS EN ANESTESIOLOGÍA"  # pero sí lo conoce


def test_descarta_parecidos_lejanos():
    assert all(s["puntaje"] >= catalogo.MINIMO for s in catalogo.buscar("cesarea"))
    assert not any(s["codigo"].startswith("90") for s in catalogo.buscar("cesarea"))  # "UREA" no es cesárea


def test_texto_corto_no_busca():
    assert catalogo.codigo_probable("ab") == (None, [])


def test_orden_sin_codigo_recibe_sugerencia(cliente, monkeypatch):
    datos = {**RESPUESTA, "procedimientos": [{"nombre": "Apendicectomía", "es_principal": True},
                                             {"nombre": "Cesárea"},
                                             {"codigo": "999999", "nombre": "Apendicectomía"}]}
    monkeypatch.setattr(extraccion, "extraer_orden", lambda archivos: OrdenExtraida.model_validate(datos))
    r = cliente.post("/api/documentos", files={"archivo": ("orden.jpg", foto(), "image/jpeg")})
    assert r.status_code == 201, r.text
    orden = r.json()["datos"]
    apendice, cesarea, con_codigo = orden["procedimientos"]
    assert apendice["codigo"] == "471100" and apendice["codigo_sugerido"]
    assert cesarea["codigo"] is None and not cesarea["codigo_sugerido"] and cesarea["sugerencias"]
    assert con_codigo["codigo"] == "999999" and not con_codigo["codigo_sugerido"]  # el de la orden no se toca
    assert {"procedimientos[0].codigo", "procedimientos[1].codigo"} <= set(orden["campos_dudosos"])
    assert "procedimientos[2].codigo" not in orden["campos_dudosos"]


def test_buscar_procedimientos(cliente):
    por_nombre = cliente.get("/api/procedimientos", params={"q": "apendicectomia"}).json()
    assert por_nombre[0]["codigo"] == "471100"
    por_codigo = cliente.get("/api/procedimientos", params={"q": "4711"}).json()
    assert any(p["codigo"] == "471100" for p in por_codigo)
    assert cliente.get("/api/procedimientos", params={"q": "a"}).status_code == 422
