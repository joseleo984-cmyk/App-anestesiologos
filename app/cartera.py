"""Cartera del anestesiólogo: lo cobrado, lo que falta por cobrar y desde hace cuánto (pantalla de Inicio),
y el recorrido del cobro de cada cirugía."""
from datetime import date
from decimal import Decimal
from typing import Optional

from app import finanzas, repositorio

# Franjas de antigüedad de lo que falta por cobrar (días desde la cirugía)
FRANJAS = [(0, 90), (91, 180), (181, finanzas.DIAS_PENDIENTE_MAX), (finanzas.DIAS_PENDIENTE_MAX + 1, None)]
MIN_PAGOS_CLINICA = 3  # pagos de una clínica para usar su propia demora típica


def _mes_anterior(d: date) -> date:
    return date(d.year - (d.month == 1), (d.month - 2) % 12 + 1, 1)


def resumen(conn, anestesiologo_id: int, hoy: Optional[date] = None) -> dict:
    hoy = hoy or date.today()
    mes = hoy.replace(day=1)
    cobrado = conn.execute(
        """SELECT COALESCE(SUM(valor_honorarios) FILTER (WHERE fecha_pago >= %(mes)s), 0) AS este,
                  COALESCE(SUM(valor_honorarios) FILTER (WHERE fecha_pago >= %(ant)s AND fecha_pago < %(mes)s), 0) AS anterior
             FROM cirugia WHERE anestesiologo_id = %(a)s AND estado = 'PAGADA' AND fecha_pago >= %(ant)s
              AND fecha_pago <= %(hoy)s""",
        {"a": anestesiologo_id, "mes": mes, "ant": _mes_anterior(mes), "hoy": hoy}).fetchone()
    pendientes = conn.execute(
        """SELECT %(hoy)s::date - fecha_procedimiento AS dias, valor_honorarios AS valor FROM cirugia
            WHERE anestesiologo_id = %(a)s AND estado NOT IN ('PAGADA', 'CANCELADA')
              AND fecha_procedimiento <= %(hoy)s""", {"a": anestesiologo_id, "hoy": hoy}).fetchall()
    franjas = []
    for desde, hasta in FRANJAS:
        dentro = [p for p in pendientes if p["dias"] >= desde and (hasta is None or p["dias"] <= hasta)]
        franjas.append({"desde": desde, "hasta": hasta, "cirugias": len(dentro),
                        "valor": sum((p["valor"] or Decimal(0) for p in dentro), Decimal(0)),
                        "sin_valor": sum(1 for p in dentro if p["valor"] is None)})
    sin_valor = conn.execute(
        """SELECT count(*) AS n FROM cirugia WHERE anestesiologo_id = %s AND estado <> 'CANCELADA'
              AND valor_honorarios IS NULL AND fecha_procedimiento <= %s""", (anestesiologo_id, hoy)).fetchone()["n"]
    por_cobrar = finanzas.ingresos_por_cobrar(conn, anestesiologo_id, hoy)
    proximo = None
    if por_cobrar and por_cobrar["meses"]:
        m = por_cobrar["meses"][0]
        proximo = {"periodo": m["periodo"], "cirugias": m["cirugias"], "te_llega": m["te_llega"]}
    return {
        "hoy": hoy,
        "cobrado_mes": cobrado["este"], "cobrado_mes_anterior": cobrado["anterior"],
        "por_cobrar": {"cirugias": len(pendientes),
                       "valor": sum((p["valor"] or Decimal(0) for p in pendientes), Decimal(0)),
                       "sin_valor": sum(1 for p in pendientes if p["valor"] is None)},
        "antiguedad": franjas,
        "atrasadas": franjas[-1]["cirugias"],
        "sin_valor": sin_valor,
        "por_aplicar": repositorio.por_aplicar(conn, anestesiologo_id),
        "proximo_pago": proximo,
        "dias_atraso": finanzas.DIAS_PENDIENTE_MAX,
    }


def _mediana(valores: list[int]) -> Optional[int]:
    if not valores:
        return None
    v = sorted(valores)
    return v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) // 2


