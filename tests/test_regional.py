"""Anestesia regional: imágenes propias por bloqueo y dosis máximas (datos ficticios)."""
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import auth, main
from tests.test_api import cliente  # noqa: F401  (fixture)

ARCHIVO = Path(__file__).resolve().parents[1] / "app" / "static" / "regional.js"


def png_con_exif() -> bytes:
    img = Image.new("RGB", (2400, 1200), (40, 40, 40))
    exif = Image.Exif()
    exif[0x010F] = "Ecografo de prueba"   # fabricante
    salida = io.BytesIO()
    img.save(salida, "JPEG", exif=exif)
    return salida.getvalue()


@pytest.fixture
def admin(cliente):
    from app.repositorio import conectar
    with conectar() as c:
        c.execute("UPDATE anestesiologo SET es_admin = TRUE WHERE anestesiologo_id = 1")
        c.commit()
    return cliente


def test_imagenes_propias_por_bloqueo(admin, conn):
    c = admin
    assert c.get("/api/regional/imagenes").json() == []
    r = c.post("/api/regional/imagenes", data={"bloque": "interescalenico", "descripcion": "Raíces C5–C7"},
               files={"archivo": ("eco.jpg", png_con_exif(), "image/jpeg")})
    assert r.status_code == 201, r.text
    iid = r.json()["imagen_id"]
    assert [i["bloque"] for i in c.get("/api/regional/imagenes").json()] == ["interescalenico"]
    img = c.get(f"/api/regional/imagenes/{iid}")
    assert img.headers["content-type"] == "image/jpeg"
    abierta = Image.open(io.BytesIO(img.content))
    assert max(abierta.size) == 1600 and not abierta.getexif()      # reducida y sin metadatos
    # no es imagen / bloque inválido
    assert c.post("/api/regional/imagenes", data={"bloque": "tap"}, files={"archivo": ("x.jpg", b"hola", "image/jpeg")}).status_code == 415
    assert c.post("/api/regional/imagenes", data={"bloque": "TAP; drop"}, files={"archivo": ("x.jpg", png_con_exif(), "image/jpeg")}).status_code == 422
    # otro anestesiólogo la ve pero no puede subir ni borrar
    conn.execute("INSERT INTO anestesiologo (nombre, email) VALUES ('Otro', 'otro@x.co')")
    conn.commit()
    otro = TestClient(main.app)
    otro.cookies.set(auth.COOKIE, auth.crear_sesion(2))
    assert otro.get(f"/api/regional/imagenes/{iid}").status_code == 200
    assert otro.delete(f"/api/regional/imagenes/{iid}").status_code == 403
    assert otro.post("/api/regional/imagenes", data={"bloque": "tap"}, files={"archivo": ("e.jpg", png_con_exif(), "image/jpeg")}).status_code == 403
    assert c.delete(f"/api/regional/imagenes/{iid}").status_code == 204
    assert c.get(f"/api/regional/imagenes/{iid}").status_code == 404


@pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado")
def test_dosis_maximas_y_datos():
    programa = f"""const R = require({json.dumps(str(ARCHIVO))});
      console.log(JSON.stringify({{
        ropi: R.dosisMaxima("ropivacaina", 70, 0.375), bupi: R.dosisMaxima("bupivacaina", 90, 0.25),
        lidoEpi: R.dosisMaxima("lidocaina", 70, 2, true), sinPeso: R.dosisMaxima("ropivacaina", 0, 0.5),
        lipido: R.rescateLipidico(20), lipidoAdulto: R.rescateLipidico(80),
        bloqueos: R.BLOQUEOS.map((b) => [b.id, b.region, !!(b.nombre && b.volumen && b.anestesico && b.nysora)]),
        regiones: R.REGIONES.map((r) => r[0]) }}));"""
    r = json.loads(subprocess.run(["node", "-e", programa], capture_output=True, text=True, check=True).stdout)
    assert r["ropi"] == {"mg": 210, "mgkg": 3, "porTope": False, "ml": 56, "mgPorMl": 3.75}   # 3 mg/kg · 70 kg
    assert r["bupi"]["mg"] == 175 and r["bupi"]["porTope"] is True and r["bupi"]["ml"] == 70  # tope de 175 mg
    assert r["lidoEpi"]["mg"] == 490 and r["sinPeso"] is None
    assert r["lipido"]["bolo"].startswith("30 mL") and r["lipidoAdulto"]["bolo"].startswith("100 mL")
    ids = [b[0] for b in r["bloqueos"]]
    assert len(ids) == len(set(ids)) >= 25
    assert all(ok and region in r["regiones"] for _, region, ok in r["bloqueos"])
