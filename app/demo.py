"""Cuenta de demostración: datos 100 % ficticios para presentar la app sin pacientes reales.

Solo funciona en cuentas que el administrador marcó como demostración (`anestesiologo.es_demo`). «Recargar»
borra todo lo de esa cuenta y vuelve a crear, con fechas relativas al día de la carga: cirugías en varios
estados (algunas con más de 90 días sin pagar), dos reportes de pago ya cruzados, volantes de los meses
anteriores y finanzas de ejemplo. Además genera los documentos para la presentación en vivo, con la misma
fecha base: una orden para tomarle la foto, un reporte de pagos para subir y el volante que cuadra con él.

Los nombres, documentos (todos empiezan por 9990, rango que no se expide) y cirujanos son inventados.
"""
import hashlib
import uuid
from datetime import date, timedelta
from decimal import Decimal

from app import almacenamiento, finanzas, liquidacion, repositorio
from app.modelos import (FilaPago, MetaEntrada, MovimientoEntrada, OrdenConfirmada, ReportePagoExtraido,
                         VolanteExtraido)

PAGADOR = "ASOCIACIÓN DE ANESTESIÓLOGOS (DEMOSTRACIÓN)"
CIRUJANOS = ["Dr. Rodrigo Ferrán Iriarte", "Dra. Cecilia Montalvo Brun", "Dr. Julio Arenas Salgar",
             "Dra. Paola Ibáñez Corrales"]
CLINICAS = ["CLÍNICA DE LA COSTA", "CLÍNICA PORTOAZUL (AUNA)", "CLÍNICA GENERAL DEL NORTE", "CLÍNICA LA ASUNCIÓN",
            "CLÍNICA SANTA ANA DE DIOS S.A.S."]
ENTIDADES = [("NUEVA EPS", "EPS"), ("EPS SURA", "EPS"), ("COLSANITAS", "PREPAGADA"),
             ("COOMEVA MEDICINA PREPAGADA", "PREPAGADA")]
PROCEDIMIENTOS = [("512104", "COLECISTECTOMÍA VÍA LAPAROSCÓPICA"), ("740001", "CESÁREA SEGMENTARIA TRANSPERITONEAL"),
                  ("471110", "APENDICECTOMÍA VÍA LAPAROSCÓPICA"), ("219501", "SEPTOPLASTIA PRIMARIA TRANSNASAL"),
                  ("684003", "HISTERECTOMÍA TOTAL POR LAPAROTOMÍA"), ("064101", "TIROIDECTOMÍA TOTAL VÍA ABIERTA"),
                  ("853104", "MAMOPLASTIA DE REDUCCIÓN BILATERAL"), ("802601", "ARTROSCOPIA DIAGNÓSTICA DE RODILLA")]

# (días antes de la fecha base, grupo, paciente, clínica, entidad, procedimiento, cirujano, honorarios)
# grupos: VIEJA (realizada, sin pagar > 90 días), PAGO1 y PAGO2 (pagadas por los reportes ya cargados),
# RADICADA, VIVO (en el reporte que se sube en la presentación), PENDIENTE y PROGRAMADA (días negativos)
CIRUGIAS = [
    (128, "VIEJA", "Marcela|Orozco Lindo", 0, 0, 0, 0, 845000),
    (112, "VIEJA", "Hernán|Escorcia Pupo", 2, 1, 4, 2, 1120000),
    (97, "VIEJA", "Luz Dary|Polo Cantillo", 1, 2, 6, 1, 1380000),
    (76, "PAGO1", "Ramiro|De la Hoz Ariza", 0, 2, 0, 0, 1250000),
    (71, "PAGO1", "Silvia|Barrios Navarro", 1, 3, 1, 1, 1460000),
    (66, "PAGO1", "Jorge Iván|Manotas Rey", 3, 0, 2, 3, 980000),
    (60, "PAGO1", "Claudia|Fontalvo Meza", 2, 1, 3, 2, 760000),
    (52, "PAGO2", "Alberto|Sarmiento Gil", 0, 3, 5, 0, 1590000),
    (46, "PAGO2", "Natalia|Charris Bolaño", 1, 2, 1, 1, 1340000),
    (39, "PAGO2", "Fabio|Pertuz Oñate", 3, 1, 7, 3, 1080000),
    (33, "RADICADA", "Gloria|Ballestas Mier", 4, 0, 4, 2, 1210000),
    (29, "RADICADA", "Iván|Rada Visbal", 4, 1, 0, 0, 1150000),
    (24, "VIVO", "Diana|Coronell Ruiz", 1, 2, 0, 1, 1450000),
    (19, "VIVO", "Óscar|Mendoza Peñate", 0, 3, 2, 0, 1180000),
    (14, "VIVO", "Lorena|Vásquez Arteta", 2, 2, 6, 3, 1620000),
    (9, "VIVO", "Camilo|Bermejo Díaz", 3, 0, 5, 2, 980000),
    (4, "PENDIENTE", "Adriana|Suárez Echeverría", 1, 1, 1, 1, 1260000),
    (-3, "PROGRAMADA", "Mauricio|Lara Consuegra", 0, 2, 3, 0, None),
    (-6, "PROGRAMADA", "Teresa|Navarro Pombo", 2, 3, 0, 3, None),
]
# Pacientes del reporte en vivo que no están en la app (las líneas «sin cirugía»)
SIN_CIRUGIA = [("Ricardo|Gómez Villalba", 1, 33, 1120000), ("Yolanda|Padilla Castro", 0, 11, 860000)]
# Paciente de la orden para la foto en vivo (no está en la app)
ORDEN_VIVO = {"nombres": "Andrea Carolina", "apellidos": "Molina Urueta", "clinica": 1, "entidad": 2, "proc": 0,
              "cirujano": 1, "dias": 1, "poliza": "CS-4471029", "plan": "Plan Integral", "orden": "QX-20914"}


