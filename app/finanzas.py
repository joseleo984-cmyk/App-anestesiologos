"""Finanzas personales de cada anestesiólogo: ingresos (volantes de AP + ingresos adicionales),
presupuesto de gastos con semáforo y metas de ahorro.

Criterio: con ingresos tan variables, el presupuesto se arma sobre el INGRESO BASE (promedio de los
3 meses más bajos de los últimos 12), no sobre el promedio; lo que entre por encima se reparte a metas.
Los porcentajes de referencia son guías generales de finanzas personales, no asesoría individual.
"""
import math
from datetime import date
from decimal import Decimal
from typing import Optional

from psycopg.types.json import Jsonb

from app import liquidacion

# (clave, nombre, % máximo sano del ingreso base, fijo o variable)
CATEGORIAS = [
    ("VIVIENDA", "Vivienda (arriendo o cuota, administración)", 30, "FIJO"),
    ("SERVICIOS", "Servicios, internet y celular", 8, "FIJO"),
    ("EDUCACION", "Educación (colegios, universidad)", 15, "FIJO"),
    ("SALUD", "Salud y seguros", 10, "FIJO"),
    ("DEUDAS", "Cuotas de créditos y tarjetas", 20, "FIJO"),
    ("ALIMENTACION", "Mercado y alimentación", 15, "VARIABLE"),
    ("TRANSPORTE", "Transporte (gasolina, parqueadero, mantenimiento)", 10, "VARIABLE"),
    ("ENTRETENIMIENTO", "Salidas, restaurantes y entretenimiento", 10, "VARIABLE"),
    ("PERSONAL", "Ropa y cuidado personal", 5, "VARIABLE"),
    ("OTROS", "Otros gastos", 5, "VARIABLE"),
]
CATEGORIAS_INGRESO = [("ARRIENDO", "Arriendos"), ("CONSULTA", "Consulta particular"),
                      ("EMPLEO", "Otro empleo o contrato"), ("INVERSION", "Rendimientos e inversiones"),
                      ("OTRO", "Otro ingreso")]
TIPOS_META = [("EMERGENCIA", "Fondo de emergencias"), ("VIAJE", "Viaje"), ("CARRO", "Carro"), ("CASA", "Casa"),
              ("EDUCACION", "Educación"), ("RETIRO", "Retiro / pensión voluntaria"), ("OTRO", "Otra meta")]
MESES_EMERGENCIA = 6        # con ingresos variables y sin prestaciones, 6 meses de gastos
LIMITE_FIJOS, LIMITE_GASTOS = 50, 80   # % del ingreso base: fijos y gasto total (ahorro >= 20 %)
TOLERANCIA_ALTO = Decimal("1.25")      # hasta 25 % por encima de la referencia: "alto"; más: "muy alto"


def semaforo(porcentaje: Decimal, referencia: Decimal) -> str:
    if porcentaje <= referencia:
        return "SANO"
    return "ALTO" if porcentaje <= referencia * TOLERANCIA_ALTO else "MUY_ALTO"


def _primer_dia(d: date) -> date:
    return d.replace(day=1)


# ------------------------------------------------------------------ ingresos
def guardar_volante(conn, anestesiologo_id: int, volante, reporte_id: Optional[int] = None) -> dict:
    """Guarda (o reemplaza) el volante del mes como ingreso real. Devuelve el periodo y los valores."""
    fecha = volante.periodo_hasta or volante.fecha_proceso
    if fecha is None or volante.neto is None:
        raise ValueError("El volante no trae el mes o el neto.")
    periodo = _primer_dia(fecha)
    conn.execute(
        """INSERT INTO volante_pago (anestesiologo_id, periodo, neto, probienestar, datos_extraidos)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (anestesiologo_id, periodo) DO UPDATE
              SET neto = EXCLUDED.neto, probienestar = EXCLUDED.probienestar,
                  datos_extraidos = EXCLUDED.datos_extraidos, subido_en = now()""",
        (anestesiologo_id, periodo, volante.neto, volante.probienestar or 0, Jsonb(volante.model_dump(mode="json"))),
    )
    return {"periodo": periodo, "neto": volante.neto, "probienestar": volante.probienestar or 0}


