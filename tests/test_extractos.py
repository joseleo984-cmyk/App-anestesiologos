"""Extractos bancarios: PDF por partes (con clave), Excel/CSV del banco, gastos, duplicados y categorías aprendidas.
Datos ficticios."""
import io
from datetime import date
from decimal import Decimal

import openpyxl
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app import auth, extraccion, extractos, main
from tests.test_api import cliente  # noqa: F401  (fixture)


def pdf(hojas: int, clave: str | None = None) -> bytes:
    w = PdfWriter()
    for _ in range(hojas):
        w.add_blank_page(width=612, height=792)
    if clave:
        w.encrypt(clave)
    salida = io.BytesIO()
    w.write(salida)
    return salida.getvalue()


@pytest.mark.parametrize("texto,valor", [
    ("1.234.567,89", "1234567.89"), ("1,234,567.89", "1234567.89"), ("-45.000", "-45000"), ("$ 45.000", "45000"),
    ("(3.500)", "-3500"), ("120000", "120000"), ("12,5", "12.5"), ("1.500", "1500"), ("85.000,00", "85000.00"),
    ("abc", None), ("", None),
])
def test_numeros_como_los_escriben_los_bancos(texto, valor):
    assert extractos.numero(texto) == (Decimal(valor) if valor else None)


def test_clave_del_comercio():
    assert extractos.clave_comercio("COMPRA POS EXITO 0234 BARRANQUILLA") == "EXITO BARRANQUILLA"
    assert extractos.clave_comercio("Compra en D1 SAS 778899") == "D1"
    assert extractos.clave_comercio("PAGO PSE CLARO MOVIL 1234567") == "CLARO MOVIL"
    assert extractos.clave_comercio("PAGO TARJETA") == "PAGO TARJETA"


def test_pdf_con_clave_por_partes_de_10_hojas():
    datos = pdf(23, clave="1045678")
    with pytest.raises(extractos.ExtractoError, match="tiene clave"):
        extractos.partes_pdf(datos)
    with pytest.raises(extractos.ExtractoError, match="no es correcta"):
        extractos.partes_pdf(datos, "999")
    partes, total = extractos.partes_pdf(datos, "1045678")
    assert total == 23 and len(partes) == 3
    from pypdf import PdfReader
    assert [len(PdfReader(io.BytesIO(p)).pages) for p in partes] == [10, 10, 3]
    assert not PdfReader(io.BytesIO(partes[0])).is_encrypted  # a la IA le llega sin clave


def test_fotos_en_grupos_de_10():
    foto = b"\xff\xd8\xff" + b"0" * 100
    p = extractos.preparar_partes([(foto, f"{i}.jpg") for i in range(12)])
    assert [len(x) for x in p["partes"]] == [10, 2] and p["hojas"] == 12


def test_csv_con_valores_negativos():
    texto = ("Extracto cuenta de ahorros\n\nFECHA;DESCRIPCIÓN;SUCURSAL;VALOR;SALDO\n"
             "05/10/2026;COMPRA POS EXITO 0234;BQ;-185.400,00;1.000.000\n"
             "06/10/2026;ABONO NOMINA AP;BQ;4.506.281,00;5.506.281\n"
             "07/10/2026;PAGO TARJETA;BQ;-1.200.000,00;4.306.281\n"
             "TOTAL;;;;\n")
    filas = extractos.leer_csv(texto.encode("latin-1"))
    assert [(f["fecha"], f["valor"], f["naturaleza"]) for f in filas] == [
        (date(2026, 10, 5), Decimal("185400.00"), "CARGO"), (date(2026, 10, 6), Decimal("4506281.00"), "ABONO"),
        (date(2026, 10, 7), Decimal("1200000.00"), "CARGO")]


def test_excel_con_columnas_debito_y_credito():
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.append(["Banco de prueba"])
    hoja.append(["Fecha", "Concepto", "Débitos", "Créditos"])
    hoja.append([date(2026, 10, 3), "TERPEL CALLE 84", 150000, None])
    hoja.append(["04/10/2026", "TRANSFERENCIA RECIBIDA", None, "2.000.000"])
    salida = io.BytesIO()
    libro.save(salida)
    filas = extractos.leer_excel(salida.getvalue())
    assert [(f["descripcion"], f["valor"], f["naturaleza"]) for f in filas] == [
        ("TERPEL CALLE 84", Decimal(150000), "CARGO"), ("TRANSFERENCIA RECIBIDA", Decimal(2000000), "ABONO")]


def test_xls_antiguo_no_se_acepta():
    with pytest.raises(extractos.ExtractoError, match=".xlsx"):
        extractos.tipo_archivo(b"\xd0\xcf\x11\xe0" + b"0" * 50, "extracto.xls")


