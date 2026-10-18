"""Finanzas personales: ingreso base, gastos con semáforo, metas y privacidad (montos de volantes reales)."""
from datetime import date
from decimal import Decimal

from app import extraccion, finanzas
from app.modelos import VolanteExtraido
from tests.test_api import cliente  # noqa: F401  (fixture)
from tests.test_liquidacion import VOLANTE_OCTUBRE
from tests.test_pagos import REPORTE, con_reporte, subir  # noqa: F401  (fixtures)

# neto del volante y fondo probienestar, abril a octubre de 2026
MESES = {4: (5709561, 2037151), 5: (2282800, 855270), 6: (8429262, 3104976), 7: (4070248, 1461083),
         8: (7491944, 2720424), 9: (2261364, 848974), 10: (4506281, 1614308)}
BASE_AP = Decimal("3926580")   # promedio de los 3 meses más bajos (septiembre, mayo y julio)


def cargar_volantes(conn):
    for mes, (neto, probienestar) in MESES.items():
        finanzas.guardar_volante(conn, 1, VolanteExtraido(periodo_hasta=date(2026, mes, 28), neto=neto,
                                                          probienestar=probienestar))
    conn.commit()


def test_ingreso_base_con_los_tres_meses_mas_bajos(conn):
    cargar_volantes(conn)
    e = finanzas.estado(conn, 1, hoy=date(2026, 10, 15))
    assert e["ingreso_base_ap"] == BASE_AP and e["meses_base"] == 3
    assert [m["periodo"].month for m in e["meses"]] == [10, 9, 8, 7, 6, 5, 4]
    assert e["meses"][0]["total"] == 4506281 + 1614308 and e["meses"][0]["fuente"] == "VOLANTE"
    # el último mes (octubre) entró por encima de la base: sugerir llevarlo a metas
    assert any("por encima del ingreso base" in c["texto"] for c in e["consejos"])


def test_gastos_con_semaforo_y_metas(cliente):
    from app.repositorio import conectar
    with conectar() as conn:
        cargar_volantes(conn)
    def partida(clase, categoria, nombre, valor):
        r = cliente.post("/api/finanzas/partidas", json={"clase": clase, "categoria": categoria, "nombre": nombre,
                                                         "valor_mensual": valor})
        assert r.status_code == 201, r.text
        return r.json()["partida_id"]
    partida("INGRESO", "ARRIENDO", "Apartamento", "1.000.000")
    vivienda = partida("GASTO", "VIVIENDA", "Arriendo", 1800000)        # 36,5 %: alto (ref. 30 %)
    partida("GASTO", "ALIMENTACION", "Mercado", 600000)                 # 12,2 %: sano
    partida("GASTO", "ENTRETENIMIENTO", "Salidas", 900000)              # 18,3 %: muy alto (ref. 10 %)
    assert cliente.post("/api/finanzas/partidas", json={"clase": "GASTO", "categoria": "ARRIENDO",
                                                        "nombre": "x", "valor_mensual": 1}).status_code == 422
    r = cliente.post("/api/finanzas/metas", json={"tipo": "VIAJE", "nombre": "Europa", "valor_objetivo": "12.000.000",
                                                  "ahorrado": "2.000.000", "fecha_objetivo": "2027-12-15"})
    assert r.status_code == 201, r.text

    e = cliente.get("/api/finanzas").json()
    assert Decimal(e["ingreso_base"]) == BASE_AP + 1000000
    estados = {c["categoria"]: c["estado"] for c in e["por_categoria"]}
    assert estados == {"VIVIENDA": "ALTO", "ALIMENTACION": "SANO", "ENTRETENIMIENTO": "MUY_ALTO"}
    assert Decimal(e["capacidad_ahorro"]) == BASE_AP + 1000000 - 3300000
    meta = e["metas"][0]
    assert Decimal(meta["falta"]) == 10000000 and meta["meses_restantes"] >= 1 and Decimal(meta["cuota_mensual"]) > 0
    textos = " ".join(c["texto"] for c in e["consejos"])
    assert "fondo de emergencias" in textos and "Salidas, restaurantes" in textos
    assert {c["clave"] for c in e["catalogos"]["gastos"]} >= {"VIVIENDA", "DEUDAS"}

    # corregir y borrar
    assert cliente.put(f"/api/finanzas/partidas/{vivienda}", json={"clase": "GASTO", "categoria": "VIVIENDA",
                       "nombre": "Arriendo", "valor_mensual": 1400000}).status_code == 200
    e = cliente.get("/api/finanzas").json()
    assert {c["categoria"]: c["estado"] for c in e["por_categoria"]}["VIVIENDA"] == "SANO"
    assert cliente.delete(f"/api/finanzas/partidas/{vivienda}").status_code == 204
    assert cliente.delete(f"/api/finanzas/metas/{meta['meta_id']}").status_code == 204
    assert cliente.get("/api/finanzas").json()["metas"] == []