def ingresos_por_mes(conn, anestesiologo_id: int, meses: int = 12) -> list[dict]:
    """Ingreso de AP de cada mes: el volante si se subió; si no, la liquidación calculada del reporte de pagos."""
    volantes = {v["periodo"]: v for v in conn.execute(
        "SELECT periodo, neto, probienestar FROM volante_pago WHERE anestesiologo_id = %s", (anestesiologo_id,))}
    reportes = conn.execute(
        """SELECT r.reporte_id, COALESCE(r.periodo_hasta, r.fecha_proceso) AS fecha, r.total_neto,
                  (SELECT SUM(neto) FROM pago_detalle d WHERE d.reporte_id = r.reporte_id) AS suma_neto
             FROM reporte_pago r WHERE r.anestesiologo_id = %s AND COALESCE(r.periodo_hasta, r.fecha_proceso) IS NOT NULL
            ORDER BY r.subido_en""", (anestesiologo_id,)).fetchall()
    calculados: dict[date, Decimal] = {}
    for r in reportes:  # varios reportes del mismo mes se suman
        periodo = _primer_dia(r["fecha"])
        calculados[periodo] = calculados.get(periodo, Decimal(0)) + (r["total_neto"] if r["total_neto"] is not None
                                                                     else (r["suma_neto"] or Decimal(0)))
    filas = []
    for periodo in sorted(set(volantes) | set(calculados), reverse=True)[:meses]:
        if periodo in volantes:
            v = volantes[periodo]
            filas.append({"periodo": periodo, "neto": v["neto"], "probienestar": v["probienestar"],
                          "total": v["neto"] + v["probienestar"], "fuente": "VOLANTE"})
        else:
            l = liquidacion.liquidar(calculados[periodo], periodo.year)
            filas.append({"periodo": periodo, "neto": l["neto"], "probienestar": l["devengados"]["probienestar"],
                          "total": l["neto"] + l["devengados"]["probienestar"], "fuente": "CALCULADO",
                          "recaudo": l["recaudo"]})
    return filas


# ------------------------------------------------------------------ partidas y metas
def listar_partidas(conn, anestesiologo_id: int) -> list[dict]:
    return conn.execute(
        """SELECT partida_id, clase, categoria, nombre, valor_mensual, saldo, tasa_ea FROM fin_partida
            WHERE anestesiologo_id = %s ORDER BY clase, categoria, partida_id""", (anestesiologo_id,)).fetchall()


def crear_partida(conn, anestesiologo_id: int, clase: str, categoria: str, nombre: str, valor: Decimal,
                  saldo: Optional[Decimal] = None, tasa_ea: Optional[Decimal] = None) -> int:
    return conn.execute(
        """INSERT INTO fin_partida (anestesiologo_id, clase, categoria, nombre, valor_mensual, saldo, tasa_ea)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING partida_id""",
        (anestesiologo_id, clase, categoria, nombre, valor, saldo, tasa_ea)).fetchone()["partida_id"]


def actualizar_partida(conn, anestesiologo_id: int, partida_id: int, categoria: str, nombre: str, valor: Decimal,
                       saldo: Optional[Decimal] = None, tasa_ea: Optional[Decimal] = None) -> bool:
    return conn.execute(
        """UPDATE fin_partida SET categoria = %s, nombre = %s, valor_mensual = %s, saldo = %s, tasa_ea = %s
            WHERE partida_id = %s AND anestesiologo_id = %s""",
        (categoria, nombre, valor, saldo, tasa_ea, partida_id, anestesiologo_id)).rowcount == 1


def borrar_partida(conn, anestesiologo_id: int, partida_id: int) -> bool:
    return conn.execute("DELETE FROM fin_partida WHERE partida_id = %s AND anestesiologo_id = %s",
                        (partida_id, anestesiologo_id)).rowcount == 1


def listar_metas(conn, anestesiologo_id: int) -> list[dict]:
    return conn.execute(
        """SELECT meta_id, tipo, nombre, valor_objetivo, ahorrado, fecha_objetivo, compromiso_mensual, comprometido_en
             FROM fin_meta
            WHERE anestesiologo_id = %s ORDER BY (tipo <> 'EMERGENCIA'), fecha_objetivo NULLS LAST, meta_id""",
        (anestesiologo_id,)).fetchall()


def crear_meta(conn, anestesiologo_id: int, m) -> int:
    return conn.execute(
        """INSERT INTO fin_meta (anestesiologo_id, tipo, nombre, valor_objetivo, ahorrado, fecha_objetivo)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING meta_id""",
        (anestesiologo_id, m.tipo, m.nombre, m.valor_objetivo, m.ahorrado, m.fecha_objetivo)).fetchone()["meta_id"]


def actualizar_meta(conn, anestesiologo_id: int, meta_id: int, m) -> bool:
    return conn.execute(
        """UPDATE fin_meta SET tipo = %s, nombre = %s, valor_objetivo = %s, ahorrado = %s, fecha_objetivo = %s
            WHERE meta_id = %s AND anestesiologo_id = %s""",
        (m.tipo, m.nombre, m.valor_objetivo, m.ahorrado, m.fecha_objetivo, meta_id, anestesiologo_id)).rowcount == 1


