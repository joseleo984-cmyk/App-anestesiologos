"""Reporte de pagos: lectura, cruce con las cirugías y aplicación (datos ficticios)."""
import json

import pytest

from app import extraccion
from app.modelos import ReportePagoExtraido
from tests.test_api import CONFIRMAR, cliente  # noqa: F401  (fixture)
from tests.test_extraccion import ClienteFalso

REPORTE = {
    "pagador": "ASOCIACION DE ANESTESIOLOGOS (FICTICIA)", "prestador": "DRA. PRUEBA",
    "fecha_proceso": "2026-10-07", "periodo_desde": "2026-10-01", "periodo_hasta": "2026-10-31",
    "total_neto": 7419742,
    "filas": [
        {"empresa": "SEGUROS UNO", "documento_paciente": "72000730", "paciente": "PACIENTE UNO",
         "fecha_servicio": "2026-08-14", "factura": "27111", "autorizacion": "A1", "total": 700405,
         "glosas": 0, "descuentos": 0, "neto": 700405, "es_paciente": True},
        {"empresa": "PREPAGADA DOS", "documento_paciente": "32.622.878", "paciente": "PACIENTE DOS",
         "fecha_servicio": "2026-07-27", "factura": "26898", "autorizacion": "B2", "total": 591976,
         "glosas": 0, "descuentos": 1039, "neto": 590937, "es_paciente": True},
        {"empresa": "IPS TRES", "documento_paciente": "979-60", "paciente": "HONORARIOS X",
         "fecha_servicio": "2026-08-01", "factura": "26982", "autorizacion": "C3", "total": 6000000,
         "glosas": 0, "descuentos": 0, "neto": 6000000, "es_paciente": False},
        {"empresa": "SEGUROS UNO", "documento_paciente": "555000", "paciente": "NO REGISTRADO",
         "fecha_servicio": "2026-08-20", "factura": "1", "autorizacion": "D4", "total": 128400,
         "glosas": 0, "descuentos": 0, "neto": 128400, "es_paciente": True},
    ],
}


def crear(cliente, documento, fecha, estado="PROGRAMADA"):
    datos = {**CONFIRMAR, "fecha_procedimiento": fecha, "estado": estado,
             "paciente": {**CONFIRMAR["paciente"], "numero_documento": documento}}
    r = cliente.post("/api/cirugias", json=datos)
    assert r.status_code == 201, r.text
    return r.json()["cirugia_id"]


@pytest.fixture
def con_reporte(cliente, monkeypatch):
    def poner(reporte):
        monkeypatch.setattr(extraccion, "extraer_reporte_pago",
                            lambda d, t: ReportePagoExtraido.model_validate(reporte))
    poner(REPORTE)
    cliente.poner_reporte = poner
    return cliente


def subir(cliente, contenido=b"%PDF-1.7 reporte"):
    return cliente.post("/api/pagos", files={"archivo": ("reporte.pdf", contenido, "application/pdf")})


def test_cruce_y_aplicacion(con_reporte):
    c = con_reporte
    uno = crear(c, "72000730", "2026-08-14")                    # misma fecha
    dos = crear(c, "32622878", "2026-07-25")                    # 2 días de diferencia
    pendiente = crear(c, "111222", "2026-09-01")                # no está en el reporte
    crear(c, "555000", "2026-08-20", estado="CANCELADA")        # cancelada: no se cruza

    r = subir(c)
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["cuadra"] is True and rep["estado"] == "LEIDO"
    assert [f["resultado"] for f in rep["filas"]] == ["COINCIDE", "COINCIDE", "OTRO_CONCEPTO", "SIN_CIRUGIA"]
    assert [f["cirugia_id"] for f in rep["filas"][:2]] == [uno, dos]

    assert c.post(f"/api/pagos/{rep['reporte_id']}/aplicar").json() == {"marcadas": 2}
    d = c.get(f"/api/cirugias/{uno}").json()
    assert d["estado"] == "PAGADA" and d["valor_honorarios"] == 700405 and d["fecha_pago"] == "2026-10-07"
    assert c.get(f"/api/cirugias/{dos}").json()["valor_honorarios"] == 590937  # el neto, con descuento

    # Aplicar otra vez no cambia nada: lo ya pagado no se toca
    assert c.post(f"/api/pagos/{rep['reporte_id']}/aplicar").json() == {"marcadas": 0}
    pendientes = c.get("/api/cirugias?estado=PENDIENTE").json()
    assert [x["cirugia_id"] for x in pendientes] == [pendiente]
    assert c.get("/api/reportes").json()["totales"]["pendientes"] == 1
    assert c.get("/api/pagos").json()[0]["encontradas"] == 2


def test_un_pago_no_se_cuenta_dos_veces(con_reporte):
    c = con_reporte
    crear(c, "72000730", "2026-08-14")
    rep = subir(c).json()
    c.post(f"/api/pagos/{rep['reporte_id']}/aplicar")
    # Otro reporte que repite el mismo paciente y fecha: la cirugía ya fue pagada por el primero
    c.poner_reporte({**REPORTE, "filas": REPORTE["filas"][:1], "total_neto": 700405})
    otro = subir(c, b"%PDF-1.7 otro reporte").json()
    assert otro["filas"][0]["resultado"] == "SIN_CIRUGIA"