def test_cada_anestesiologo_ve_solo_sus_finanzas(conn):
    conn.execute("INSERT INTO anestesiologo (nombre, email) VALUES ('Otro', 'otro@x.co')")
    cargar_volantes(conn)
    pid = finanzas.crear_partida(conn, 1, "GASTO", "VIVIENDA", "Arriendo", Decimal(1))
    conn.commit()
    assert not finanzas.borrar_partida(conn, 2, pid)
    otro = finanzas.estado(conn, 2)
    assert otro["meses"] == [] and otro["partidas"] == [] and otro["ingreso_base"] == 0


def test_volante_comparado_queda_como_ingreso_y_sin_volante_se_calcula(con_reporte, monkeypatch):
    c = con_reporte
    c.poner_reporte({**REPORTE, "total_neto": 8071542})
    reporte_id = subir(c).json()["reporte_id"]
    mes = c.get("/api/finanzas").json()["meses"][0]
    assert mes["fuente"] == "CALCULADO" and Decimal(mes["neto"]) == 4506281
    monkeypatch.setattr(extraccion, "extraer_volante",
                        lambda d, t: VolanteExtraido.model_validate({**VOLANTE_OCTUBRE, "neto": 4400000}))
    c.post(f"/api/pagos/{reporte_id}/volante", files={"archivo": ("v.pdf", b"%PDF-1.7 v", "application/pdf")})
    mes = c.get("/api/finanzas").json()["meses"][0]
    assert mes["fuente"] == "VOLANTE" and Decimal(mes["neto"]) == 4400000
    # también se puede subir el volante directamente en Finanzas, y borrarlo
    r = c.post("/api/volantes", files={"archivo": ("v.pdf", b"%PDF-1.7 v2", "application/pdf")})
    assert r.status_code == 201 and r.json()["periodo"] == "2026-10-01"
    assert c.delete("/api/volantes/2026-10-01").status_code == 204
    assert c.get("/api/finanzas").json()["meses"][0]["fuente"] == "CALCULADO"


# ------------------------------------------------------------------ fase 2
def test_proyeccion_de_metas():
    metas = [{"meta_id": 1, "tipo": "EMERGENCIA", "nombre": "Fondo", "falta": Decimal(3000000), "cuota_mensual": Decimal(0),
              "fecha_objetivo": None},
             {"meta_id": 2, "tipo": "VIAJE", "nombre": "Viaje", "falta": Decimal(6000000), "cuota_mensual": Decimal(1000000),
              "fecha_objetivo": date(2027, 4, 1)}]
    finanzas.proyectar_metas(metas, Decimal(1000000), date(2026, 10, 1))
    fondo, viaje = metas
    assert viaje["fecha_estimada"] == date(2027, 4, 1) and viaje["a_tiempo"]      # su cuota va primero
    assert fondo["fecha_estimada"] == date(2027, 7, 1)                              # luego el sobrante
    finanzas.proyectar_metas(metas, Decimal(500000), date(2026, 10, 1))
    assert metas[1]["fecha_estimada"] == date(2027, 10, 1) and not metas[1]["a_tiempo"]
    finanzas.proyectar_metas(metas, Decimal(0), date(2026, 10, 1))
    assert metas[1]["fecha_estimada"] is None


