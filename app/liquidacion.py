"""Liquidación del volante de pago de AP (Anestesiólogos Permanentes) a partir del recaudo del mes.

Fórmula de la "Propuesta para plataforma de liquidación de compensaciones y auxilios", verificada al
peso contra el volante de octubre de 2026:

    recaudo (neto del reporte de pagos)
    - fondo probienestar 20 %, administración 5 %, compensación semestral 2,85 %,
      compensación anual 2,85 %, vacaciones 1 %                    -> base del contrato sindical
    - seguridad social 12,1 % de la base                           -> valor a distribuir en el volante
    reparto: 60 % compensaciones (ordinaria = 1 SMLMV, el resto extraordinaria) y 40 % auxilio sindical.
    deducciones: salud 4 % y pensión 4 % de las compensaciones, 4 x mil del valor distribuido y cuota de
    sostenimiento del 5 % del SMLMV.
    Recaudo bajo (el 60 % no alcanza a 1 SMLMV): todo es compensación, sin auxilio; salud y pensión sobre
    1 SMLMV y una deducción de "ajuste sindical" para completar la seguridad social.
    La retención en la fuente (meses altos) no se calcula: se toma del volante al comparar.
    Si AP descuenta la suscripción de la app (variable SUSCRIPCION_APP), va como una deducción más.
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from app import config

PORCENTAJES = {
    "probienestar": Decimal("0.20"),
    "administracion": Decimal("0.05"),
    "semestral": Decimal("0.0285"),
    "anual": Decimal("0.0285"),
    "vacaciones": Decimal("0.01"),
    "seguridad_social": Decimal("0.121"),     # sobre la base del contrato
    "compensaciones": Decimal("0.60"),        # del valor a distribuir; el resto es auxilio sindical
    "salud": Decimal("0.04"),
    "pension": Decimal("0.04"),
    "cuatro_por_mil": Decimal("0.004"),
    "cuota_sostenimiento": Decimal("0.05"),   # del SMLMV
    "ss_asociacion": Decimal("0.22936"),      # lo que la asociación paga de salud, pensión y riesgos (S,P,A)
    # En recaudo bajo el ajuste sindical es 22,936 % del SMLMV menos 8,3 % del recaudo
    # (deducido de los volantes de mayo y septiembre de 2026; cuadra con 1 a 3 pesos de diferencia)
    "ss_recaudo_bajo": Decimal("0.083"),
}

# Salario mínimo por año (se puede cambiar con la variable SMLMV en Render)
SMLMV = {2026: Decimal("1750905")}


def smlmv(anio: Optional[int]) -> Decimal:
    if config.SMLMV:
        return Decimal(config.SMLMV)
    if anio in SMLMV:
        return SMLMV[anio]
    return SMLMV[max(SMLMV)]


def _pct(v: Decimal, decimales: int = 1) -> str:
    return f"{v * 100:.{decimales}f}".replace(".", ",") + " %"


def _peso(v: Decimal) -> Decimal:
    return v.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def suscripcion_app() -> Decimal:
    return Decimal(config.SUSCRIPCION_APP) if config.SUSCRIPCION_APP else Decimal(0)


def liquidar(recaudo: Decimal, anio: Optional[int] = None, suscripcion: Optional[Decimal] = None) -> dict:
    """Volante calculado: líneas de apropiación, devengados, deducciones, neto y alertas."""
    p, minimo = PORCENTAJES, smlmv(anio)
    recaudo = Decimal(recaudo)
    apropiaciones = {k: recaudo * p[k] for k in ("probienestar", "administracion", "semestral", "anual", "vacaciones")}
    base = recaudo - sum(apropiaciones.values())
    seguridad_social = base * p["seguridad_social"]
    distribuir = _peso(base - seguridad_social)

    sesenta = _peso(distribuir * p["compensaciones"])
    bajo = sesenta < minimo
    alertas, ajuste = [], Decimal(0)
    if not bajo:  # mes normal: 60 % compensaciones (ordinaria = 1 SMLMV) y 40 % auxilio sindical
        compensaciones, ibc = sesenta, sesenta
    else:
        # Recaudo bajo (como en los volantes de mayo y septiembre): todo va como compensación, sin auxilio;
        # salud y pensión sobre 1 SMLMV, y un "ajuste sindical" completa la seguridad social de la asociación
        compensaciones, ibc = distribuir, min(minimo, distribuir)
        ajuste = max(Decimal(0), _peso(minimo * p["ss_asociacion"] - recaudo * p["ss_recaudo_bajo"]))
        umbral = minimo / p["compensaciones"] / (1 - p["seguridad_social"]) / (
            1 - sum(p[k] for k in ("probienestar", "administracion", "semestral", "anual", "vacaciones")))
        alertas.append((f"Recaudo bajo (menos de ${_peso(umbral):,.0f}): el 60 % no alcanza a 1 SMLMV, así que todo va "
                        f"como compensación, sin auxilio sindical, y se descuenta un ajuste sindical de "
                        f"${ajuste:,.0f} para completar la seguridad social.").replace(",", "."))
    ordinaria = min(minimo, compensaciones)
    extraordinaria = compensaciones - ordinaria
    auxilio = distribuir - compensaciones

    deducciones = {
        "salud": _peso(ibc * p["salud"]),
        "pension": _peso(ibc * p["pension"]),
        "cuatro_por_mil": _peso(distribuir * p["cuatro_por_mil"]),
        "cuota_sostenimiento": _peso(minimo * p["cuota_sostenimiento"]),
        "ajuste_sindical": ajuste,
        "suscripcion_app": _peso(Decimal(suscripcion_app() if suscripcion is None else suscripcion)),
    }
    neto = distribuir - sum(deducciones.values())

    return {
        "recaudo": _peso(recaudo),
        "smlmv": minimo,
        "apropiaciones": {k: _peso(v) for k, v in apropiaciones.items()},
        "base_contrato": _peso(base),
        "seguridad_social": _peso(seguridad_social),
        "distribuir": distribuir,
        "devengados": {"probienestar": _peso(apropiaciones["probienestar"]), "compensacion_ordinaria": ordinaria,
                       "compensacion_extraordinaria": extraordinaria, "auxilio_sindical": auxilio},
        "deducciones": deducciones,
        "neto": neto,
        "alertas": alertas,
    }


# ------------------------------------------------------------ comparación con el volante de AP
CONCEPTOS = [  # (clave, nombre en pantalla, dónde está en la liquidación)
    ("probienestar", "Fondo probienestar", ("devengados", "probienestar")),
    ("compensacion_ordinaria", "Compensación ordinaria", ("devengados", "compensacion_ordinaria")),
    ("compensacion_extraordinaria", "Compensación extraordinaria", ("devengados", "compensacion_extraordinaria")),
    ("auxilio_sindical", "Auxilio sindical", ("devengados", "auxilio_sindical")),
    ("cuatro_por_mil", "4 x mil", ("deducciones", "cuatro_por_mil")),
    ("cuota_sostenimiento", "Cuota de sostenimiento", ("deducciones", "cuota_sostenimiento")),
    ("salud", "Salud", ("deducciones", "salud")),
    ("pension", "Pensión", ("deducciones", "pension")),
    ("ajuste_sindical", "Ajuste sindical", ("deducciones", "ajuste_sindical")),
    ("suscripcion_app", "Descuento suscripción app", ("deducciones", "suscripcion_app")),
    ("neto", "Neto a pagar (sin probienestar)", ("neto",)),
]
TOLERANCIA = Decimal("5")  # diferencias de redondeo


def comparar(calculada: dict, volante: dict) -> list[dict]:
    """Compara la liquidación calculada con los valores leídos del volante, concepto por concepto.
    Los conceptos del volante que la fórmula no calcula (ej. retención en la fuente) se muestran aparte
    y se tienen en cuenta en el neto."""
    otros = list(volante.get("otros") or [])
    leido_suscripcion = volante.get("suscripcion_app")
    if leido_suscripcion is None:  # por si la IA lo dejó entre los otros conceptos
        for o in otros:
            if "suscrip" in (o.get("concepto") or "").lower() and o.get("deducido"):
                leido_suscripcion = o["deducido"]
                otros.remove(o)
                break
    volante = {**volante, "suscripcion_app": leido_suscripcion}
    desde_volante = bool(leido_suscripcion) and not calculada["deducciones"]["suscripcion_app"]
    if desde_volante:
        # AP ya descuenta la suscripción pero aquí no está configurada: se toma del volante para que el neto cuadre
        calculada = {**calculada, "deducciones": {**calculada["deducciones"], "suscripcion_app": Decimal(leido_suscripcion)},
                     "neto": calculada["neto"] - Decimal(leido_suscripcion)}
    efecto_otros = sum((Decimal(o.get("devengado") or 0) - Decimal(o.get("deducido") or 0) for o in otros), Decimal(0))
    filas = []
    for clave, nombre, ruta in CONCEPTOS:
        esperado = calculada
        for parte in ruta:
            esperado = esperado[parte]
        if clave == "suscripcion_app" and desde_volante:
            nombre += " (según el volante)"
        if clave == "neto":
            esperado = esperado + efecto_otros
            if efecto_otros:
                nombre += " (con los otros conceptos del volante)"
        leido = volante.get(clave)
        if leido is None:
            estado = "NO_APARECE" if esperado else "COINCIDE"
        else:
            estado = "COINCIDE" if abs(Decimal(leido) - esperado) <= TOLERANCIA else "DIFERENTE"
        filas.append({"concepto": nombre, "calculado": esperado, "volante": leido,
                      "diferencia": None if leido is None else Decimal(leido) - esperado, "estado": estado})
    for o in otros:
        valor = Decimal(o.get("deducido") or 0) or Decimal(o.get("devengado") or 0)
        filas.insert(-1, {"concepto": (o.get("concepto") or "Otro concepto").capitalize() + " (no se calcula)",
                          "calculado": None, "volante": valor, "diferencia": None, "estado": "OTRO"})
    return filas
