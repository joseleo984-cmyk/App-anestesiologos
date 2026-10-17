"""Consumo de la IA: cada llamada guarda sus tokens, el modelo que respondió y un costo estimado, por anestesiólogo.

El endpoint (o la tarea en segundo plano) que va a leer con la IA fija el contexto con `en_nombre_de(...)`; la
llamada lo toma de ahí. Las tareas del sistema (resumir noticias) quedan sin anestesiólogo.
"""
import logging
from contextvars import ContextVar
from decimal import Decimal
from typing import Optional

log = logging.getLogger(__name__)

# Precio en USD por millón de tokens: entrada, salida, lectura de caché, escritura de caché (5 min)
PRECIOS = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-fable-5-1": (10.00, 50.00, 0.25, 12.50),
    "claude-opus-5": (5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-8": (5.00, 25.00, 0.50, 6.25),
    "claude-sonnet-5": (2.00, 10.00, 0.20, 2.50),
}

_contexto: ContextVar[dict] = ContextVar("contexto_ia", default={})


def en_nombre_de(anestesiologo_id: Optional[int], documento_id: Optional[int] = None) -> None:
    """Las llamadas a la IA que siguen en este hilo se cargan a este anestesiólogo (y documento, si lo hay)."""
    _contexto.set({"anestesiologo_id": anestesiologo_id, "documento_id": documento_id})


def costo_estimado(modelo: str, entrada: int, salida: int, cache_lectura: int, cache_escritura: int) -> Optional[Decimal]:
    precio = PRECIOS.get(modelo)
    if precio is None:
        return None
    total = (entrada * precio[0] + salida * precio[1] + cache_lectura * precio[2] + cache_escritura * precio[3]) / 1_000_000
    return Decimal(str(round(total, 6)))


def registrar(tipo: str, respuesta) -> None:
    """Guarda el consumo de una respuesta. Nunca hace fallar la lectura: si algo sale mal, solo queda en el log."""
    try:
        uso = getattr(respuesta, "usage", None)
        if uso is None:
            return
        n = lambda campo: int(getattr(uso, campo, 0) or 0)  # noqa: E731
        entrada, salida = n("input_tokens"), n("output_tokens")
        lectura, escritura = n("cache_read_input_tokens"), n("cache_creation_input_tokens")
        modelo = str(getattr(respuesta, "model", "") or "")
        ctx = _contexto.get()
        from app.repositorio import conectar
        with conectar() as conn:
            conn.execute(
                """INSERT INTO uso_ia (anestesiologo_id, documento_id, tipo, modelo, tokens_entrada, tokens_salida,
                                       tokens_cache_lectura, tokens_cache_escritura, costo_usd)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (ctx.get("anestesiologo_id"), ctx.get("documento_id"), tipo, modelo[:60], entrada, salida,
                 lectura, escritura, costo_estimado(modelo, entrada, salida, lectura, escritura)))
            conn.commit()
    except Exception as e:  # noqa: BLE001 - el registro de consumo nunca debe romper la lectura
        log.warning("No se pudo registrar el consumo de la IA: %r", e)


def resumen(conn, desde=None) -> list[dict]:
    """Consumo por anestesiólogo (y del sistema) desde una fecha: lecturas, tokens y costo estimado."""
    return conn.execute(
        """SELECT u.anestesiologo_id, COALESCE(a.nombre, 'Sistema (noticias)') AS nombre,
                  count(*) AS lecturas, sum(u.tokens_entrada) AS entrada, sum(u.tokens_salida) AS salida,
                  sum(u.tokens_cache_lectura + u.tokens_cache_escritura) AS cache, COALESCE(sum(u.costo_usd), 0) AS costo_usd
             FROM uso_ia u LEFT JOIN anestesiologo a USING (anestesiologo_id)
            WHERE u.creado_en >= COALESCE(%s, date_trunc('month', now()))
            GROUP BY u.anestesiologo_id, a.nombre ORDER BY costo_usd DESC""", (desde,)).fetchall()


def por_tipo(conn, desde=None) -> list[dict]:
    return conn.execute(
        """SELECT tipo, count(*) AS lecturas, COALESCE(sum(costo_usd), 0) AS costo_usd,
                  round(avg(tokens_entrada + tokens_salida)) AS tokens_promedio
             FROM uso_ia WHERE creado_en >= COALESCE(%s, date_trunc('month', now()))
            GROUP BY tipo ORDER BY costo_usd DESC""", (desde,)).fetchall()


def lecturas_ultimas_24h(conn, anestesiologo_id: int) -> int:
    return conn.execute("SELECT count(*) AS n FROM uso_ia WHERE anestesiologo_id = %s AND creado_en > now() - interval '24 hours'",
                        (anestesiologo_id,)).fetchone()["n"]
