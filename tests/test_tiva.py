"""Simulador de TIVA (app/static/tiva.js): parámetros de los modelos contra los valores publicados y la simulación.
Se ejecuta con Node; si no está instalado, se omite."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ARCHIVO = Path(__file__).resolve().parents[1] / "app" / "static" / "tiva.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado")


def js(codigo: str):
    programa = f"const T = require({json.dumps(str(ARCHIVO))});\nconsole.log(JSON.stringify((() => {{ {codigo} }})()));"
    return json.loads(subprocess.run(["node", "-e", programa], capture_output=True, text=True, check=True).stdout)


def params(modelo, **p):
    return js(f"const k = T.MODELOS[{json.dumps(modelo)}].calcular({json.dumps(p)});"
              "return { v1: k.v1, v2: k.v2, v3: k.v3, cl: k.k10 * k.v1, q2: k.k12 * k.v1, q3: k.k13 * k.v1, ke0: k.ke0 };")


REF = dict(edad=35, peso=70, talla=170, sexo="M")


def test_eleveld_propofol_individuo_de_referencia():
    sin = params("eleveld_propofol", **REF, opioide=False)
    assert sin["v1"] == pytest.approx(6.28) and sin["v2"] == pytest.approx(25.5) and sin["v3"] == pytest.approx(273)
    assert sin["cl"] == pytest.approx(1.79) and sin["q3"] == pytest.approx(1.11) and sin["ke0"] == pytest.approx(0.146)
    con = params("eleveld_propofol", **REF, opioide=True)       # el opioide reduce V3 y CL según la edad
    assert con["v3"] == pytest.approx(273 * 2.718281828 ** (-0.0138 * 35))
    assert con["cl"] == pytest.approx(1.79 * 2.718281828 ** (-0.00286 * 35))


def test_eleveld_remifentanilo_individuo_de_referencia():
    r = params("eleveld_remi", **REF)
    assert [round(r[k], 3) for k in ("v1", "v2", "v3", "cl", "q2", "q3", "ke0")] == [5.81, 8.82, 5.03, 2.58, 1.72, 0.124, 1.09]


def test_schnider_minto_marsh():
    s = params("schnider", edad=53, peso=77, talla=177, sexo="M")
    lbm = 1.1 * 77 - 128 * (77 / 177) ** 2
    assert s["v1"] == pytest.approx(4.27) and s["v2"] == pytest.approx(18.9) and s["v3"] == pytest.approx(238)
    assert s["cl"] == pytest.approx(1.89 - 0.0681 * (lbm - 59)) and s["ke0"] == pytest.approx(0.456)
    m = params("minto", edad=40, peso=70, talla=170, sexo="M")
    lbm = 1.1 * 70 - 128 * (70 / 170) ** 2
    assert m["v1"] == pytest.approx(5.1 + 0.072 * (lbm - 55)) and m["ke0"] == pytest.approx(0.595)
    assert params("marsh", peso=70)["v1"] == pytest.approx(15.96)
    assert params("marsh_mod", peso=70)["ke0"] == 1.2


def test_simulacion_exacta():
    r = js("""const k = T.MODELOS.marsh.calcular({ peso: 90 });
      let x = T.avanzar([200, 0, 0, 0], T.paso(k, 1), 0);           // bolo de 200 mg, un minuto después
      const Q = T.paso(k, 60); let y = [0, 0, 0, 0];
      for (let i = 0; i < 24 * 30; i++) y = T.avanzar(y, Q, 10);    // 10 mg/min durante 30 días: estado estable
      return { cp1: x[0] / k.v1, ss: y[0] / k.v1, ce: y[3], esperado: 10 / (k.k10 * k.v1) };""")
    assert round(r["cp1"], 2) == 7.44                    # mismo valor que jsTCI
    assert r["ss"] == pytest.approx(r["esperado"], rel=1e-6) and r["ce"] == pytest.approx(r["esperado"], rel=1e-6)


def test_tci_en_sitio_efecto_y_plasma():
    r = js("""const k = T.MODELOS.schnider.calcular({ edad: 40, peso: 70, talla: 170, sexo: "M" });
      const s = T.planTCI(k, { objetivos: [{ min: 0, valor: 3 }, { min: 60, valor: 2 }], modo: "efecto", duracion: 90,
                               concJeringa: 10, velocidadMax: 1200, despues: 30 });
      const en = (t) => s.find((z) => z.t >= t);
      const p = T.planTCI(k, { objetivos: [{ min: 0, valor: 4 }], modo: "plasma", duracion: 20, concJeringa: 10 });
      return { pico: Math.max(...s.filter((z) => z.t < 60).map((z) => z.ce)), ce5: en(5).ce, ce30: en(30).ce, cp30: en(30).cp,
               ce75: en(75).ce, pico2: Math.max(...s.filter((z) => z.t > 70 && z.t < 90).map((z) => z.ce)),
               despertar: T.tiempoHasta(s, 90, 1.2), cpMax: Math.max(...p.map((z) => z.cp)), cp2: p.find((z) => z.t >= 2).cp,
               negativas: s.some((z) => z.velocidad < 0) };""")
    assert r["pico"] == pytest.approx(3, abs=0.03)        # sin sobrepasar el objetivo
    assert r["ce5"] == pytest.approx(3, abs=0.03) and r["ce30"] == pytest.approx(3, abs=0.01) and r["cp30"] == pytest.approx(3, abs=0.05)
    assert r["ce75"] == pytest.approx(2, abs=0.02) and r["pico2"] <= 2.03
    assert 3 < r["despertar"] < 30 and r["negativas"] is False
    assert r["cpMax"] == pytest.approx(4, abs=0.02) and r["cp2"] == pytest.approx(4, abs=0.02)


def test_validaciones():
    r = js("""return { obesa: T.validar("schnider", { edad: 45, peso: 150, talla: 165, sexo: "F" }),
                       falta: T.validar("eleveld_propofol", { edad: 30, peso: 80 }),
                       nino: T.validar("paedfusor", { edad: 30, peso: 80 }),
                       ok: T.validar("eleveld_propofol", { edad: 30, peso: 80, talla: 175, sexo: "M" }) };""")
    assert "masa magra" in r["obesa"]["errores"][0]
    assert r["falta"]["errores"] == ["Falta la talla.", "Falta el sexo."]
    assert r["nino"]["avisos"] and r["ok"] == {"errores": [], "avisos": []}