# ------------------------------------------------------------------ flujo completo por la API
ENCABEZADO = {"banco": "Banco Ficticio", "tipo_producto": "TARJETA_CREDITO", "ultimos_digitos": "4321",
              "periodo_desde": "2026-09-16", "periodo_hasta": "2026-10-15"}


def mov(fecha, descripcion, valor, tipo="COMPRA", es_gasto=True, categoria="OTROS", naturaleza="CARGO"):
    return {"fecha": fecha, "descripcion": descripcion, "valor": valor, "naturaleza": naturaleza, "tipo": tipo,
            "es_gasto": es_gasto, "categoria": categoria}


PARTES = [
    {"encabezado": ENCABEZADO, "movimientos": [
        mov("2026-09-20", "COMPRA EXITO 0234 BARRANQUILLA", 185400, categoria="ALIMENTACION"),
        mov("2026-09-21", "TERPEL CALLE 84", 150000, categoria="TRANSPORTE"),
        mov("2026-09-21", "TERPEL CALLE 84", 150000, categoria="TRANSPORTE"),  # dos tanqueadas iguales: ambas
    ]},
    {"encabezado": {k: None for k in ENCABEZADO}, "movimientos": [
        mov("2026-10-01", "PAGO TARJETA GRACIAS", 1200000, tipo="PAGO_TARJETA", es_gasto=False, categoria=None,
            naturaleza="ABONO"),
        mov("2026-10-02", "RESTAURANTE LA PLAYA", 210000, categoria="ENTRETENIMIENTO"),
        mov("2026-08-10", "ALMACEN CUOTA 3 DE 6", 600000, categoria="PERSONAL"),  # diferida de otro mes
    ]},
    {"encabezado": {k: None for k in ENCABEZADO}, "movimientos": [
        mov("2026-10-05", "CUOTA DE MANEJO", 38900, tipo="CUOTA_MANEJO", categoria="DEUDAS"),
    ]},
]


@pytest.fixture
def con_ia(cliente, monkeypatch):
    llamadas = []

    def leer_falso(archivos, n, total, contexto):
        llamadas.append((n, total, dict(contexto)))
        return PARTES[n - 1]

    monkeypatch.setattr(extractos, "leer_parte", leer_falso)
    cliente.lecturas = llamadas
    return cliente


def importar(c, datos, nombre="extracto.pdf", clave=None):
    r = c.post("/api/finanzas/importaciones", files=[("archivos", (nombre, datos, "application/octet-stream"))],
               data={"clave_pdf": clave} if clave else {})
    assert r.status_code == 202, r.text
    return c.get(f"/api/finanzas/importaciones/{r.json()['importacion_id']}").json()


def test_extracto_pdf_revisar_confirmar_y_no_repetir(con_ia):
    c = con_ia
    assert c.post("/api/finanzas/importaciones",
                  files=[("archivos", ("e.pdf", pdf(25, "1045678"), "application/pdf"))]).status_code == 422
    imp = importar(c, pdf(25, "1045678"), clave="1045678")
    assert imp["estado"] == "LISTO" and imp["partes_total"] == 3 and imp["partes_leidas"] == 3
    # la parte 2 ya sabe el periodo y el banco que vienen en la parte 1
    assert c.lecturas[1][2]["periodo_hasta"] == "2026-10-15" and c.lecturas[1][2]["banco"] == "Banco Ficticio"
    res = imp["resultado"]
    assert res["encabezado"]["ultimos_digitos"] == "4321" and res["cuenta_sugerida"] is None
    items = res["items"]
    assert [i["incluir"] for i in items] == [True, True, True, False, True, False, True]
    assert items[3]["motivo"] == "Pago de la tarjeta: no es gasto"
    assert items[5]["motivo"] == "Compra de un mes anterior (diferida)"
    assert items[1]["huella"] != items[2]["huella"]

    # el usuario cambia el restaurante a ALIMENTACION, y crea la cuenta con lo que se detectó
    elegidos = [{"indice": i["indice"], "incluir": i["incluir"], "categoria": i["categoria"]} for i in items]
    elegidos[4]["categoria"] = "ALIMENTACION"
    r = c.post(f"/api/finanzas/importaciones/{imp['importacion_id']}/confirmar",
               json={"nueva_cuenta": {"banco": "Banco Ficticio", "tipo": "TARJETA_CREDITO", "ultimos_digitos": "4321"},
                     "items": elegidos})
    assert r.status_code == 200, r.text
    assert r.json()["anotados"] == 5 and Decimal(r.json()["total"]) == Decimal("734300")
    assert c.post(f"/api/finanzas/importaciones/{imp['importacion_id']}/confirmar",
                  json={"items": []}).status_code == 409

    e = c.get("/api/finanzas", params={"mes": "2026-09-01"}).json()
    assert e["cuentas"][0]["ultimos_digitos"] == "4321"
    assert {m["cuenta"] for m in e["mes"]["movimientos"]} == {"Banco Ficticio 4321"}
    assert len(e["mes"]["movimientos"]) == 3

    # el mismo extracto otra vez: todo lo anotado sale como ya importado, con la cuenta y la categoría aprendida
    c.lecturas.clear()
    imp2 = importar(c, pdf(25, "1045678"), clave="1045678")
    res2 = imp2["resultado"]
    assert res2["cuenta_sugerida"] == e["cuentas"][0]["cuenta_id"]
    assert [i["duplicado"] for i in res2["items"]] == [True, True, True, False, True, False, True]
    assert not any(i["incluir"] for i in res2["items"])
    assert res2["items"][4]["categoria"] == "ALIMENTACION" and res2["items"][4]["regla"]
    # aunque se marque de nuevo, no se anota dos veces
    r = c.post(f"/api/finanzas/importaciones/{imp2['importacion_id']}/confirmar",
               json={"cuenta_id": res2["cuenta_sugerida"],
                     "items": [{"indice": 0, "incluir": True, "categoria": "ALIMENTACION"}]})
    assert r.json()["anotados"] == 0 and r.json()["repetidos"] == 1


