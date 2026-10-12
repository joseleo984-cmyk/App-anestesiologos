"""Liquidación del volante de AP: fórmula verificada contra un volante real (solo montos)."""
import json

import pytest
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
    "salud": 116299, "pension": 116299, "ajuste_sindical": None, "neto": 4506281, "otros": [],
}


def test_formula_cuadra_con_el_volante_de_octubre():
    l = liquidacion.liquidar(Decimal("8071542"), 2026)
    assert l["base_contrato"] == 5512863 and l["seguridad_social"] == 667056 and l["distribuir"] == 4845807
    for clave, _, _ in liquidacion.CONCEPTOS:
        if clave != "neto":
            esperado = l["devengados"].get(clave, l["deducciones"].get(clave))
            assert esperado == (VOLANTE_OCTUBRE.get(clave) or 0), clave
    assert l["neto"] == 4506281 and l["alertas"] == []
    d = l["devengados"]
    assert d["compensacion_ordinaria"] + d["compensacion_extraordinaria"] + d["auxilio_sindical"] == l["distribuir"]


# Volantes reales de abril a octubre de 2026 (solo montos). Recaudo: el neto total de la relación de
# pacientes del mes (abril, mayo y octubre) o, en los demás, el fondo probienestar / 20 %.
VOLANTES_2026 = {
    #       recaudo,  ordinaria, extraord.,  auxilio, 4xmil, cuota,  salud,  ajuste, retención, neto
    "abr": (10185757, 1750905, 1918149, 2446036, 24460, 87545, 146762, 0, 0, 5709561),
    "may": (4276350, 1750905, 816431, 0, 10269, 87545, 70036, 46650, 0, 2282800),
    "jun": (15524880, 1750905, 3841378, 3728188, 37282, 87545, 223691, 0, 319000, 8429262),
    "jul": (7305415, 1750905, 880610, 1754343, 17543, 87545, 105261, 0, 0, 4070248),
    "ago": (13602120, 1750905, 3148772, 3266451, 32665, 87545, 195987, 0, 162000, 7491944),
    "sep": (4244870, 1750905, 797530, 0, 10194, 87545, 70036, 49260, 0, 2261364),
    "oct": (8071542, 1750905, 1156579, 1938323, 19383, 87545, 116299, 0, 0, 4506281),
}


@pytest.mark.parametrize("mes", VOLANTES_2026)
def test_formula_cuadra_con_los_volantes_reales(mes):
    recaudo, ordi, extra, aux, cxm, cuota, salud, ajuste, retencion, neto = VOLANTES_2026[mes]
    volante = {"probienestar": round(recaudo * 0.2), "compensacion_ordinaria": ordi, "compensacion_extraordinaria": extra,
               "auxilio_sindical": aux, "cuatro_por_mil": cxm, "cuota_sostenimiento": cuota, "salud": salud,
               "pension": salud, "ajuste_sindical": ajuste, "neto": neto,
               "otros": [{"concepto": "RETENCION EN LA FUENTE", "devengado": None, "deducido": retencion}] if retencion else []}
    filas = liquidacion.comparar(liquidacion.liquidar(Decimal(recaudo), 2026), volante)
    malas = [(f["concepto"], f["calculado"], f["volante"]) for f in filas if f["estado"] not in ("COINCIDE", "OTRO")]
    assert malas == []


def test_recaudo_bajo():
    l = liquidacion.liquidar(Decimal("4276350"), 2026)   # mayo
    assert l["devengados"]["auxilio_sindical"] == 0 and l["deducciones"]["salud"] == 70036
    assert abs(l["deducciones"]["ajuste_sindical"] - 46650) <= 1
    assert len(l["alertas"]) == 1 and "4.860.733" in l["alertas"][0]
    assert liquidacion.liquidar(Decimal("8071542"), 2026)["deducciones"]["ajuste_sindical"] == 0
    muy_bajo = liquidacion.liquidar(Decimal("1000000"), 2026)  # ni siquiera alcanza el mínimo
    d = muy_bajo["devengados"]
    assert d["auxilio_sindical"] == 0 and d["compensacion_ordinaria"] == muy_bajo["distribuir"]


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
