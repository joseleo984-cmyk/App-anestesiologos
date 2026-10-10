import pytest
from pydantic import ValidationError

from app.modelos import OrdenExtraida
from tests.datos import orden


def test_primer_procedimiento_es_principal_por_defecto():
    o = orden(procedimientos=[{"codigo": "471100", "nombre": "Apendicectomía"},
                                    {"codigo": "512101", "nombre": "Colecistectomía"}])
    assert [p.es_principal for p in o.procedimientos] == [True, False]


def test_rechaza_dos_principales_y_codigos_repetidos():
    with pytest.raises(ValidationError, match="solo un procedimiento"):
        orden(procedimientos=[{"codigo": "471100", "nombre": "Apendicectomía", "es_principal": True},
                              {"codigo": "512101", "nombre": "Colecistectomía", "es_principal": True}])
    with pytest.raises(ValidationError, match="repetidos"):
        orden(procedimientos=[{"codigo": "471100", "nombre": "Apendicectomía"},
                              {"codigo": "47 11 00", "nombre": "Apendicectomía"}])


def test_exige_datos_minimos():
    with pytest.raises(ValidationError):
        orden(paciente={"numero_documento": "", "nombres": "A", "apellidos": "B"})
    with pytest.raises(ValidationError):
        orden(procedimientos=[])


def test_extraccion_tolera_datos_ilegibles():
    o = OrdenExtraida.model_validate({"fecha_procedimiento": "2026-02-31", "confianza": 3,
                                      "paciente": {"nombres": "  ", "numero_documento": None}})
    assert o.fecha_procedimiento is None
    assert o.confianza == 1
    assert o.paciente.nombres is None


def test_codigo_con_caracteres_raros():
    with pytest.raises(ValidationError, match="letras y números"):
        orden(procedimientos=[{"codigo": "54?1", "nombre": "Lavado peritoneal"}])