def fijar_compromiso(conn, anestesiologo_id: int, meta_id: int, valor: Optional[Decimal], hoy: Optional[date] = None) -> bool:
    """El anestesiólogo se compromete a ahorrar `valor` cada mes para la meta (None lo quita).
    El cumplimiento se cuenta desde el mes en que se compromete."""
    return conn.execute(
        """UPDATE fin_meta SET compromiso_mensual = %s,
                  comprometido_en = CASE WHEN %s::numeric IS NULL THEN NULL
                                         ELSE COALESCE(comprometido_en, %s) END
            WHERE meta_id = %s AND anestesiologo_id = %s""",
        (valor, valor, _primer_dia(hoy or date.today()), meta_id, anestesiologo_id)).rowcount == 1


# ------------------------------------------------------------------ movimientos reales (fase 3)
class MovimientoInvalido(ValueError):
    pass


def crear_movimiento(conn, anestesiologo_id: int, m) -> int:
    """Registra un gasto real o un aporte a una meta. El aporte suma a lo ahorrado de la meta."""
    if m.clase == "APORTE":
        meta = conn.execute("SELECT 1 FROM fin_meta WHERE meta_id = %s AND anestesiologo_id = %s",
                            (m.meta_id, anestesiologo_id)).fetchone()
        if not meta:
            raise MovimientoInvalido("La meta no existe.")
        conn.execute("UPDATE fin_meta SET ahorrado = ahorrado + %s WHERE meta_id = %s", (m.valor, m.meta_id))
    return conn.execute(
        """INSERT INTO fin_movimiento (anestesiologo_id, fecha, clase, categoria, meta_id, descripcion, valor)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING movimiento_id""",
        (anestesiologo_id, m.fecha, m.clase, m.categoria if m.clase == "GASTO" else None,
         m.meta_id if m.clase == "APORTE" else None, m.descripcion, m.valor)).fetchone()["movimiento_id"]


def borrar_movimiento(conn, anestesiologo_id: int, movimiento_id: int) -> bool:
    mov = conn.execute("""DELETE FROM fin_movimiento WHERE movimiento_id = %s AND anestesiologo_id = %s
                          RETURNING clase, meta_id, valor""", (movimiento_id, anestesiologo_id)).fetchone()
    if mov and mov["clase"] == "APORTE":
        conn.execute("UPDATE fin_meta SET ahorrado = GREATEST(0, ahorrado - %s) WHERE meta_id = %s",
                     (mov["valor"], mov["meta_id"]))
    return mov is not None


def borrar_meta(conn, anestesiologo_id: int, meta_id: int) -> bool:
    return conn.execute("DELETE FROM fin_meta WHERE meta_id = %s AND anestesiologo_id = %s",
                        (meta_id, anestesiologo_id)).rowcount == 1


# ------------------------------------------------------------------ estado financiero
def _meses_hasta(fecha: date, hoy: date) -> int:
    return max(1, (fecha.year - hoy.year) * 12 + fecha.month - hoy.month)


def _num(v, decimales: int = 1) -> str:
    """15.28 -> '15,3'; 30.00 -> '30'."""
    texto = f"{Decimal(v):.{decimales}f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def _pesos(v) -> str:
    return f"${Decimal(v):,.0f}".replace(",", ".")