def test_gasto_anotado_a_mano_sale_como_posible_duplicado(con_ia):
    c = con_ia
    c.post("/api/finanzas/movimientos", json={"clase": "GASTO", "categoria": "ALIMENTACION", "fecha": "2026-09-20",
                                             "valor": "185.400", "descripcion": "Mercado"})
    item = importar(c, pdf(3))["resultado"]["items"][0]
    assert not item["incluir"] and item["motivo"].startswith("Posible duplicado")


def test_csv_sin_ia_usa_palabras_clave(cliente, monkeypatch):
    def falla(filas):
        raise extraccion.ExtraccionError("sin servicio")
    monkeypatch.setattr(extractos, "clasificar", falla)
    texto = ("Fecha,Descripcion,Valor\n2026-10-03,COMPRA TERPEL CALLE 84,-150000\n"
             "2026-10-04,PAGO TARJETA CREDITO,-1200000\n2026-10-05,ABONO NOMINA,4506281\n")
    imp = importar(cliente, texto.encode(), nombre="movimientos.csv")
    items = imp["resultado"]["items"]
    assert [(i["categoria"], i["incluir"]) for i in items] == [("TRANSPORTE", True), (None, False), (None, False)]


def test_csv_con_categorias_de_la_ia(cliente, monkeypatch):
    monkeypatch.setattr(extractos, "clasificar", lambda filas: {
        0: {"indice": 0, "tipo": "COMPRA", "es_gasto": True, "categoria": "SALUD"}})
    imp = importar(cliente, b"Fecha;Detalle;Valor\n03/10/2026;DROGUERIA X;-45.000\n", nombre="m.csv")
    assert imp["resultado"]["items"][0]["categoria"] == "SALUD" and imp["partes_total"] == 1


def test_error_de_lectura_queda_registrado(cliente, monkeypatch):
    def falla(*a):
        raise extraccion.ExtraccionError("El servicio de lectura no está disponible, intenta de nuevo en un momento.")
    monkeypatch.setattr(extractos, "leer_parte", falla)
    imp = importar(cliente, pdf(2))
    assert imp["estado"] == "ERROR" and "no está disponible" in imp["error"]


def test_cuentas_y_privacidad(con_ia, conn):
    c = con_ia
    r = c.post("/api/finanzas/cuentas", json={"banco": "Banco Ficticio", "tipo": "CUENTA_AHORROS",
                                             "ultimos_digitos": "**** 9876"})
    cuenta_id = r.json()["cuenta_id"]
    assert c.get("/api/finanzas").json()["cuentas"][0]["ultimos_digitos"] == "9876"
    assert c.put(f"/api/finanzas/cuentas/{cuenta_id}", json={"banco": "Banco Ficticio", "tipo": "CUENTA_CORRIENTE"}
                 ).status_code == 200
    imp = importar(c, pdf(3))

    conn.execute("INSERT INTO anestesiologo (nombre, email) VALUES ('Otro', 'otro@x.co')")
    conn.commit()
    otro = TestClient(main.app)
    otro.cookies.set(auth.COOKIE, auth.crear_sesion(2))
    assert otro.get(f"/api/finanzas/importaciones/{imp['importacion_id']}").status_code == 404
    assert otro.post(f"/api/finanzas/importaciones/{imp['importacion_id']}/confirmar",
                     json={"items": []}).status_code == 404
    assert otro.delete(f"/api/finanzas/cuentas/{cuenta_id}").status_code == 404
    assert otro.get("/api/finanzas").json()["cuentas"] == []
    assert c.delete(f"/api/finanzas/cuentas/{cuenta_id}").status_code == 204
