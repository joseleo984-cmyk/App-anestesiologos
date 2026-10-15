"""Consumo de la IA por lectura y por anestesiólogo."""
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import extraccion, uso_ia
from tests.test_api import cliente  # noqa: F401  (fixture)
from tests.test_extraccion import RESPUESTA, ClienteFalso


def cliente_con_uso(modelo="claude-opus-5-5"):
    c = ClienteFalso(texto=json.dumps(RESPUESTA))
    c._respuesta.model = modelo
    c._respuesta.usage = SimpleNamespace(input_tokens=10_000, output_tokens=2_000, cache_read_input_tokens=0,
                                         cache_creation_input_tokens=0)
    return c


def test_costo_estimado():
    # Opus 5.5: $4 por millón de entrada y $20 por millón de salida
    assert uso_ia.costo_estimado("claude-opus-5-5", 1_000_000, 0, 0, 0) == Decimal("4.0")
    assert uso_ia.costo_estimado("claude-opus-5-5", 10_000, 2_000, 0, 0) == Decimal("0.08")
    assert uso_ia.costo_estimado("modelo-desconocido", 1, 1, 0, 0) is None


def test_cada_lectura_queda_registrada_por_anestesiologo(cliente, conn):
    uso_ia.en_nombre_de(1, None)
    leer = lambda c: extraccion._llamar_claude([(b"%PDF-1.7", "application/pdf")], "x", {"type": "object"}, "y",  # noqa: E731
                                               "high", c, tipo="orden")
    leer(cliente_con_uso())
    # una lectura que luego falla (rechazada) también consumió tokens
    rechazada = cliente_con_uso("claude-sonnet-5-5")
    rechazada._respuesta.stop_reason = "refusal"
    with pytest.raises(extraccion.ExtraccionError):
        leer(rechazada)
    uso_ia.en_nombre_de(None)  # tareas del sistema (noticias)
    extraccion._llamar_claude([], "x", {"type": "object"}, "y", "low", cliente_con_uso(), tipo="noticias")
    filas = conn.execute("SELECT anestesiologo_id, tipo, modelo, tokens_entrada, costo_usd FROM uso_ia ORDER BY uso_id").fetchall()
    assert [(f["anestesiologo_id"], f["tipo"], f["modelo"]) for f in filas] == [
        (1, "orden", "claude-opus-5-5"), (1, "orden", "claude-sonnet-5-5"), (None, "noticias", "claude-opus-5-5")]
    assert filas[0]["costo_usd"] == Decimal("0.08") and filas[1]["costo_usd"] == Decimal("0.04")

    # solo el administrador ve el resumen
    assert cliente.get("/api/uso-ia").status_code == 403
    conn.execute("UPDATE anestesiologo SET es_admin = TRUE WHERE anestesiologo_id = 1")
    conn.commit()
    r = cliente.get("/api/uso-ia").json()
    por = {f["nombre"]: f for f in r["por_anestesiologo"]}
    assert por["Sistema (noticias)"]["lecturas"] == 1
    yo = next(f for f in r["por_anestesiologo"] if f["anestesiologo_id"] == 1)
    assert yo["lecturas"] == 2 and float(yo["costo_usd"]) == pytest.approx(0.12)
    assert {t["tipo"] for t in r["por_tipo"]} == {"orden", "noticias"}


def test_un_fallo_al_registrar_no_rompe_la_lectura(monkeypatch):
    def conectar_roto():
        raise RuntimeError("base caída")
    monkeypatch.setattr("app.repositorio.conectar", conectar_roto)
    datos = extraccion._llamar_claude([], "x", {"type": "object"}, "y", "low", cliente_con_uso(), tipo="orden")
    assert datos["paciente"]["nombres"] == RESPUESTA["paciente"]["nombres"]