def estado(conn, anestesiologo_id: int, hoy: Optional[date] = None, mes: Optional[date] = None) -> dict:
    hoy = hoy or date.today()
    mes = _primer_dia(mes or hoy)
    meses = ingresos_por_mes(conn, anestesiologo_id)
    partidas = listar_partidas(conn, anestesiologo_id)
    gastos = [p for p in partidas if p["clase"] == "GASTO"]
    extras = [p for p in partidas if p["clase"] == "INGRESO"]
    metas = listar_metas(conn, anestesiologo_id)

    totales = sorted(m["total"] for m in meses)
    bajos = totales[:3]
    base_ap = sum(bajos, Decimal(0)) / len(bajos) if bajos else Decimal(0)
    promedio_ap = sum(totales, Decimal(0)) / len(totales) if totales else Decimal(0)
    otros = sum((p["valor_mensual"] for p in extras), Decimal(0))
    base = base_ap + otros

    total_gastos = sum((g["valor_mensual"] for g in gastos), Decimal(0))
    pct = (lambda v: (Decimal(v) * 100 / base) if base else Decimal(0))
    referencias = {c: Decimal(r) for c, _, r, _ in CATEGORIAS}
    tipo_categoria = {c: t for c, _, _, t in CATEGORIAS}
    por_categoria = []
    for clave, nombre, ref, tipo in CATEGORIAS:
        valor = sum((g["valor_mensual"] for g in gastos if g["categoria"] == clave), Decimal(0))
        if valor:
            por_categoria.append({"categoria": clave, "nombre": nombre, "valor": valor, "porcentaje": pct(valor),
                                  "referencia": ref, "estado": semaforo(pct(valor), Decimal(ref))})
    fijos = sum((g["valor_mensual"] for g in gastos if tipo_categoria.get(g["categoria"]) == "FIJO"), Decimal(0))
    capacidad = base - total_gastos

    hoy_mes = _primer_dia(hoy)
    lista_metas = []
    for m in metas:
        falta = max(Decimal(0), m["valor_objetivo"] - m["ahorrado"])
        meses_rest = _meses_hasta(m["fecha_objetivo"], hoy_mes) if m["fecha_objetivo"] else None
        lista_metas.append({**m, "falta": falta, "avance": min(Decimal(100), m["ahorrado"] * 100 / m["valor_objetivo"]),
                            "meses_restantes": meses_rest,
                            "cuota_mensual": (falta / meses_rest).quantize(Decimal("1")) if meses_rest and falta else Decimal(0)})
    cuotas = sum((m["compromiso_mensual"] or m["cuota_mensual"] for m in lista_metas), Decimal(0))
    mes_info = movimientos_del_mes(conn, anestesiologo_id, mes, gastos)
    seguimiento_compromisos(conn, anestesiologo_id, lista_metas, mes, _primer_dia(hoy))
    emergencia = [m for m in metas if m["tipo"] == "EMERGENCIA"]
    meses_colchon = (sum((m["ahorrado"] for m in emergencia), Decimal(0)) / total_gastos) if total_gastos else None

    consejos = []
    if not meses:
        consejos.append(("INFO", "Sube tus reportes de pago o tus volantes en la pestaña Pagos para calcular tu ingreso base."))
    elif len(meses) < 3:
        consejos.append(("INFO", f"Tu ingreso base se calcula con {len(meses)} mes(es). Con al menos 3 meses será más confiable."))
    if base and total_gastos:
        if pct(total_gastos) > LIMITE_GASTOS:
            consejos.append(("MUY_ALTO" if pct(total_gastos) > 100 else "ALTO",
                             f"Tus gastos son el {_num(pct(total_gastos))} % de tu ingreso base. Lo sano es no pasar del "
                             f"{LIMITE_GASTOS} % para poder ahorrar al menos el 20 %."))
        if pct(fijos) > LIMITE_FIJOS:
            consejos.append(("ALTO", f"Tus gastos fijos son el {_num(pct(fijos))} % del ingreso base (lo sano es hasta "
                                     f"el {LIMITE_FIJOS} %): un mes de recaudo bajo te deja sin margen."))
        for c in por_categoria:
            if c["estado"] != "SANO":
                consejos.append((c["estado"], f"{c['nombre']}: {_num(c['porcentaje'])} % del ingreso base; la referencia "
                                              f"sana es hasta el {c['referencia']} %."))
    if total_gastos and not emergencia:
        consejos.append(("ALTO", f"Crea un fondo de emergencias de {MESES_EMERGENCIA} meses de gastos "
                                 f"({_pesos(total_gastos * MESES_EMERGENCIA)}). Con ingresos variables es la primera meta."))
    elif meses_colchon is not None and meses_colchon < MESES_EMERGENCIA:
        consejos.append(("INFO", f"Tu fondo de emergencias cubre {_num(meses_colchon)} meses de gastos; la meta es "
                                 f"{MESES_EMERGENCIA}."))
    if cuotas and capacidad < cuotas:
        consejos.append(("MUY_ALTO" if capacidad <= 0 else "ALTO",
                         f"Tus metas piden {_pesos(cuotas)} al mes y tu capacidad de ahorro es {_pesos(max(capacidad, 0))}: "
                         "amplía los plazos o reduce gastos."))
    if meses and base_ap:
        ultimo = meses[0]
        excedente = ultimo["total"] - base_ap
        if excedente > 0:
            consejos.append(("SANO", f"En {ultimo['periodo']:%m/%Y} entraron {_pesos(excedente)} por encima de tu ingreso "
                                     "base: llévalos a tus metas (primero al fondo de emergencias) en lugar de gastarlos."))

    # ---- fase 2: lo que viene, ahorros de AP, proyección de metas, créditos y vivienda
    por_cobrar = ingresos_por_cobrar(conn, anestesiologo_id, hoy)
    ahorros = ahorros_ap(conn, anestesiologo_id)
    proyectar_metas(lista_metas, capacidad, hoy_mes)
    creditos = analizar_creditos(gastos, hoy)
    for m in lista_metas:
        if m["fecha_objetivo"] and m["fecha_estimada"] and not m["a_tiempo"]:
            consejos.append(("ALTO", f"Con tu capacidad de ahorro actual, «{m['nombre']}» se cumpliría en "
                                     f"{m['fecha_estimada']:%m/%Y}, después de la fecha que te pusiste."))
    for m in lista_metas:
        if not m["compromiso_mensual"] or not m["falta"]:
            continue
        if m["cumple_mes"]:
            consejos.append(("SANO", f"Cumpliste tu compromiso de {mes:%m/%Y} con «{m['nombre']}»"
                                     + (f": llevas {m['racha']} meses seguidos." if m["racha"] > 1 else ".")))
        elif mes == _primer_dia(hoy):
            consejos.append(("INFO", f"Este mes llevas {_pesos(m['aportado_mes'])} de tu compromiso de "
                                     f"{_pesos(m['compromiso_mensual'])} para «{m['nombre']}»."))
        if m["fecha_objetivo"] and m["fecha_con_compromiso"] and m["fecha_con_compromiso"] > _primer_dia(m["fecha_objetivo"]):
            consejos.append(("ALTO", f"Con tu compromiso de {_pesos(m['compromiso_mensual'])} al mes, «{m['nombre']}» "
                                     f"se cumple en {m['fecha_con_compromiso']:%m/%Y}: para llegar a tiempo necesitas "
                                     f"{_pesos(m['cuota_mensual'])} al mes."))
    for c in mes_info["categorias"]:
        if c["estado"] in ("ALTO", "MUY_ALTO"):
            consejos.append((c["estado"], f"En {mes:%m/%Y} llevas {_pesos(c['real'])} en {c['nombre'].split(' (')[0].lower()}, "
                                          f"el {_num(c['uso'])} % de lo presupuestado ({_pesos(c['presupuesto'])})."))
    if creditos["recomendacion"]:
        consejos.append(("INFO", creditos["recomendacion"]))
    if ahorros and emergencia and meses_colchon is not None and meses_colchon < MESES_EMERGENCIA:
        consejos.append(("INFO", "Cuando AP te pague la compensación semestral o la anual, llévala primero al fondo "
                                 "de emergencias hasta completar 6 meses de gastos."))

    return {
        "por_cobrar": por_cobrar, "ahorros_ap": ahorros, "creditos": creditos, "mes": mes_info,
        "meses": meses, "ingreso_base_ap": base_ap.quantize(Decimal("1")), "promedio_ap": promedio_ap.quantize(Decimal("1")),
        "meses_base": len(bajos), "otros_ingresos": otros, "ingreso_base": base.quantize(Decimal("1")),
        "gastos": total_gastos, "gastos_fijos": fijos, "capacidad_ahorro": capacidad.quantize(Decimal("1")),
        "tasa_ahorro": pct(capacidad).quantize(Decimal("0.1")) if base else None,
        "porcentaje_gastos": pct(total_gastos).quantize(Decimal("0.1")) if base else None,
        "estado_gastos": semaforo(pct(total_gastos), Decimal(LIMITE_GASTOS)) if base and total_gastos else None,
        "por_categoria": por_categoria, "partidas": partidas, "metas": lista_metas, "cuotas_metas": cuotas,
        "meses_colchon": meses_colchon.quantize(Decimal("0.1")) if meses_colchon is not None else None,
        "fondo_sugerido": total_gastos * MESES_EMERGENCIA,
        "consejos": [{"nivel": n, "texto": t} for n, t in consejos],
    }