def test_creditos_y_vivienda():
    gastos = [
        {"partida_id": 1, "categoria": "DEUDAS", "nombre": "Tarjeta", "valor_mensual": Decimal(300000),
         "saldo": Decimal(5000000), "tasa_ea": Decimal(30)},
        {"partida_id": 2, "categoria": "DEUDAS", "nombre": "Libre inversión", "valor_mensual": Decimal(600000),
         "saldo": Decimal(20000000), "tasa_ea": Decimal(18)},
        {"partida_id": 3, "categoria": "VIVIENDA", "nombre": "Arriendo", "valor_mensual": Decimal(1), "saldo": None, "tasa_ea": None}]
    c = finanzas.analizar_creditos(gastos, date(2026, 10, 15))
    tarjeta, libre = c["creditos"]
    assert tarjeta["meses"] == 22 and 1_500_000 < tarjeta["intereses"] < 1_700_000
    assert libre["meses"] == 46 and c["saldo_total"] == 25000000
    assert "Tarjeta" in c["recomendacion"]
    gastos[0]["valor_mensual"] = Decimal(100000)   # no cubre ni los intereses (~110.000 al mes)
    c = finanzas.analizar_creditos(gastos, date(2026, 10, 15))
    assert not c["creditos"][0]["cubre_intereses"] and "no alcanza ni para los intereses" in c["recomendacion"]


def test_ahorros_de_ap_y_lo_que_viene(con_reporte):
    from app.repositorio import conectar
    from tests.test_pagos import crear
    c = con_reporte
    crear(c, "72000730", "2026-08-14")          # se paga en el reporte (SEGUROS UNO ... ver REPORTE)
    crear(c, "32622878", "2026-07-25")
    subir(c)                                    # reporte del 2026-10-07: pagos de agosto y julio
    crear(c, "5551", "2026-10-01")              # pendientes de pago
    crear(c, "5552", "2026-10-03")
    crear(c, "5553", "2026-01-10")              # muy vieja: atrasada
    with conectar() as conn:
        finanzas.guardar_volante(conn, 1, VolanteExtraido.model_validate({
            **VOLANTE_OCTUBRE, "acumulado_aporte_sindical": 1017800, "acumulado_semestral": 946882,
            "acumulado_anual": 1948008, "acumulado_vacaciones": 683512}))
        conn.commit()
        e = finanzas.estado(conn, 1, hoy=date(2026, 10, 15))
    a = e["ahorros_ap"]
    assert a["semestral"] == 946882 and a["total"] == 946882 + 1948008 + 683512 and a["proximo_semestral"] == "diciembre"
    p = e["por_cobrar"]
    assert p["cirugias"] == 2 and p["atrasadas"] == 1 and p["rezago_dias"] > 30
    assert all(m["periodo"] >= date(2026, 11, 1) for m in p["meses"]) and p["total_te_llega"] > 0


# ------------------------------------------------------------------ fase 3
def test_compromiso_de_ahorro_con_racha(conn):
    from app.modelos import MetaEntrada, MovimientoEntrada
    meta = finanzas.crear_meta(conn, 1, MetaEntrada(tipo="VIAJE", nombre="Europa", valor_objetivo=6000000,
                                                    fecha_objetivo=date(2027, 6, 1)))
    finanzas.fijar_compromiso(conn, 1, meta, Decimal(500000), hoy=date(2026, 8, 3))
    for fecha, valor in ((date(2026, 8, 10), 500000), (date(2026, 9, 5), 600000), (date(2026, 10, 2), 200000)):
        finanzas.crear_movimiento(conn, 1, MovimientoEntrada(clase="APORTE", meta_id=meta, fecha=fecha, valor=valor))
    conn.commit()
    e = finanzas.estado(conn, 1, hoy=date(2026, 10, 20))
    m = e["metas"][0]
    assert m["ahorrado"] == 1300000 and m["aportado_mes"] == 200000 and m["cumple_mes"] is False
    assert m["racha"] == 2
    assert [(h["periodo"].month, h["estado"]) for h in m["historial"]] == [(8, "CUMPLIDO"), (9, "CUMPLIDO"), (10, "EN_CURSO")]
    assert m["fecha_con_compromiso"] == date(2027, 8, 1)          # 4,7 M / 500 mil = 10 meses
    textos = " ".join(c["texto"] for c in e["consejos"])
    assert "van $200.000 del compromiso de $500.000" in textos and "08/2027" in textos
    # septiembre, mirado como mes elegido: cumplido
    sept = finanzas.estado(conn, 1, hoy=date(2026, 10, 20), mes=date(2026, 9, 1))
    assert sept["metas"][0]["cumple_mes"] and sept["metas"][0]["aportado_mes"] == 600000
    # borrar un aporte devuelve lo ahorrado
    mov = e["mes"]["movimientos"][0]["movimiento_id"]
    assert finanzas.borrar_movimiento(conn, 1, mov)
    assert finanzas.listar_metas(conn, 1)[0]["ahorrado"] == 1100000
    finanzas.fijar_compromiso(conn, 1, meta, None)
    assert finanzas.listar_metas(conn, 1)[0]["comprometido_en"] is None