def documento(i: int) -> str:
    return f"9990{100211 + i * 7919:06d}"[:10]


def _fila(i: int) -> dict:
    dias, grupo, nombre, cli, ent, proc, ciru, valor = CIRUGIAS[i]
    nombres, apellidos = nombre.split("|")
    return {"dias": dias, "grupo": grupo, "nombres": nombres, "apellidos": apellidos, "doc": documento(i),
            "clinica": CLINICAS[cli], "entidad": ENTIDADES[ent], "proc": PROCEDIMIENTOS[proc],
            "cirujano": CIRUJANOS[ciru], "valor": valor}


def _descuento(valor: int) -> int:
    return round(valor * 0.004)


def _linea_pago(nombres: str, apellidos: str, doc: str, entidad: str, fecha: date, valor: int, factura: int) -> FilaPago:
    return FilaPago(empresa=entidad, documento_paciente=doc, paciente=f"{apellidos} {nombres}".upper(), fecha_servicio=fecha,
                    factura=str(factura), total=Decimal(valor), descuentos=Decimal(_descuento(valor)),
                    neto=Decimal(valor - _descuento(valor)), es_paciente=True)


def _reporte(base: date, grupo: str, fecha_proceso: date, extra: list[FilaPago] = ()) -> ReportePagoExtraido:
    filas = []
    for i in range(len(CIRUGIAS)):
        f = _fila(i)
        if f["grupo"] == grupo:
            filas.append(_linea_pago(f["nombres"], f["apellidos"], f["doc"], f["entidad"][0],
                                     base - timedelta(days=f["dias"]), f["valor"], 52000 + i * 13))
    filas += list(extra)
    desde = fecha_proceso.replace(day=1)
    hasta = (desde + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return ReportePagoExtraido(pagador=PAGADOR, prestador="DRA. DEMO", fecha_proceso=fecha_proceso, periodo_desde=desde,
                               periodo_hasta=hasta, total_neto=sum((x.neto for x in filas), Decimal(0)), filas=filas)


def reporte_en_vivo(base: date) -> ReportePagoExtraido:
    extra = []
    for k, (nombre, ent, dias, valor) in enumerate(SIN_CIRUGIA):
        nombres, apellidos = nombre.split("|")
        extra.append(_linea_pago(nombres, apellidos, documento(90 + k), ENTIDADES[ent][0], base - timedelta(days=dias),
                                 valor, 53100 + k))
    return _reporte(base, "VIVO", base, extra)


def _volante(rep: ReportePagoExtraido) -> tuple[VolanteExtraido, dict]:
    l = liquidacion.liquidar(rep.total_neto, rep.periodo_hasta.year, suscripcion=Decimal(0))
    d, x = l["devengados"], l["deducciones"]
    v = VolanteExtraido(fecha_proceso=rep.fecha_proceso, periodo_desde=rep.periodo_desde, periodo_hasta=rep.periodo_hasta,
                        probienestar=d["probienestar"], compensacion_ordinaria=d["compensacion_ordinaria"],
                        compensacion_extraordinaria=d["compensacion_extraordinaria"], auxilio_sindical=d["auxilio_sindical"],
                        cuatro_por_mil=x["cuatro_por_mil"], cuota_sostenimiento=x["cuota_sostenimiento"], salud=x["salud"],
                        pension=x["pension"], ajuste_sindical=x["ajuste_sindical"] or None, neto=l["neto"])
    return v, l


# ------------------------------------------------------------------ carga
def vaciar(conn, anestesiologo_id: int) -> None:
    """Borra todos los datos de la cuenta de demostración (no la cuenta). Los cirujanos y entidades que solo
    usaba esta cuenta también se borran, para que no queden sugeridos a nadie."""
    usados = conn.execute(
        """SELECT array_agg(DISTINCT c.cirujano_id) FILTER (WHERE c.cirujano_id IS NOT NULL) AS cirujanos,
                  array_agg(DISTINCT cb.aseguradora_id) FILTER (WHERE cb.aseguradora_id IS NOT NULL) AS entidades
             FROM cirugia c LEFT JOIN cobertura cb USING (cobertura_id) WHERE c.anestesiologo_id = %s""",
        (anestesiologo_id,)).fetchone()
    for tabla in ("reporte_pago", "cirugia", "documento_fuente", "paciente", "volante_pago", "fin_movimiento", "fin_meta",
                  "fin_partida", "fin_importacion", "fin_cuenta", "fin_regla_categoria", "comentario_lectura"):
        conn.execute(f"DELETE FROM {tabla} WHERE anestesiologo_id = %s", (anestesiologo_id,))
    if usados["cirujanos"]:
        conn.execute("""DELETE FROM cirujano ci WHERE ci.cirujano_id = ANY(%s)
                          AND NOT EXISTS (SELECT 1 FROM cirugia c WHERE c.cirujano_id = ci.cirujano_id)""",
                     (usados["cirujanos"],))
    if usados["entidades"]:
        conn.execute("""DELETE FROM aseguradora a WHERE a.aseguradora_id = ANY(%s)
                          AND NOT EXISTS (SELECT 1 FROM cobertura cb WHERE cb.aseguradora_id = a.aseguradora_id)""",
                     (usados["entidades"],))


def _orden(f: dict, base: date) -> OrdenConfirmada:
    estado = {"VIEJA": "REALIZADA", "PAGO1": "REALIZADA", "PAGO2": "REALIZADA", "RADICADA": "FACTURADA",
              "VIVO": "REALIZADA", "PENDIENTE": "REALIZADA", "PROGRAMADA": "PROGRAMADA"}[f["grupo"]]
    return OrdenConfirmada.model_validate({
        "paciente": {"tipo_documento": "CC", "numero_documento": f["doc"], "nombres": f["nombres"], "apellidos": f["apellidos"]},
        "aseguradora": {"nombre": f["entidad"][0], "tipo": f["entidad"][1]},
        "clinica": {"nombre": f["clinica"], "ciudad": "BARRANQUILLA"},
        "procedimientos": [{"codigo": f["proc"][0], "nombre": f["proc"][1], "es_principal": True}],
        "fecha_procedimiento": (base - timedelta(days=f["dias"])).isoformat(), "cirujano": f["cirujano"],
        "estado": estado, "valor_honorarios": f["valor"]})


def _guardar_reporte(conn, anestesiologo_id: int, rep: ReportePagoExtraido, aplicar: bool) -> int:
    pdf = pdf_reporte(rep)
    ubicacion = almacenamiento.guardar(f"pago-demo-{uuid.uuid4().hex}.pdf", pdf, "application/pdf")
    reporte_id = repositorio.crear_reporte(conn, anestesiologo_id, ubicacion, hashlib.sha256(pdf).hexdigest(), rep)
    repositorio.conciliar(conn, anestesiologo_id, reporte_id)
    if aplicar:
        repositorio.aplicar_reporte(conn, anestesiologo_id, reporte_id)
    return reporte_id


def cargar(conn, anestesiologo_id: int, base: date) -> dict:
    vaciar(conn, anestesiologo_id)
    for i in range(len(CIRUGIAS)):
        repositorio.guardar_orden(conn, anestesiologo_id, _orden(_fila(i), base))

    # dos reportes de pago ya cruzados y aplicados: las cirugías de PAGO1 y PAGO2 quedan pagadas
    _guardar_reporte(conn, anestesiologo_id, _reporte(base, "PAGO1", base - timedelta(days=40)), True)
    _guardar_reporte(conn, anestesiologo_id, _reporte(base, "PAGO2", base - timedelta(days=12)), True)

    # volantes de los seis meses anteriores (ingreso real de cada mes)
    mes = base.replace(day=1)
    for k, recaudo in enumerate([10_480_000, 12_350_000, 8_960_000, 11_720_000, 9_340_000, 13_150_000]):
        mes = (mes - timedelta(days=1)).replace(day=1)
        l = liquidacion.liquidar(Decimal(recaudo), mes.year, suscripcion=Decimal(0))
        finanzas.guardar_volante(conn, anestesiologo_id, VolanteExtraido(
            periodo_hasta=mes, neto=l["neto"], probienestar=l["devengados"]["probienestar"]))

    # finanzas personales de ejemplo
    for clase, categoria, nombre, valor, saldo, tasa in [
            ("GASTO", "VIVIENDA", "Cuota del apartamento y administración", 1_450_000, None, None),
            ("GASTO", "EDUCACION", "Colegio de los niños", 720_000, None, None),
            ("GASTO", "SERVICIOS", "Servicios, internet y celulares", 360_000, None, None),
            ("GASTO", "SALUD", "Medicina prepagada y seguro de vida", 450_000, None, None),
            ("GASTO", "DEUDAS", "Crédito del carro", 560_000, 18_400_000, Decimal("15.9")),
            ("GASTO", "ALIMENTACION", "Mercado", 780_000, None, None),
            ("GASTO", "TRANSPORTE", "Gasolina y parqueaderos", 310_000, None, None),
            ("GASTO", "ENTRETENIMIENTO", "Restaurantes y salidas", 360_000, None, None),
            ("INGRESO", "CONSULTA", "Consulta preanestésica particular", 1_800_000, None, None)]:
        finanzas.crear_partida(conn, anestesiologo_id, clase, categoria, nombre, Decimal(valor),
                               Decimal(saldo) if saldo else None, tasa)
    metas = [finanzas.crear_meta(conn, anestesiologo_id, MetaEntrada(
                 tipo="EMERGENCIA", nombre="Fondo de emergencias", valor_objetivo=Decimal(30_000_000),
                 ahorrado=Decimal(12_000_000), fecha_objetivo=base + timedelta(days=420))),
             finanzas.crear_meta(conn, anestesiologo_id, MetaEntrada(
                 tipo="VIAJE", nombre="Vacaciones en familia", valor_objetivo=Decimal(8_000_000),
                 ahorrado=Decimal(2_500_000), fecha_objetivo=base + timedelta(days=150)))]
    inicio_mes = base.replace(day=1)
    for dia, clase, categoria, meta, descripcion, valor in [
            (1, "GASTO", "ALIMENTACION", None, "Mercado de la quincena", 410_000),
            (3, "GASTO", "TRANSPORTE", None, "Gasolina", 140_000),
            (5, "APORTE", None, 0, "Ahorro del mes", 1_000_000),
            (8, "GASTO", "ENTRETENIMIENTO", None, "Cena familiar", 185_000),
            (12, "GASTO", "ALIMENTACION", None, "Mercado", 290_000)]:
        fecha = min(base, inicio_mes + timedelta(days=dia - 1))
        finanzas.crear_movimiento(conn, anestesiologo_id, MovimientoEntrada(
            clase=clase, fecha=fecha, categoria=categoria, meta_id=metas[meta] if meta is not None else None,
            descripcion=descripcion, valor=Decimal(valor)))

    conn.execute("UPDATE anestesiologo SET demo_fecha = %s WHERE anestesiologo_id = %s", (base, anestesiologo_id))
    return {"cirugias": len(CIRUGIAS), "fecha_base": base}


# ------------------------------------------------------------------ documentos para la presentación
class _Pdf:
    """PDF mínimo (texto y líneas, Helvetica) para no depender de otra librería. Medidas en puntos, origen arriba."""
    ANCHO, ALTO = 595, 842

    def __init__(self):
        self.paginas = [[]]

    @staticmethod
    def _texto_pdf(s: str) -> str:
        b = s.encode("cp1252", "replace").decode("latin-1")
        return b.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def texto(self, x, y, s, tam=10, negrita=False, gris=0.0, derecha=False):
        if derecha:   # ancho aproximado de Helvetica: 0,5 em por carácter
            x -= len(s) * tam * (0.56 if negrita else 0.52)
        self.paginas[-1].append(f"{gris:.2f} g BT /{'F2' if negrita else 'F1'} {tam} Tf {x:.1f} {self.ALTO - y:.1f} Td "
                                f"({self._texto_pdf(s)}) Tj ET")

    def linea(self, x1, y1, x2, y2, ancho=0.6, gris=0.0):
        self.paginas[-1].append(f"{gris:.2f} G {ancho} w {x1:.1f} {self.ALTO - y1:.1f} m {x2:.1f} {self.ALTO - y2:.1f} l S")

    def caja(self, x, y, w, h, ancho=1.0, gris=0.0):
        self.paginas[-1].append(f"{gris:.2f} G {ancho} w {x:.1f} {self.ALTO - y - h:.1f} {w:.1f} {h:.1f} re S")

    def bytes(self) -> bytes:
        objetos = ["<< /Type /Catalog /Pages 2 0 R >>", None,
                   "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
                   "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
        hojas = []
        for contenido in self.paginas:
            flujo = "\n".join(contenido).encode("latin-1")
            objetos.append(f"<< /Length {len(flujo)} >>\nstream\n".encode("latin-1") + flujo + b"\nendstream")
            objetos.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {self.ANCHO} {self.ALTO}] "
                           f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {len(objetos)} 0 R >>")
            hojas.append(len(objetos))
        objetos[1] = f"<< /Type /Pages /Kids [{' '.join(f'{n} 0 R' for n in hojas)}] /Count {len(hojas)} >>"
        salida, posiciones = bytearray(b"%PDF-1.4\n"), []
        for n, obj in enumerate(objetos, start=1):
            posiciones.append(len(salida))
            cuerpo = obj if isinstance(obj, bytes) else obj.encode("latin-1")
            salida += f"{n} 0 obj\n".encode() + cuerpo + b"\nendobj\n"
        xref = len(salida)
        salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
        salida += "".join(f"{p:010d} 00000 n \n" for p in posiciones).encode()
        salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(salida)


def _pesos(v) -> str:
    return f"{int(v):,}".replace(",", ".")


def _fecha(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _pie(p: _Pdf):
    p.texto(40, 815, "DOCUMENTO FICTICIO PARA DEMOSTRACIÓN · ningún paciente ni valor es real", 8, True, 0.45)


def pdf_reporte(rep: ReportePagoExtraido) -> bytes:
    p = _Pdf()
    p.texto(40, 50, rep.pagador, 13, True)
    p.texto(40, 68, "RELACIÓN DE PACIENTES PAGADOS AL ANESTESIÓLOGO", 10, True)
    p.texto(40, 88, f"Prestador: {rep.prestador}", 9)
    p.texto(40, 102, f"Fecha de proceso: {_fecha(rep.fecha_proceso)}    Periodo: {_fecha(rep.periodo_desde)} a "
                     f"{_fecha(rep.periodo_hasta)}", 9)
    columnas = [(40, "EMPRESA"), (160, "DOCUMENTO"), (215, "PACIENTE"), (340, "F. SERVICIO"), (392, "FACTURA")]
    y = 130
    p.linea(40, y - 12, 555, y - 12)
    for x, t in columnas:
        p.texto(x, y, t, 7, True)
    for x, t in [(475, "TOTAL"), (512, "DESC."), (555, "NETO")]:
        p.texto(x, y, t, 7, True, derecha=True)
    p.linea(40, y + 5, 555, y + 5)
    for f in rep.filas:
        y += 18
        p.texto(40, y, f.empresa[:28], 6)
        p.texto(160, y, f.documento_paciente, 7)
        p.texto(215, y, f.paciente[:26], 7)
        p.texto(340, y, _fecha(f.fecha_servicio), 7)
        p.texto(392, y, f.factura, 7)
        p.texto(475, y, _pesos(f.total), 7, derecha=True)
        p.texto(512, y, _pesos(f.descuentos), 7, derecha=True)
        p.texto(555, y, _pesos(f.neto), 7, derecha=True)
    y += 12
    p.linea(40, y, 555, y)
    p.texto(400, y + 16, "TOTAL NETO A PAGAR", 9, True)
    p.texto(555, y + 16, _pesos(rep.total_neto), 9, True, derecha=True)
    _pie(p)
    return p.bytes()


def pdf_volante(base: date) -> bytes:
    rep = reporte_en_vivo(base)
    v, l = _volante(rep)
    p = _Pdf()
    p.texto(40, 50, PAGADOR, 13, True)
    p.texto(40, 68, "VOLANTE DE LIQUIDACIÓN DE COMPENSACIONES Y AUXILIOS", 10, True)
    p.texto(40, 90, "Asociado: DRA. DEMO", 9)
    p.texto(40, 104, f"Fecha de proceso: {_fecha(v.fecha_proceso)}    INICIO: {_fecha(v.periodo_desde)}    "
                     f"FIN: {_fecha(v.periodo_hasta)}", 9)
    y = 135
    p.texto(40, y, "CONCEPTO", 8, True)
    p.texto(420, y, "DEVENGADO", 8, True, derecha=True)
    p.texto(555, y, "DEDUCIDO", 8, True, derecha=True)
    p.linea(40, y + 5, 555, y + 5)
    filas = [("FONDO PROBIENESTAR", v.probienestar, None), ("COMPENSACION ORDINARIA", v.compensacion_ordinaria, None),
             ("COMPENSACION EXTRAORDINARIA", v.compensacion_extraordinaria, None),
             ("AUXILIO SINDICAL", v.auxilio_sindical, None), ("4 X MIL", None, v.cuatro_por_mil),
             ("CUOTA DE SOSTENIMIENTO", None, v.cuota_sostenimiento), ("SALUD", None, v.salud), ("PENSION", None, v.pension)]
    if v.ajuste_sindical:
        filas.append(("AJUSTE SINDICAL", None, v.ajuste_sindical))
    for nombre, dev, ded in filas:
        y += 18
        p.texto(40, y, nombre, 9)
        if dev:
            p.texto(420, y, _pesos(dev), 9, derecha=True)
        if ded:
            p.texto(555, y, _pesos(ded), 9, derecha=True)
    y += 12
    p.linea(40, y, 555, y)
    p.texto(40, y + 18, "NETO A PAGAR (sin fondo probienestar)", 10, True)
    p.texto(555, y + 18, _pesos(v.neto), 10, True, derecha=True)
    a = l["apropiaciones"]
    y += 60
    p.texto(40, y, "ACUMULADO DE APORTES", 9, True)
    for k, (nombre, valor) in enumerate([("APORTE SINDICAL", l["base_contrato"]), ("SEMESTRAL", a["semestral"] * 5),
                                         ("ANUAL", a["anual"] * 9), ("VACACIONES", a["vacaciones"] * 9)]):
        p.texto(40, y + 18 * (k + 1), nombre, 9)
        p.texto(300, y + 18 * (k + 1), _pesos(valor), 9, derecha=True)
    _pie(p)
    return p.bytes()


def pdf_reporte_en_vivo(base: date) -> bytes:
    return pdf_reporte(reporte_en_vivo(base))


def pdf_orden(base: date) -> bytes:
    o = ORDEN_VIVO
    entidad = ENTIDADES[o["entidad"]]
    cod, proc = PROCEDIMIENTOS[o["proc"]]
    p = _Pdf()
    p.caja(40, 40, 515, 70, 1.4)
    p.texto(56, 70, CLINICAS[o["clinica"]], 18, True)
    p.texto(56, 94, f"ORDEN DE PROCEDIMIENTO QUIRÚRGICO   ·   Nº {o['orden']}", 11)
    filas = [("Paciente:", f"{o['nombres']} {o['apellidos']}".upper()), ("Documento:", f"CC {documento(95)}"),
             ("Entidad:", f"{entidad[0]} · {o['plan']}"), ("Póliza:", o["poliza"]),
             ("Fecha:", _fecha(base + timedelta(days=o["dias"]))), ("Procedimiento:", f"{cod} {proc}"),
             ("Cirujano:", CIRUJANOS[o["cirujano"]].upper()), ("Anestesia:", "GENERAL BALANCEADA")]
    y = 160
    for etiqueta, valor in filas:
        p.texto(56, y, etiqueta, 12, True)
        p.texto(190, y, valor, 12)
        p.linea(190, y + 6, 540, y + 6, 0.5, 0.6)
        y += 42
    p.texto(56, y + 20, "Observaciones:  paciente ASA II, ayuno de 8 horas.", 11)
    p.linea(340, y + 130, 540, y + 130, 0.8)
    p.texto(400, y + 146, "Firma y sello", 10, gris=0.4)
    p.texto(56, 770, "DOCUMENTO FICTICIO PARA DEMOSTRACIÓN", 14, True, 0.55)
    return p.bytes()


DOCUMENTOS = {"orden": ("orden-ficticia.pdf", pdf_orden), "reporte": ("reporte-pagos-ficticio.pdf", pdf_reporte_en_vivo),
              "volante": ("volante-ficticio.pdf", pdf_volante)}