# ------------------------------------------------------------------ fase 2
REZAGO_DIAS_DEFECTO = 60          # si aún no hay pagos para medir cuánto tarda AP en pagar una cirugía
DIAS_PENDIENTE_MAX = 180          # cirugías más viejas sin pagar no se proyectan: se reportan como atrasadas


def _sumar_meses(d: date, n: int) -> date:
    anio, mes = divmod(d.month - 1 + n, 12)
    return date(d.year + anio, mes + 1, 1)


def _mediana(valores: list) -> Decimal:
    v = sorted(valores)
    medio = len(v) // 2
    return Decimal(v[medio]) if len(v) % 2 else (Decimal(v[medio - 1]) + Decimal(v[medio])) / 2


def ingresos_por_cobrar(conn, anestesiologo_id: int, hoy: date) -> Optional[dict]:
    """Estima cuándo y cuánto pagará AP por las cirugías realizadas y aún no pagadas, con lo que AP ha pagado
    antes: el neto promedio por paciente (por aseguradora si hay suficientes pagos) y el tiempo típico de pago."""
    pagos = conn.execute(
        """SELECT d.neto, d.fecha_servicio, r.fecha_proceso, cb.aseguradora_id
             FROM pago_detalle d JOIN reporte_pago r USING (reporte_id)
             LEFT JOIN cirugia c ON c.cirugia_id = d.cirugia_id
             LEFT JOIN cobertura cb ON cb.cobertura_id = c.cobertura_id
            WHERE r.anestesiologo_id = %s AND d.es_paciente AND d.neto > 0""", (anestesiologo_id,)).fetchall()
    if not pagos:
        return None
    promedio = sum((p["neto"] for p in pagos), Decimal(0)) / len(pagos)
    por_aseguradora: dict[int, list] = {}
    for p in pagos:
        if p["aseguradora_id"]:
            por_aseguradora.setdefault(p["aseguradora_id"], []).append(p["neto"])
    rezagos = [(p["fecha_proceso"] - p["fecha_servicio"]).days for p in pagos
               if p["fecha_proceso"] and p["fecha_servicio"] and p["fecha_proceso"] >= p["fecha_servicio"]]
    rezago = int(_mediana(rezagos)) if rezagos else REZAGO_DIAS_DEFECTO

    pendientes = conn.execute(
        """SELECT c.fecha_procedimiento, cb.aseguradora_id FROM cirugia c
             JOIN cobertura cb ON cb.cobertura_id = c.cobertura_id
            WHERE c.anestesiologo_id = %s AND c.estado NOT IN ('PAGADA', 'CANCELADA')
              -- ya aparece en un reporte de pagos (aunque no se haya aplicado): no está por cobrar
              AND NOT EXISTS (SELECT 1 FROM pago_detalle d WHERE d.cirugia_id = c.cirugia_id)""",
        (anestesiologo_id,)).fetchall()
    primer_mes = _primer_dia(hoy) if hoy.day <= 7 else _sumar_meses(hoy, 1)  # AP procesa a inicio de mes
    por_mes: dict[date, dict] = {}
    atrasadas = 0
    for c in pendientes:
        if (hoy - c["fecha_procedimiento"]).days > DIAS_PENDIENTE_MAX:
            atrasadas += 1
            continue
        valores = por_aseguradora.get(c["aseguradora_id"], [])
        valor = sum(valores, Decimal(0)) / len(valores) if len(valores) >= 2 else promedio
        mes = max(_primer_dia(date.fromordinal(c["fecha_procedimiento"].toordinal() + rezago)), primer_mes)
        grupo = por_mes.setdefault(mes, {"periodo": mes, "cirugias": 0, "recaudo": Decimal(0)})
        grupo["cirugias"] += 1
        grupo["recaudo"] += valor
    meses = []
    for mes in sorted(por_mes):
        g = por_mes[mes]
        l = liquidacion.liquidar(g["recaudo"], mes.year)
        meses.append({**g, "recaudo": l["recaudo"], "te_llega": l["neto"] + l["devengados"]["probienestar"]})
    return {"cirugias": sum(m["cirugias"] for m in meses), "atrasadas": atrasadas, "rezago_dias": rezago,
            "valor_promedio": promedio.quantize(Decimal("1")), "meses": meses,
            "total_te_llega": sum((m["te_llega"] for m in meses), Decimal(0))}


