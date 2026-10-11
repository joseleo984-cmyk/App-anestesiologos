"""Clínicas: sugeridas al escribir, sin duplicados por tildes o mayúsculas."""
from app import extraccion
from app.modelos import OrdenExtraida
from tests.test_api import CONFIRMAR, cliente  # noqa: F401  (fixture)
from tests.test_extraccion import RESPUESTA, foto


def guardar(cliente, nombre, ciudad="Barranquilla"):
    r = cliente.post("/api/cirugias", json={**CONFIRMAR, "clinica": {"nombre": nombre, "ciudad": ciudad}})
    assert r.status_code == 201, r.text


def test_misma_clinica_con_o_sin_tildes(cliente):
    guardar(cliente, "Clínica del Caribe")
    guardar(cliente, "CLINICA  DEL CARIBE")
    guardar(cliente, "clinica del caribe", ciudad="barranquilla")
    guardar(cliente, "Clínica del Caribe", ciudad="Santa Marta")  # otra ciudad, otra sede
    clinicas = cliente.get("/api/clinicas").json()
    assert [(c["nombre"], c["ciudad"]) for c in clinicas] == [("CLÍNICA DEL CARIBE", "BARRANQUILLA"),
                                                              ("CLÍNICA DEL CARIBE", "SANTA MARTA")]


def leer(cliente, monkeypatch, nombre, ciudad=None, n=1):
    datos = {**RESPUESTA, "clinica": {"nombre": nombre, "ciudad": ciudad}}
    monkeypatch.setattr(extraccion, "extraer_orden", lambda archivos: OrdenExtraida.model_validate(datos))
    r = cliente.post("/api/documentos", files={"archivo": ("orden.jpg", foto(300 + n, 200), "image/jpeg")})
    assert r.status_code == 201, r.text
    return r.json()["datos"]


def test_clinica_leida_toma_el_nombre_registrado(cliente, monkeypatch):
    guardar(cliente, "Clínica del Caribe")
    guardar(cliente, "Clínica Portoazul")
    datos = leer(cliente, monkeypatch, "Clinica del Caribe S.A.S.", n=1)
    assert datos["clinica"] == {"nombre": "CLÍNICA DEL CARIBE", "ciudad": "BARRANQUILLA"}
    assert "clinica.nombre" in datos["campos_dudosos"]
    assert leer(cliente, monkeypatch, "CLINICA PORTO AZUL", n=2)["clinica"]["nombre"] == "CLÍNICA PORTOAZUL"
    # Nada parecido, o demasiado genérico: se deja como la leyó la IA
    assert leer(cliente, monkeypatch, "Clínica La Merced", n=3)["clinica"]["nombre"] == "Clínica La Merced"
    assert leer(cliente, monkeypatch, "Clínica", n=4)["clinica"]["nombre"] == "Clínica"


def test_desempate_entre_clinicas_parecidas(cliente, monkeypatch):
    guardar(cliente, "Clínica Portoazul (Auna)")
    guardar(cliente, "Sabbag Radiólogos - Sede Portoazul Torre Sabbag")
    guardar(cliente, "Clínica del Norte Sede 1")
    guardar(cliente, "Clínica del Norte Sede 2")
    assert leer(cliente, monkeypatch, "Clínica Portoazul", n=1)["clinica"]["nombre"] == "CLÍNICA PORTOAZUL (AUNA)"
    assert leer(cliente, monkeypatch, "Sabbag Radiologos", n=2)["clinica"]["nombre"] == \
        "SABBAG RADIÓLOGOS - SEDE PORTOAZUL TORRE SABBAG"
    # Ventaja poco clara: se deja como la leyó la IA
    assert leer(cliente, monkeypatch, "Norte", n=3)["clinica"]["nombre"] == "Norte"