def test_dos_cirugias_del_mismo_paciente(con_reporte):
    c = con_reporte
    primera = crear(c, "72000730", "2026-08-01")
    segunda = crear(c, "72000730", "2026-08-14")
    fila = REPORTE["filas"][0]
    c.poner_reporte({**REPORTE, "total_neto": None,
                     "filas": [fila, {**fila, "fecha_servicio": "2026-08-02", "factura": "2"}]})
    rep = subir(c).json()
    assert [f["cirugia_id"] for f in rep["filas"]] == [segunda, primera]
    assert rep["cuadra"] is None


def test_fuera_de_la_ventana_no_se_cruza(con_reporte):
    c = con_reporte
    crear(c, "72000730", "2025-10-01")  # más de 300 días antes del servicio (2026-08-14)
    crear(c, "72000730", "2026-09-23")  # más de 30 días después del servicio
    assert subir(c).json()["filas"][0]["resultado"] == "SIN_CIRUGIA"


def test_reporte_que_no_cuadra(con_reporte):
    c = con_reporte
    c.poner_reporte({**REPORTE, "total_neto": 1})
    assert subir(c).json()["cuadra"] is False


def test_duplicado_y_descartar(con_reporte):
    c = con_reporte
    rep = subir(c).json()
    assert subir(c).status_code == 409
    assert c.delete(f"/api/pagos/{rep['reporte_id']}").status_code == 204
    rep = subir(c).json()  # tras descartarlo se puede volver a subir
    c.post(f"/api/pagos/{rep['reporte_id']}/aplicar")
    assert c.delete(f"/api/pagos/{rep['reporte_id']}").status_code == 409
    assert c.get(f"/api/pagos/{rep['reporte_id']}/archivo").content == b"%PDF-1.7 reporte"


def test_lectura_del_reporte_con_claude():
    cliente = ClienteFalso(texto=json.dumps(REPORTE))
    r = extraccion.extraer_reporte_pago(b"%PDF-1.7", "application/pdf", client=cliente)
    kw = cliente.llamadas[0]
    assert kw["output_config"]["format"]["schema"] is extraccion.ESQUEMA_PAGO
    assert kw["output_config"]["effort"] == "medium" and kw["system"] is extraccion.INSTRUCCIONES_PAGO
    assert r.filas[1].documento_paciente == "32622878" and r.cuadra is True


def test_volver_a_cruzar_tras_registrar_el_faltante(con_reporte):
    c = con_reporte
    uno = crear(c, "72000730", "2026-08-14")
    rep = subir(c).json()
    c.post(f"/api/pagos/{rep['reporte_id']}/aplicar")
    assert rep["filas"][3]["resultado"] == "SIN_CIRUGIA"
    # se registra el paciente que faltaba: se cruza al guardarlo y, como el reporte ya estaba aplicado, queda pagado
    faltante = crear(c, "555000", "2026-08-20")
    rep = c.post(f"/api/pagos/{rep['reporte_id']}/cruzar").json()
    assert rep["filas"][0]["cirugia_id"] == uno                # lo ya pagado se conserva
    assert rep["filas"][3]["cirugia_id"] == faltante and rep["filas"][3]["estado_cirugia"] == "PAGADA"
    assert c.post(f"/api/pagos/{rep['reporte_id']}/aplicar").json() == {"marcadas": 0}
    assert c.get(f"/api/cirugias/{faltante}").json()["valor_honorarios"] == 128400


def test_reporte_de_glosas(con_reporte):
    c = con_reporte
    c.poner_reporte({**REPORTE, "total_neto": None, "filas": [
        {**REPORTE["filas"][0], "glosas": 50000, "neto": 650405},
        {**REPORTE["filas"][1]},                                             # solo descuento
        {**REPORTE["filas"][3]},                                             # sin glosa ni descuento
        {**REPORTE["filas"][0], "empresa": "OTRA", "fecha_servicio": "2026-01-10", "glosas": 10000}]})
    subir(c)
    g = c.get("/api/glosas").json()
    assert g["totales"]["glosas"] == 60000 and g["totales"]["descuentos"] == 1039 and g["totales"]["lineas"] == 3
    assert g["por_empresa"][0]["nombre"] == "SEGUROS UNO"
    assert c.get("/api/glosas?desde=2026-07-01").json()["totales"]["lineas"] == 2  # por fecha del servicio
    from openpyxl import load_workbook
    import io
    wb = load_workbook(io.BytesIO(c.get("/api/cirugias.xlsx").content))
    assert wb["Glosas"].max_row == 4


