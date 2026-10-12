"""Finanzas personales de cada anestesiólogo: ingresos (volantes de AP + ingresos adicionales),
presupuesto de gastos con semáforo y metas de ahorro.

Criterio: con ingresos tan variables, el presupuesto se arma sobre el INGRESO BASE (promedio de los
3 meses más bajos de los últimos 12), no sobre el promedio; lo que entre por encima se reparte a metas.
Los porcentajes de referencia son guías generales de finanzas personales, no asesoría individual.
"""
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
        """SELECT partida_id, clase, categoria, nombre, valor_mensual FROM fin_partida
            WHERE anestesiologo_id = %s ORDER BY clase, categoria, partida_id""", (anestesiologo_id,)).fetchall()


def crear_partida(conn, anestesiologo_id: int, clase: str, categoria: str, nombre: str, valor: Decimal) -> int:
    return conn.execute(
        """INSERT INTO fin_partida (anestesiologo_id, clase, categoria, nombre, valor_mensual)
           VALUES (%s, %s, %s, %s, %s) RETURNING partida_id""",
        (anestesiologo_id, clase, categoria, nombre, valor)).fetchone()["partida_id"]


def actualizar_partida(conn, anestesiologo_id: int, partida_id: int, categoria: str, nombre: str, valor: Decimal) -> bool:
    return conn.execute(
        """UPDATE fin_partida SET categoria = %s, nombre = %s, valor_mensual = %s
            WHERE partida_id = %s AND anestesiologo_id = %s""",
        (categoria, nombre, valor, partida_id, anestesiologo_id)).rowcount == 1


def borrar_partida(conn, anestesiologo_id: int, partida_id: int) -> bool:
    return conn.execute("DELETE FROM fin_partida WHERE partida_id = %s AND anestesiologo_id = %s",
                        (partida_id, anestesiologo_id)).rowcount == 1


def listar_metas(conn, anestesiologo_id: int) -> list[dict]:
    return conn.execute(
        """SELECT meta_id, tipo, nombre, valor_objetivo, ahorrado, fecha_objetivo FROM fin_meta
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


def borrar_meta(conn, anestesiologo_id: int, meta_id: int) -> bool:
    return conn.execute("DELETE FROM fin_meta WHERE meta_id = %s AND anestesiologo_id = %s",
                        (meta_id, anestesiologo_id)).rowcount == 1


# ------------------------------------------------------------------ estado financiero
def _meses_hasta(fecha: date, hoy: date) -> int:
    return max(1, (fecha.year - hoy.year) * 12 + fecha.month - hoy.month)


def _pesos(v) -> str:
    return f"${Decimal(v):,.0f}".replace(",", ".")


def estado(conn, anestesiologo_id: int, hoy: Optional[date] = None) -> dict:
    hoy = hoy or date.today()
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
    cuotas = sum((m["cuota_mensual"] for m in lista_metas), Decimal(0))
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
                             f"Tus gastos son el {pct(total_gastos):.0f} % de tu ingreso base. Lo sano es no pasar del "
                             f"{LIMITE_GASTOS} % para poder ahorrar al menos el 20 %."))
        if pct(fijos) > LIMITE_FIJOS:
            consejos.append(("ALTO", f"Tus gastos fijos son el {pct(fijos):.0f} % del ingreso base (lo sano es hasta "
                                     f"el {LIMITE_FIJOS} %): un mes de recaudo bajo te deja sin margen."))
        for c in por_categoria:
            if c["estado"] != "SANO":
                consejos.append((c["estado"], f"{c['nombre']}: {c['porcentaje']:.0f} % del ingreso base; la referencia "
                                              f"sana es hasta el {c['referencia']} %."))
    if total_gastos and not emergencia:
        consejos.append(("ALTO", f"Crea un fondo de emergencias de {MESES_EMERGENCIA} meses de gastos "
                                 f"({_pesos(total_gastos * MESES_EMERGENCIA)}). Con ingresos variables es la primera meta."))
    elif meses_colchon is not None and meses_colchon < MESES_EMERGENCIA:
        consejos.append(("INFO", f"Tu fondo de emergencias cubre {meses_colchon:.1f} meses de gastos; la meta es "
                                 f"{MESES_EMERGENCIA}.".replace(".", ",", 1)))
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

    return {
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


def catalogos() -> dict:
    return {"gastos": [{"clave": c, "nombre": n, "referencia": r, "tipo": t} for c, n, r, t in CATEGORIAS],
            "ingresos": [{"clave": c, "nombre": n} for c, n in CATEGORIAS_INGRESO],
            "metas": [{"clave": c, "nombre": n} for c, n in TIPOS_META]}