def ahorros_ap(conn, anestesiologo_id: int) -> Optional[dict]:
    """Ahorros que AP guarda por el anestesiólogo, según el último volante que los trae."""
    for v in conn.execute("""SELECT periodo, datos_extraidos FROM volante_pago WHERE anestesiologo_id = %s
                              ORDER BY periodo DESC""", (anestesiologo_id,)):
        d = v["datos_extraidos"] or {}
        if d.get("acumulado_semestral") is not None or d.get("acumulado_anual") is not None:
            valor = lambda k: Decimal(str(d.get(k) or 0))  # noqa: E731
            semestral, anual, vacaciones = valor("acumulado_semestral"), valor("acumulado_anual"), valor("acumulado_vacaciones")
            return {"periodo": v["periodo"], "semestral": semestral, "anual": anual, "vacaciones": vacaciones,
                    "aporte_sindical": valor("acumulado_aporte_sindical"), "total": semestral + anual + vacaciones,
                    # AP paga la semestral con los cortes de junio y diciembre (confirmado)
                    "proximo_semestral": "junio" if v["periodo"].month < 6 else "diciembre"}
    return None


def proyectar_metas(metas: list[dict], capacidad: Decimal, desde: date, limite: int = 240) -> None:
    """Simula mes a mes el ahorro: primero el fondo de emergencias, luego las metas por fecha. Cada meta con
    fecha recibe su cuota; lo que sobre se va a las demás en orden. Agrega fecha_estimada y a_tiempo."""
    orden = sorted(metas, key=lambda m: (m["tipo"] != "EMERGENCIA", m["fecha_objetivo"] or date.max))
    falta = {id(m): m["falta"] for m in orden}
    for m in orden:
        m["fecha_estimada"] = desde if not m["falta"] else None
    disponible_mes = max(capacidad, Decimal(0))
    for n in range(1, limite + 1):
        if disponible_mes <= 0 or all(falta[id(m)] <= 0 for m in orden):
            break
        disponible = disponible_mes
        for m in orden:  # primero lo comprometido (o la cuota de las metas con fecha)
            cuota = m.get("compromiso_mensual") or m["cuota_mensual"]
            if cuota and falta[id(m)] > 0:
                aporte = min(cuota, falta[id(m)], disponible)
                falta[id(m)] -= aporte
                disponible -= aporte
        for m in orden:  # lo que sobra, en orden de prioridad
            if disponible <= 0:
                break
            aporte = min(falta[id(m)], disponible)
            falta[id(m)] -= aporte
            disponible -= aporte
        for m in orden:
            if falta[id(m)] <= 0 and m["fecha_estimada"] is None:
                m["fecha_estimada"] = _sumar_meses(desde, n)
    for m in orden:
        m["a_tiempo"] = (m["fecha_estimada"] is not None and m["fecha_objetivo"] is not None
                         and m["fecha_estimada"] <= _primer_dia(m["fecha_objetivo"]))


