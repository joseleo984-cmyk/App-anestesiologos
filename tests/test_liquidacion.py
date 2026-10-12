"""Liquidación del volante de AP: fórmula verificada contra un volante real (solo montos)."""
import json
from decimal import Decimal

from app import extraccion, liquidacion
from app.modelos import VolanteExtraido
from tests.test_extraccion import ClienteFalso
from tests.test_api import cliente  # noqa: F401  (fixture)
from tests.test_pagos import REPORTE, con_reporte, subir  # noqa: F401  (fixtures)

VOLANTE_OCTUBRE = {  # valores del volante de octubre de 2026 que entregó AP
    "fecha_proceso": "2026-10-06", "periodo_desde": "2026-10-01", "periodo_hasta": "2026-10-31",
    "probienestar": 1614308, "compensacion_ordinaria": 1750905, "compensacion_extraordinaria": 1156579,
    "auxilio_sindical": 1938323, "cuatro_por_mil": 19383, "cuota_sostenimiento": 87545,
    "salud": 116299, "pension": 116299, "neto": 4506281, "otros": [],
}


def test_formula_cuadra_con_el_volante_de_octubre():
    l = liquidacion.liquidar(Decimal("8071542"), 2026)
    assert l["base_contrato"] == 5512863 and l["seguridad_social"] == 667056 and l["distribuir"] == 4845807
    for clave, _, _ in liquidacion.CONCEPTOS:
        if clave != "neto":
            esperado = l["devengados"].get(clave, l["deducciones"].get(clave))
            assert esperado == VOLANTE_OCTUBRE[clave], clave
    assert l["neto"] == 4506281 and l["alertas"] == []
    d = l["devengados"]
    assert d["compensacion_ordinaria"] + d["compensacion_extraordinaria"] + d["auxilio_sindical"] == l["distribuir"]


def test_recaudo_bajo_avisa():
    l = liquidacion.liquidar(Decimal("4340232"), 2026)   # el ejemplo de la propuesta
    d = l["devengados"]
    assert d["compensacion_ordinaria"] == 1750905 and d["compensacion_extraordinaria"] == 0
    assert d["auxilio_sindical"] == 854784 and l["deducciones"]["salud"] == 70036
    assert len(l["alertas"]) == 2 and "4.860.733" in l["alertas"][0] and "42.898" in l["alertas"][1]
    muy_bajo = liquidacion.liquidar(Decimal("1000000"), 2026)  # ni siquiera alcanza el mínimo
    assert muy_bajo["devengados"]["auxilio_sindical"] == 0
    assert muy_bajo["devengados"]["compensacion_ordinaria"] == muy_bajo["distribuir"]


def test_liquidacion_y_comparacion_por_api(con_reporte, monkeypatch):
    c = con_reporte
    c.poner_reporte({**REPORTE, "total_neto": 8071542})
    reporte_id = subir(c).json()["reporte_id"]
    l = c.get(f"/api/pagos/{reporte_id}/liquidacion").json()
    assert Decimal(l["neto"]) == 4506281

    monkeypatch.setattr(extraccion, "extraer_volante", lambda d, t: VolanteExtraido.model_validate(VOLANTE_OCTUBRE))
    r = c.post(f"/api/pagos/{reporte_id}/volante", files={"archivo": ("v.pdf", b"%PDF-1.7 v", "application/pdf")})
    assert r.status_code == 200, r.text
    assert {f["estado"] for f in r.json()["comparacion"]} == {"COINCIDE"} and r.json()["avisos"] == []

    distinto = {**VOLANTE_OCTUBRE, "auxilio_sindical": 1900000, "periodo_hasta": "2026-09-30",
                "otros": [{"concepto": "PRESTAMO", "devengado": None, "deducido": 50000}]}
    monkeypatch.setattr(extraccion, "extraer_volante", lambda d, t: VolanteExtraido.model_validate(distinto))
    r = c.post(f"/api/pagos/{reporte_id}/volante", files={"archivo": ("v.pdf", b"%PDF-1.7 v2", "application/pdf")})
    filas = {f["concepto"]: f for f in r.json()["comparacion"]}
    assert filas["Auxilio sindical"]["estado"] == "DIFERENTE" and Decimal(filas["Auxilio sindical"]["diferencia"]) == -38323
    assert len(r.json()["avisos"]) == 2   # otro mes y un concepto que no se calcula

    monkeypatch.setattr(extraccion, "extraer_volante", lambda d, t: VolanteExtraido())
    r = c.post(f"/api/pagos/{reporte_id}/volante", files={"archivo": ("v.pdf", b"%PDF-1.7 v3", "application/pdf")})
    assert r.status_code == 422
    assert c.get("/api/pagos/999999/liquidacion").status_code == 404


def test_lectura_del_volante_con_claude():
    cliente = ClienteFalso(texto=json.dumps(VOLANTE_OCTUBRE))
    v = extraccion.extraer_volante(b"%PDF-1.7", "application/pdf", client=cliente)
    assert v.neto == 4506281 and v.periodo_hasta.month == 10
    esquema = cliente.llamadas[0]["output_config"]["format"]["schema"]
    assert "auxilio_sindical" in esquema["required"]
