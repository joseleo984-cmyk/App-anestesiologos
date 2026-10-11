"""Código CUPS sugerido desde el catálogo CUPS (Resolución 2706 de 2025) cuando la orden trae solo el nombre del procedimiento."""
from app import catalogo, extraccion
from app.modelos import OrdenExtraida
from tests.test_api import cliente  # noqa: F401  (fixture)
from tests.test_extraccion import RESPUESTA, foto


def test_coincidencia_clara_pone_el_codigo():
    elegido, sugerencias = catalogo.codigo_probable("Apendicectomía laparoscópica")
    assert elegido["codigo"] == "471110"
    assert sugerencias[0]["codigo"] == "471110"
    assert catalogo.codigo_probable("colecistectomia laparoscopica")[0]["codigo"] == "512104"
    assert catalogo.codigo_probable("Histerectomía abdominal total")[0]["codigo"] == "684003"


def test_nombre_ambiguo_solo_muestra_opciones():
    elegido, sugerencias = catalogo.codigo_probable("CESAREA")
    assert elegido is None and {"740001", "740002", "740003"} <= {s["codigo"] for s in sugerencias}
    elegido, sugerencias = catalogo.codigo_probable("Apendicectomía")  # ¿abierta o laparoscópica?
    assert elegido is None and {"471102", "471110"} <= {s["codigo"] for s in sugerencias}


def test_nombres_de_uso_diario():
    assert catalogo.buscar("Endoscopia digestiva alta")[0]["codigo"].startswith("4413")


def test_no_sugiere_laboratorio():
    for nombre in ("urea", "apendicectomia", "cesarea"):
        assert not any(s["codigo"].startswith(catalogo.NO_PROCEDIMIENTOS) for s in catalogo.buscar(nombre))
    assert catalogo.por_codigo("903856")  # pero sí lo encuentra por código


def test_descarta_parecidos_lejanos():
    assert all(s["puntaje"] >= catalogo.MINIMO for s in catalogo.buscar("cesarea"))
    assert not any(s["codigo"].startswith("90") for s in catalogo.buscar("cesarea"))  # "UREA" no es cesárea


def test_texto_corto_no_busca():
    assert catalogo.codigo_probable("ab") == (None, [])


def test_orden_sin_codigo_recibe_sugerencia(cliente, monkeypatch):
    datos = {**RESPUESTA, "procedimientos": [{"nombre": "Apendicectomía laparoscópica", "es_principal": True},
                                             {"nombre": "Cesárea"},
                                             {"codigo": "999999", "nombre": "Apendicectomía"}]}
    monkeypatch.setattr(extraccion, "extraer_orden", lambda archivos: OrdenExtraida.model_validate(datos))
    r = cliente.post("/api/documentos", files={"archivo": ("orden.jpg", foto(), "image/jpeg")})
    assert r.status_code == 201, r.text
    orden = r.json()["datos"]
    apendice, cesarea, con_codigo = orden["procedimientos"]
    assert apendice["codigo"] == "471110" and apendice["codigo_sugerido"]
    assert cesarea["codigo"] is None and not cesarea["codigo_sugerido"] and cesarea["sugerencias"]
    assert con_codigo["codigo"] == "999999" and not con_codigo["codigo_sugerido"]  # el de la orden no se toca
    assert {"procedimientos[0].codigo", "procedimientos[1].codigo"} <= set(orden["campos_dudosos"])
    assert "procedimientos[2].codigo" not in orden["campos_dudosos"]


def test_buscar_procedimientos(cliente):
    por_nombre = cliente.get("/api/procedimientos", params={"q": "apendicectomia"}).json()
    assert {p["codigo"] for p in por_nombre[:2]} == {"471102", "471110"}
    por_codigo = cliente.get("/api/procedimientos", params={"q": "4711"}).json()
    assert [p["codigo"] for p in por_codigo] == ["471102", "471110"]
    assert cliente.get("/api/procedimientos", params={"q": "a"}).status_code == 422