def analizar_creditos(gastos: list[dict], hoy: Optional[date] = None) -> dict:
    """Meses para terminar de pagar cada crédito y cuál conviene abonar primero (el de tasa más alta)."""
    creditos = []
    for g in gastos:
        if g["categoria"] != "DEUDAS":
            continue
        c = {"partida_id": g["partida_id"], "nombre": g["nombre"], "cuota": g["valor_mensual"], "saldo": g["saldo"],
             "tasa_ea": g["tasa_ea"], "meses": None, "intereses": None, "fecha_fin": None, "cubre_intereses": True}
        if g["saldo"] and g["tasa_ea"] is not None and g["valor_mensual"]:
            r = (1 + float(g["tasa_ea"]) / 100) ** (1 / 12) - 1
            saldo, cuota = float(g["saldo"]), float(g["valor_mensual"])
            if r == 0:
                n = math.ceil(saldo / cuota)
            elif cuota <= saldo * r:
                c["cubre_intereses"] = False
                n = None
            else:
                n = math.ceil(-math.log(1 - r * saldo / cuota) / math.log(1 + r))
            if n:
                c["meses"] = n
                c["intereses"] = Decimal(max(0, round(n * cuota - saldo)))
                c["fecha_fin"] = _sumar_meses(hoy or date.today(), n)
        creditos.append(c)
    con_tasa = sorted((c for c in creditos if c["tasa_ea"] is not None and c["saldo"]), key=lambda c: -c["tasa_ea"])
    recomendacion = None
    malos = [c for c in creditos if not c["cubre_intereses"]]
    if malos:
        recomendacion = (f"La cuota de «{malos[0]['nombre']}» no alcanza ni para los intereses: la deuda crece cada mes. "
                         "Habla con el banco o súbele la cuota.")
    elif len(con_tasa) >= 2:
        recomendacion = (f"Si te sobra plata, abónala a «{con_tasa[0]['nombre']}» ({_num(con_tasa[0]['tasa_ea'], 2)} % EA): es "
                         "el crédito más caro. Paga la cuota mínima en los demás.")
    return {"creditos": creditos, "saldo_total": sum((c["saldo"] or Decimal(0) for c in creditos), Decimal(0)),
            "recomendacion": recomendacion}


USO_ALTO = Decimal(110)   # gastar hasta 10 % más de lo presupuestado: "alto"; más: "muy alto"


