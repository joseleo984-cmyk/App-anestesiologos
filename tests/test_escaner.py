"""Escáner de documentos: detecta la hoja, la endereza y mejora el contraste (imagen sintética, sin datos reales)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ARCHIVO = Path(__file__).resolve().parents[1] / "app" / "static" / "escaner.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado")

# Foto sintética 600x450: mesa oscura, hoja clara inclinada con sombra de un lado y líneas de texto oscuras.
PREPARAR = """
const E = require(%r);
const W = 600, H = 450;
const hoja = [{x: 90, y: 60}, {x: 520, y: 90}, {x: 490, y: 400}, {x: 70, y: 370}];  // TL, TR, BR, BL
function dentro(px, py, p) {
  let c = false;
  for (let i = 0, j = 3; i < 4; j = i++)
    if ((p[i].y > py) !== (p[j].y > py) && px < (p[j].x - p[i].x) * (py - p[i].y) / (p[j].y - p[i].y) + p[i].x) c = !c;
  return c;
}
const data = new Uint8ClampedArray(W * H * 4);
for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
  const o = (y * W + x) * 4;
  let v = 40;
  if (dentro(x, y, hoja)) {
    v = 245 - 60 * (x / W);                                  // sombra: más oscura a la derecha
    if (y %% 24 < 3 && x > 120 && x < 440) v = 40;           // líneas de texto
  }
  data[o] = v; data[o + 1] = v; data[o + 2] = v; data[o + 3] = 255;
}
const img = {data, width: W, height: H};
""" % str(ARCHIVO)


def node(cuerpo: str):
    r = subprocess.run(["node", "-e", PREPARAR + cuerpo], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_detecta_las_esquinas_de_la_hoja():
    r = node("const d = E.detectarHoja(img); console.log(JSON.stringify({d: d.detectada, e: d.esquinas, h: hoja}));")
    assert r["d"] is True
    for e, h in zip(r["e"], r["h"]):
        assert abs(e["x"] - h["x"]) < 14 and abs(e["y"] - h["y"]) < 14


def test_sin_hoja_clara_devuelve_el_marco_completo():
    r = node("""
      for (let i = 0; i < data.length; i += 4) { data[i] = data[i+1] = data[i+2] = 128; }
      const d = E.detectarHoja(img); console.log(JSON.stringify({d: d.detectada, e: d.esquinas}));""")
    assert r["d"] is False and len(r["e"]) == 4


def test_endereza_y_deja_el_papel_blanco_aunque_haya_sombra():
    r = node("""
      const d = E.detectarHoja(img);
      const recta = E.enderezar(img, d.esquinas, 800);
      const esc = E.mejorar(recta, "escaner");
      const prom = (x0, x1) => { const v = [];   // mediana: ignora los renglones de texto
        for (let y = 5; y < 15; y++) for (let x = Math.floor(esc.width * x0); x < Math.floor(esc.width * x1); x++) v.push(esc.data[(y * esc.width + x) * 4]);
        return v.sort((a, b) => a - b)[v.length >> 1]; };
      let oscuros = 0; for (let i = 0; i < esc.data.length; i += 4) if (esc.data[i] < 100) oscuros++;
      console.log(JSON.stringify({w: recta.width, h: recta.height, izq: prom(0.05, 0.15), der: prom(0.85, 0.95),
        oscuros: oscuros / (esc.width * esc.height)}));""")
    assert 400 < r["w"] < 470 and 290 < r["h"] < 340             # la hoja mide ~430x300 en la foto
    assert r["izq"] > 235 and r["der"] > 235                     # la sombra de la derecha desaparece
    assert 0.01 < r["oscuros"] < 0.25                            # las líneas de texto siguen ahí


def test_modo_color_conserva_el_color():
    r = node("""
      for (let i = 0; i < data.length; i += 4) if (data[i] > 100) { data[i] = 230; data[i+1] = 230; data[i+2] = 150; } // papel amarillento
      const col = E.mejorar(E.enderezar(img, E.detectarHoja(img).esquinas, 400), "color");
      const c = (col.height >> 1) * col.width * 4 + (col.width >> 1) * 4;
      console.log(JSON.stringify({r: col.data[c], b: col.data[c + 2]}));""")
    assert r["r"] > 235          # el fondo se aclara