def test_cirugia_registrada_despues_del_reporte_se_cruza_sola(con_reporte):
    c = con_reporte
    # el reporte se sube primero, sin cirugías registradas; se aplica (lo que había)
    rep = subir(c).json()
    assert [f["resultado"] for f in rep["filas"]] == ["SIN_CIRUGIA", "SIN_CIRUGIA", "OTRO_CONCEPTO", "SIN_CIRUGIA"]
    c.post(f"/api/pagos/{rep['reporte_id']}/aplicar")
    # luego se registran las cirugías: se cruzan al guardarlas y, como el reporte ya estaba aplicado, quedan pagadas
    uno = crear(c, "72000730", "2026-08-14")
    assert c.get(f"/api/cirugias/{uno}").json()["estado"] == "PAGADA"
    filas = c.get(f"/api/pagos/{rep['reporte_id']}").json()["filas"]
    assert filas[0]["cirugia_id"] == uno and filas[0]["resultado"] == "COINCIDE"


def test_documento_con_prefijo_ceros_y_puntos(con_reporte):
    c = con_reporte
    c.poner_reporte({**REPORTE, "filas": [{**REPORTE["filas"][0], "documento_paciente": "CC 0072.000.730"}]})
    uno = crear(c, "72000730", "2026-08-14")
    rep = subir(c).json()
    assert rep["filas"][0]["cirugia_id"] == uno


def test_volver_a_cruzar_todos(con_reporte):
    c = con_reporte
    rep = subir(c).json()  # reporte leído (sin aplicar) antes de registrar las cirugías
    # se borra el cruce (como si las cirugías se hubieran registrado antes de esta versión): «cruzar todos» lo rehace
    from app.repositorio import conectar
    uno = crear(c, "72000730", "2026-08-14")
    with conectar() as conn:
        conn.execute("UPDATE pago_detalle SET cirugia_id = NULL")
        conn.commit()
    r = c.post("/api/pagos/cruzar-todos").json()
    assert r == {"reportes": 1, "lineas": 3, "encontradas": 1, "nuevas": 1, "marcadas_pagadas": 0, "por_aplicar": 1}
    assert c.get(f"/api/pagos/{rep['reporte_id']}").json()["filas"][0]["cirugia_id"] == uno
    assert c.get(f"/api/cirugias/{uno}").json()["estado"] == "PROGRAMADA"  # leído, no aplicado: no se marca pagada


def test_pago_hasta_300_dias_despues_de_la_cirugia(con_reporte):
    c = con_reporte
    # la fecha de servicio del reporte es la de radicación: la cirugía fue 210 días antes
    c.poner_reporte({**REPORTE, "fecha_proceso": "2026-10-07", "filas": [
        {**REPORTE["filas"][0], "fecha_servicio": "2026-08-14"},
        {**REPORTE["filas"][1], "fecha_servicio": "2026-07-27"}]})
    vieja = crear(c, "72000730", "2026-01-16")      # 210 días antes: se cruza
    crear(c, "32622878", "2026-10-20")              # posterior al pago (7 de octubre): no puede ser esa
    filas = subir(c).json()["filas"]
    assert filas[0]["cirugia_id"] == vieja
    assert filas[1]["cirugia_id"] is None


def test_con_varias_cirugias_toma_la_mas_cercana(con_reporte):
    c = con_reporte
    c.poner_reporte({**REPORTE, "filas": [REPORTE["filas"][0]]})   # servicio 2026-08-14
    crear(c, "72000730", "2026-02-01")
    cercana = crear(c, "72000730", "2026-07-30")
    assert subir(c).json()["filas"][0]["cirugia_id"] == cercana


def test_varias_lineas_del_mismo_paciente_van_a_la_misma_cirugia(con_reporte):
    c = con_reporte
    # AP paga en dos líneas los dos procedimientos de la misma cirugía
    linea = REPORTE["filas"][0]
    c.poner_reporte({**REPORTE, "total_neto": None, "filas": [
        {**linea, "neto": 500000, "factura": "1"}, {**linea, "neto": 200405, "factura": "2"}]})
    uno = crear(c, "72000730", "2026-07-20")
    rep = subir(c).json()
    assert [f["cirugia_id"] for f in rep["filas"]] == [uno, uno]
    assert c.post(f"/api/pagos/{rep['reporte_id']}/aplicar").json() == {"marcadas": 1}
    assert c.get(f"/api/cirugias/{uno}").json()["valor_honorarios"] == 700405  # la suma de las dos líneas


def test_marcar_todas_las_encontradas(con_reporte):
    c = con_reporte
    rep = subir(c).json()                                   # leído, sin aplicar
    uno = crear(c, "72000730", "2026-04-01")                # se cruzan al registrarlas
    dos = crear(c, "32622878", "2026-03-01")
    assert c.post("/api/pagos/cruzar-todos").json()["por_aplicar"] == 2
    assert c.post("/api/pagos/aplicar-todos").json() == {"marcadas": 2}
    assert {c.get(f"/api/cirugias/{i}").json()["estado"] for i in (uno, dos)} == {"PAGADA"}
    assert c.get(f"/api/pagos/{rep['reporte_id']}").json()["estado"] == "APLICADO"
    assert c.post("/api/pagos/cruzar-todos").json()["por_aplicar"] == 0