def movimientos_del_mes(conn, anestesiologo_id: int, mes: date, gastos_presupuesto: list[dict]) -> dict:
    """Gastos reales del mes contra el presupuesto, por categoría, y los movimientos registrados."""
    hasta = _sumar_meses(mes, 1)
    movimientos = conn.execute(
        """SELECT m.movimiento_id, m.fecha, m.clase, m.categoria, m.meta_id, f.nombre AS meta, m.descripcion, m.valor,
                  m.cuenta_id, NULLIF(concat_ws(' ', c.banco, c.ultimos_digitos), '') AS cuenta
             FROM fin_movimiento m LEFT JOIN fin_meta f ON f.meta_id = m.meta_id
             LEFT JOIN fin_cuenta c ON c.cuenta_id = m.cuenta_id
            WHERE m.anestesiologo_id = %s AND m.fecha >= %s AND m.fecha < %s
            ORDER BY m.fecha DESC, m.movimiento_id DESC""", (anestesiologo_id, mes, hasta)).fetchall()
    nombres = {c: n for c, n, _, _ in CATEGORIAS}
    presupuesto: dict[str, Decimal] = {}
    for g in gastos_presupuesto:
        presupuesto[g["categoria"]] = presupuesto.get(g["categoria"], Decimal(0)) + g["valor_mensual"]
    real: dict[str, Decimal] = {}
    for m in movimientos:
        if m["clase"] == "GASTO":
            real[m["categoria"]] = real.get(m["categoria"], Decimal(0)) + m["valor"]
    categorias = []
    for clave, nombre, _, _ in CATEGORIAS:
        p, r = presupuesto.get(clave, Decimal(0)), real.get(clave, Decimal(0))
        if not p and not r:
            continue
        uso = (r * 100 / p) if p else None
        estado_cat = ("SIN_PRESUPUESTO" if not p else "SANO" if uso <= 100 else "ALTO" if uso <= USO_ALTO else "MUY_ALTO")
        categorias.append({"categoria": clave, "nombre": nombres[clave], "presupuesto": p, "real": r,
                           "uso": uso.quantize(Decimal("0.1")) if uso is not None else None, "estado": estado_cat})
    total_p, total_r = sum(presupuesto.values(), Decimal(0)), sum(real.values(), Decimal(0))
    aportes = sum((m["valor"] for m in movimientos if m["clase"] == "APORTE"), Decimal(0))
    # gastos y ahorros de los 6 meses que terminan en el elegido, para la gráfica
    desde = _sumar_meses(mes, -5)
    por_mes = {r["periodo"]: r for r in conn.execute(
        """SELECT date_trunc('month', fecha)::date AS periodo,
                  COALESCE(SUM(valor) FILTER (WHERE clase = 'GASTO'), 0) AS gastos,
                  COALESCE(SUM(valor) FILTER (WHERE clase = 'APORTE'), 0) AS aportes
             FROM fin_movimiento WHERE anestesiologo_id = %s AND fecha >= %s AND fecha < %s GROUP BY 1""",
        (anestesiologo_id, desde, hasta))}
    historial = [{"periodo": p, "gastos": por_mes[p]["gastos"] if p in por_mes else Decimal(0),
                  "aportes": por_mes[p]["aportes"] if p in por_mes else Decimal(0)}
                 for p in (_sumar_meses(desde, i) for i in range(6))]
    return {"periodo": mes, "categorias": categorias, "presupuesto": total_p, "real": total_r, "aportes": aportes,
            "disponible": total_p - total_r, "movimientos": movimientos, "historial": historial}


def seguimiento_compromisos(conn, anestesiologo_id: int, metas: list[dict], mes: date, mes_actual: date) -> None:
    """Para cada meta con compromiso: lo aportado en el mes, si cumplió, la racha de meses seguidos cumplidos
    y el historial de los últimos 6 meses. También en qué mes se cumple la meta ahorrando el compromiso."""
    filas = conn.execute(
        """SELECT meta_id, date_trunc('month', fecha)::date AS periodo, SUM(valor) AS total FROM fin_movimiento
            WHERE anestesiologo_id = %s AND clase = 'APORTE' GROUP BY 1, 2""", (anestesiologo_id,)).fetchall()
    aportes = {(f["meta_id"], f["periodo"]): f["total"] for f in filas}
    for m in metas:
        compromiso, inicio = m["compromiso_mensual"], m["comprometido_en"]
        m.update({"aportado_mes": aportes.get((m["meta_id"], mes), Decimal(0)), "cumple_mes": None,
                  "racha": 0, "historial": [], "fecha_con_compromiso": None})
        if not compromiso:
            continue
        cumple = lambda p: aportes.get((m["meta_id"], p), Decimal(0)) >= compromiso  # noqa: E731
        m["cumple_mes"] = cumple(mes)
        if m["falta"]:
            m["fecha_con_compromiso"] = _sumar_meses(mes_actual, math.ceil(m["falta"] / compromiso))
        # racha: meses seguidos cumplidos hasta el actual (el actual cuenta si ya se cumplió)
        p = mes_actual if cumple(mes_actual) else _sumar_meses(mes_actual, -1)
        while p >= inicio and cumple(p):
            m["racha"] += 1
            p = _sumar_meses(p, -1)
        for n in range(5, -1, -1):
            p = _sumar_meses(mes_actual, -n)
            if p < inicio:
                continue
            m["historial"].append({"periodo": p, "aportado": aportes.get((m["meta_id"], p), Decimal(0)),
                                   "estado": "CUMPLIDO" if cumple(p) else ("EN_CURSO" if p == mes_actual else "NO_CUMPLIDO")})


def catalogos() -> dict:
    return {"gastos": [{"clave": c, "nombre": n, "referencia": r, "tipo": t} for c, n, r, t in CATEGORIAS],
            "ingresos": [{"clave": c, "nombre": n} for c, n in CATEGORIAS_INGRESO],
            "metas": [{"clave": c, "nombre": n} for c, n in TIPOS_META]}
