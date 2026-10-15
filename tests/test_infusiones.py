"""Calculadora de infusiones (app/static/infusiones.js): fórmulas y datos de cada medicamento.
Se ejecuta con Node; si no está instalado, se omite."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ARCHIVO = Path(__file__).resolve().parents[1] / "app" / "static" / "infusiones.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado")


def js(codigo: str):
    programa = f"const I = require({json.dumps(str(ARCHIVO))});\nconsole.log(JSON.stringify((() => {{ {codigo} }})()));"
    salida = subprocess.run(["node", "-e", programa], capture_output=True, text=True, check=True).stdout
    return json.loads(salida)


def test_formulas():
    r = js("""const c = I.concentracion(4, "mg", 250);
      return { c, mlh: I.mlPorHora(0.1, "mcg/kg/min", 70, c), dosis: I.dosisDesde(26.25, "mcg/kg/min", 70, c),
               vaso: I.mlPorHora(0.04, "U/min", null, I.concentracion(20, "U", 100)),
               dexmed: I.mlPorHora(0.5, "mcg/kg/h", 80, I.concentracion(200, "mcg", 50)),
               fenil: I.mlPorHora(100, "mcg/min", null, I.concentracion(10, "mg", 250)),
               sinPeso: I.mlPorHora(0.1, "mcg/kg/min", null, 16),
               regla6: I.preparacionPorPeso(0.1, "mcg/kg/min", 10, 50),
               dopa: I.preparacionPorPeso(1, "mcg/kg/min", 10, 50) };""")
    assert r["c"] == 16                                    # 4 mg / 250 mL = 16 mcg/mL
    assert r["mlh"] == pytest.approx(26.25)                # 0,1 × 70 × 60 / 16
    assert r["dosis"] == pytest.approx(0.1)
    assert r["vaso"] == pytest.approx(12)                  # 0,04 U/min × 60 / 0,2 U/mL
    assert r["dexmed"] == pytest.approx(10)                # 0,5 × 80 / 4
    assert r["fenil"] == pytest.approx(150)                # 100 mcg/min × 60 / 40
    assert r["sinPeso"] is None
    assert r["regla6"] == {"cantidad": 3, "unidad": "mg"}  # 0,3 mg × kg en 50 mL → 1 mL/h = 0,1 mcg/kg/min
    assert r["dopa"] == {"cantidad": 30, "unidad": "mg"}   # 3 mg × kg en 50 mL → 1 mL/h = 1 mcg/kg/min


def test_datos_de_cada_medicamento():
    meds = js("return I.MEDICAMENTOS.map((m) => ({ id: m.id, cfg: [m.adulto, m.nino], pasos: [I.pasosDeDosis(m.adulto), I.pasosDeDosis(m.nino)] }));")
    assert len(meds) >= 12
    unidades = js("return Object.keys(I.UNIDADES);")
    for m in meds:
        for cfg, pasos in zip(m["cfg"], m["pasos"]):
            assert cfg["unidad"] in unidades, m["id"]
            assert 0 < cfg["r"][0] < cfg["r"][1] <= cfg["tope"], m["id"]
            assert cfg["p"] and all(c > 0 and u in ("mg", "mcg", "U") and v > 0 for c, u, v in cfg["p"]), m["id"]
            assert pasos == sorted(pasos) and pasos[0] >= cfg["r"][0] and pasos[-1] <= cfg["tope"], m["id"]
        assert m["cfg"][1]["porPeso"] > 0, m["id"]


def test_niveles():
    r = js("""const c = I.MEDICAMENTOS.find((m) => m.id === "norepinefrina").adulto;
      return [0.005, 0.1, 0.5, 0.8, 3].map((d) => I.nivel(d, c));""")
    assert r == ["BAJA", "USUAL", "USUAL", "ALTA", "TOPE"]
