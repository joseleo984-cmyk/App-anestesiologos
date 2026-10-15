"""Pantalla de Inicio (cartera) y recorrido del cobro de una cirugía (datos ficticios)."""
from datetime import date, timedelta

from app import cartera
from tests.test_api import CONFIRMAR, cliente  # noqa: F401  (fixture)

HOY = date.today()


def crear(cliente, documento, dias_atras, estado="REALIZADA", valor=None, fecha_pago=None, clinica=None):
    datos = {**CONFIRMAR, "fecha_procedimiento": str(HOY - timedelta(days=dias_atras)), "estado": estado,
             "valor_honorarios": valor, "fecha_pago": fecha_pago and str(fecha_pago),
             "paciente": {**CONFIRMAR["paciente"], "numero_documento": f"900{documento}"}}
    if clinica:
        datos["clinica"] = {"nombre": clinica, "ciudad": "Barranquilla"}
    r = cliente.post("/api/cirugias", json=datos)
    assert r.status_code == 201, r.text
    return r.json()["cirugia_id"]


def test_resumen_de_inicio(cliente):
    crear(cliente, "1", 10, valor=500000)                      # 0–90
    crear(cliente, "2", 120)                                   # 91–180, sin valor
    crear(cliente, "3", 300, valor=700000)                     # atrasada
    crear(cliente, "4", 5, estado="PAGADA", valor=900000, fecha_pago=HOY)
    crear(cliente, "5", -10, estado="PROGRAMADA", valor=1)     # futura: no cuenta
    crear(cliente, "6", 400, estado="CANCELADA")
    r = cliente.get("/api/inicio").json()
    assert r["cobrado_mes"] == 900000
    assert r["por_cobrar"] == {"cirugias": 3, "valor": 1200000, "sin_valor": 1}
    assert [f["cirugias"] for f in r["antiguedad"]] == [1, 1, 0, 1]
    assert r["atrasadas"] == 1 and r["sin_valor"] == 1 and r["por_aplicar"] == 0
    # Los filtros de los chips de la lista
    assert len(cliente.get("/api/cirugias?estado=ATRASADA").json()) == 1
    assert len(cliente.get("/api/cirugias?estado=SIN_VALOR").json()) == 1


def test_recorrido_del_cobro(cliente):
    pagadas = [crear(cliente, str(10 + i), 100 + i, estado="PAGADA", valor=100,
                     fecha_pago=HOY - timedelta(days=i), clinica="Clínica Ficticia") for i in range(3)]
    pendiente = crear(cliente, "20", 200, estado="FACTURADA", clinica="Clínica Ficticia")
    c = cliente.get(f"/api/cirugias/{pendiente}/cobro").json()
    assert [p["hecho"] for p in c["pasos"]] == [True, True, False, False]
    assert c["actual"] == "REPORTE" and c["dias"] == 200
    assert c["demora_tipica"] == 100 and c["demora_base"] == "CLINICA" and c["situacion"] == "DEMORADA"
    p = cliente.get(f"/api/cirugias/{pagadas[0]}/cobro").json()
    assert p["situacion"] == "PAGADA" and p["actual"] is None and p["dias"] == 100
    assert cliente.get("/api/cirugias/999999/cobro").status_code == 404


def test_franjas_cubren_todo():
    assert cartera.FRANJAS[0][0] == 0 and cartera.FRANJAS[-1][1] is None
    for (_, hasta), (desde, _) in zip(cartera.FRANJAS, cartera.FRANJAS[1:]):
        assert desde == hasta + 1