def test_gastos_reales_contra_presupuesto(cliente):
    def post(url, datos, codigo=201):
        r = cliente.post(url, json=datos)
        assert r.status_code == codigo, r.text
        return r.json()
    post("/api/finanzas/partidas", {"clase": "GASTO", "categoria": "ALIMENTACION", "nombre": "Mercado", "valor_mensual": 600000})
    post("/api/finanzas/partidas", {"clase": "GASTO", "categoria": "ENTRETENIMIENTO", "nombre": "Salidas", "valor_mensual": 300000})
    hoy = date.today().isoformat()
    for cat, valor in (("ALIMENTACION", "400.000"), ("ALIMENTACION", "250.000"), ("ENTRETENIMIENTO", 400000), ("TRANSPORTE", 100000)):
        post("/api/finanzas/movimientos", {"clase": "GASTO", "categoria": cat, "valor": valor, "fecha": hoy})
    mes = cliente.get("/api/finanzas").json()["mes"]
    cats = {c["categoria"]: c for c in mes["categorias"]}
    assert cats["ALIMENTACION"]["estado"] == "ALTO" and Decimal(cats["ALIMENTACION"]["real"]) == 650000
    assert cats["ENTRETENIMIENTO"]["estado"] == "MUY_ALTO"
    assert cats["TRANSPORTE"]["estado"] == "SIN_PRESUPUESTO"
    assert Decimal(mes["real"]) == 1150000 and len(mes["movimientos"]) == 4
    # otro mes: vacío
    assert cliente.get("/api/finanzas", params={"mes": "2020-01-01"}).json()["mes"]["movimientos"] == []
    # validaciones
    post("/api/finanzas/movimientos", {"clase": "GASTO", "valor": 1000}, 422)
    post("/api/finanzas/movimientos", {"clase": "APORTE", "meta_id": 999, "valor": 1000}, 404)
    meta = post("/api/finanzas/metas", {"tipo": "CARRO", "nombre": "Carro", "valor_objetivo": 30000000})["meta_id"]
    r = cliente.put(f"/api/finanzas/metas/{meta}/compromiso", json={"compromiso_mensual": "1.000.000"})
    assert r.status_code == 200
    post("/api/finanzas/movimientos", {"clase": "APORTE", "meta_id": meta, "valor": 1000000})
    m = cliente.get("/api/finanzas").json()["metas"][0]
    assert m["cumple_mes"] and m["racha"] == 1 and Decimal(m["ahorrado"]) == 1000000


def test_historial_de_gastos_de_6_meses(conn):
    from app.modelos import MovimientoEntrada
    for fecha, valor in [("2026-05-03", 100000), ("2026-10-02", 250000), ("2026-10-20", 50000), ("2026-03-01", 999)]:
        finanzas.crear_movimiento(conn, 1, MovimientoEntrada(clase="GASTO", categoria="OTROS", fecha=fecha, valor=valor))
    h = finanzas.estado(conn, 1, hoy=date(2026, 10, 15))["mes"]["historial"]
    assert [x["periodo"].month for x in h] == [5, 6, 7, 8, 9, 10]
    assert [x["gastos"] for x in h] == [100000, 0, 0, 0, 0, 300000]