def demora_tipica(conn, anestesiologo_id: int, clinica_id: int) -> tuple[Optional[int], str]:
    """Días que suele tardar el pago: los de esa clínica si hay suficientes pagos; si no, los de todas."""
    filas = conn.execute(
        """SELECT clinica_id, fecha_pago - fecha_procedimiento AS dias FROM cirugia
            WHERE anestesiologo_id = %s AND estado = 'PAGADA' AND fecha_pago >= fecha_procedimiento""",
        (anestesiologo_id,)).fetchall()
    propias = [f["dias"] for f in filas if f["clinica_id"] == clinica_id]
    if len(propias) >= MIN_PAGOS_CLINICA:
        return _mediana(propias), "CLINICA"
    todas = [f["dias"] for f in filas]
    return (_mediana(todas), "GENERAL") if len(todas) >= MIN_PAGOS_CLINICA else (None, "GENERAL")


def cobro(conn, anestesiologo_id: int, cirugia_id: int, hoy: Optional[date] = None) -> Optional[dict]:
    """Pasos del cobro: realizada → entregada a AP → en un reporte de pagos → pagada, con los días."""
    hoy = hoy or date.today()
    c = conn.execute(
        """SELECT c.cirugia_id, c.clinica_id, c.fecha_procedimiento, c.estado, c.fecha_pago, c.valor_honorarios,
                  cl.nombre AS clinica
             FROM cirugia c JOIN clinica cl USING (clinica_id)
            WHERE c.cirugia_id = %s AND c.anestesiologo_id = %s""", (cirugia_id, anestesiologo_id)).fetchone()
    if c is None:
        return None
    docs = conn.execute(
        """SELECT r.reporte_id, r.tipo, r.numero, r.pagador, r.fecha_proceso, r.estado, d.neto
             FROM pago_detalle d JOIN reporte_pago r USING (reporte_id)
            WHERE d.cirugia_id = %s AND r.anestesiologo_id = %s ORDER BY r.fecha_proceso NULLS LAST, r.reporte_id""",
        (cirugia_id, anestesiologo_id)).fetchall()
    relacion = next((d for d in docs if d["tipo"] == "RELACION"), None)
    reporte = next((d for d in docs if d["tipo"] == "PAGOS"), None)
    pagada = c["estado"] == "PAGADA"
    cancelada = c["estado"] == "CANCELADA"
    realizada = c["fecha_procedimiento"] <= hoy
    entregada = pagada or c["estado"] == "FACTURADA" or relacion is not None
    pasos = [
        {"clave": "REALIZADA", "titulo": "Realizada" if realizada else "Programada",
         "hecho": realizada, "fecha": c["fecha_procedimiento"], "detalle": c["clinica"]},
        {"clave": "ENTREGADA", "titulo": "Entregada a AP", "hecho": entregada,
         "fecha": relacion["fecha_proceso"] if relacion else None,
         "detalle": (f"Relación Nº {relacion['numero']}" if relacion and relacion["numero"]
                     else "En una relación de AP" if relacion else "Facturada" if entregada else None)},
        {"clave": "REPORTE", "titulo": "En un reporte de pagos", "hecho": reporte is not None or pagada,
         "fecha": reporte["fecha_proceso"] if reporte else None,
         "detalle": reporte["pagador"] if reporte else None},
        {"clave": "PAGADA", "titulo": "Pagada", "hecho": pagada, "fecha": c["fecha_pago"],
         "detalle": None},
    ]
    if relacion and not reporte:  # pago global (ej. Santa Ana): la relación es el soporte del pago
        pasos[2]["detalle"] = "Pago global de la clínica" if pagada else None
    fin = c["fecha_pago"] if pagada and c["fecha_pago"] else hoy
    dias = (fin - c["fecha_procedimiento"]).days if realizada else None
    tipica, base = demora_tipica(conn, anestesiologo_id, c["clinica_id"])
    if cancelada or not realizada or pagada:
        situacion = "CANCELADA" if cancelada else "PROGRAMADA" if not realizada else "PAGADA"
    elif dias > finanzas.DIAS_PENDIENTE_MAX:
        situacion = "ATRASADA"
    elif tipica is not None and dias > tipica + 30:
        situacion = "DEMORADA"
    else:
        situacion = "A_TIEMPO"
    actual = next((p["clave"] for p in pasos if not p["hecho"]), None)
    return {"pasos": pasos, "actual": None if cancelada else actual, "dias": dias, "situacion": situacion,
            "demora_tipica": tipica, "demora_base": base, "clinica": c["clinica"]}
