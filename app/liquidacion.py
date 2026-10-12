"""Liquidación del volante de pago de AP (Anestesiólogos Permanentes) a partir del recaudo del mes.

Fórmula de la "Propuesta para plataforma de liquidación de compensaciones y auxilios", verificada al
peso contra el volante de octubre de 2026:

    recaudo (neto del reporte de pagos)
    - fondo probienestar 20 %, administración 5 %, compensación semestral 2,85 %,
      compensación anual 2,85 %, vacaciones 1 %                    -> base del contrato sindical
    - seguridad social 12,1 % de la base                           -> valor a distribuir en el volante
    reparto: 60 % compensaciones (ordinaria = 1 SMLMV, el resto extraordinaria) y 40 % auxilio sindical.
    Si el 60 % no alcanza a 1 SMLMV, la compensación ordinaria se completa al SMLMV y el auxilio baja.
    deducciones: salud 4 % y pensión 4 % de las compensaciones, 4 x mil del valor distribuido y cuota de
    sostenimiento del 5 % del SMLMV.
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


def liquidar(recaudo: Decimal, anio: Optional[int] = None) -> dict:
    """Volante calculado: líneas de apropiación, devengados, deducciones, neto y alertas."""
    p, minimo = PORCENTAJES, smlmv(anio)
    recaudo = Decimal(recaudo)
    apropiaciones = {k: recaudo * p[k] for k in ("probienestar", "administracion", "semestral", "anual", "vacaciones")}
    base = recaudo - sum(apropiaciones.values())
    seguridad_social = base * p["seguridad_social"]
    distribuir = _peso(base - seguridad_social)

    compensaciones = _peso(distribuir * p["compensaciones"])
    if compensaciones < minimo:  # recaudo bajo: la compensación ordinaria se completa al SMLMV
        compensaciones = min(minimo, distribuir)
    ordinaria = min(minimo, compensaciones)
    extraordinaria = compensaciones - ordinaria
    auxilio = distribuir - compensaciones

    deducciones = {
        "salud": _peso(compensaciones * p["salud"]),
        "pension": _peso(compensaciones * p["pension"]),
        "cuatro_por_mil": _peso(distribuir * p["cuatro_por_mil"]),
        "cuota_sostenimiento": _peso(minimo * p["cuota_sostenimiento"]),
    }
    neto = distribuir - sum(deducciones.values())

    ss_necesaria = compensaciones * p["ss_asociacion"]
    alertas = []
    if distribuir * p["compensaciones"] < minimo:
        umbral = minimo / p["compensaciones"] / (1 - p["seguridad_social"]) / (
            1 - sum(p[k] for k in ("probienestar", "administracion", "semestral", "anual", "vacaciones")))
        alertas.append(f"Recaudo bajo: el 60 % no alcanza a 1 SMLMV (se necesita un recaudo de al menos "
                       f"${_peso(umbral):,.0f}). La compensación ordinaria se completó al mínimo y el auxilio "
                       f"quedó en ".replace(",", ".") + f"{_pct(auxilio / distribuir)} en lugar del 40 %.")
    if seguridad_social + 1 < ss_necesaria:
        alertas.append((f"La seguridad social apropiada (${_peso(seguridad_social):,.0f}) no alcanza para el "
                        f"PCT de las compensaciones (${_peso(ss_necesaria):,.0f}): faltan "
                        f"${_peso(ss_necesaria - seguridad_social):,.0f}.").replace(",", ".")
                       .replace("PCT", _pct(p["ss_asociacion"], 3)))

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
    ("neto", "Neto a pagar (sin probienestar)", ("neto",)),
]
TOLERANCIA = Decimal("2")  # diferencias de redondeo


def comparar(calculada: dict, volante: dict) -> list[dict]:
    """Compara la liquidación calculada con los valores leídos del volante, concepto por concepto."""
    filas = []
    for clave, nombre, ruta in CONCEPTOS:
        esperado = calculada
        for parte in ruta:
            esperado = esperado[parte]
        leido = volante.get(clave)
        if leido is None:
            estado = "NO_APARECE" if esperado else "COINCIDE"
        else:
            estado = "COINCIDE" if abs(Decimal(leido) - esperado) <= TOLERANCIA else "DIFERENTE"
        filas.append({"concepto": nombre, "calculado": esperado, "volante": leido,
                      "diferencia": None if leido is None else Decimal(leido) - esperado, "estado": estado})
    return filas
