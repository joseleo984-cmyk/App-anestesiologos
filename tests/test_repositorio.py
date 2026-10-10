from app import repositorio
from tests.datos import orden


def contar(conn, tabla):
    return conn.execute(f"SELECT count(*) AS n FROM {tabla}").fetchone()["n"]


def test_guarda_orden_completa(conn):
    cirugia_id = repositorio.guardar_orden(conn, 1, orden())
    fila = repositorio.listar_cirugias(conn, 1)[0]
    assert fila["cirugia_id"] == cirugia_id
    assert fila["numero_documento"] == "1020304050"  # sin puntos
    assert fila["aseguradora"] == "SURA"
    assert fila["clinica"] == "CLÍNICA LAS AMÉRICAS"
    assert fila["procedimientos"] == [{"codigo": "471100", "nombre": "Apendicectomía", "es_principal": True}]


def test_no_duplica_paciente_aseguradora_ni_clinica(conn):
    repositorio.guardar_orden(conn, 1, orden())
    # Segunda orden del mismo paciente, con mayúsculas/espacios distintos y un dato corregido
    repositorio.guardar_orden(conn, 1, orden(
        paciente={"tipo_documento": "CC", "numero_documento": "1020304050",
                  "nombres": "María  Fernanda", "apellidos": "Gómez Ruíz"},
        aseguradora={"nombre": "SURA", "tipo": "EPS"},
        clinica={"nombre": "clínica las américas", "ciudad": "MEDELLÍN"},
        fecha_procedimiento="2026-11-02"))
    assert contar(conn, "cirugia") == 2
    assert contar(conn, "paciente") == 1
    assert contar(conn, "aseguradora") == 1
    assert contar(conn, "cobertura") == 1  # póliza vacía en ambas: misma cobertura
    assert contar(conn, "clinica") == 1
    assert conn.execute("SELECT apellidos FROM paciente").fetchone()["apellidos"] == "Gómez Ruíz"


def test_eps_y_prepagada_son_coberturas_distintas(conn):
    repositorio.guardar_orden(conn, 1, orden())
    repositorio.guardar_orden(conn, 1, orden(aseguradora={"nombre": "Sura", "tipo": "PREPAGADA", "numero_poliza": "PP-1"}))
    assert contar(conn, "aseguradora") == 2
    assert contar(conn, "cobertura") == 2


def test_particular_sin_aseguradora(conn):
    repositorio.guardar_orden(conn, 1, orden(aseguradora=None))
    assert repositorio.listar_cirugias(conn, 1)[0]["aseguradora"] == "PARTICULAR"


def test_catalogo_conserva_nombre_existente(conn):
    conn.execute("INSERT INTO procedimiento VALUES ('471100', 'APENDICECTOMÍA SOD')")
    repositorio.guardar_orden(conn, 1, orden())
    assert conn.execute("SELECT nombre FROM procedimiento").fetchone()["nombre"] == "APENDICECTOMÍA SOD"


def test_solo_lista_cirugias_del_anestesiologo(conn):
    conn.execute("INSERT INTO anestesiologo (nombre, email) VALUES ('Otro', 'otro@x.co')")
    repositorio.guardar_orden(conn, 1, orden())
    assert repositorio.listar_cirugias(conn, 2) == []
