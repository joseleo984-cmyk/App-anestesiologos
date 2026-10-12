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
    assert any("por encima de tu ingreso base" in c["texto"] for c in e["consejos"])


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
