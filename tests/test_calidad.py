"""«¿Qué te faltó?» y registro de los campos que el anestesiólogo corrige tras la lectura."""
import copy

from fastapi.testclient import TestClient

from app import auth, calidad, main, repositorio
from app.modelos import OrdenConfirmada
from tests.test_api import CONFIRMAR, cliente, subir  # noqa: F401  (fixture)
from tests.test_extraccion import RESPUESTA


def test_campos_corregidos_ignora_tildes_y_mayusculas():
    igual = copy.deepcopy(CONFIRMAR)
    igual["clinica"]["nombre"] = "CLINICA LAS AMERICAS."
    assert calidad.campos_corregidos(RESPUESTA, OrdenConfirmada.model_validate(igual)) == []

    cambiada = copy.deepcopy(CONFIRMAR)
    cambiada["paciente"]["nombres"] = "Mariana"
    cambiada["cirujano"] = "Dr. Cirujano Ficticio"
    cambiada["aseguradora"] = None
    cambiada["procedimientos"].append({"codigo": "862100", "nombre": "Otro", "es_principal": False})
    cambios = dict(calidad.campos_corregidos(RESPUESTA, OrdenConfirmada.model_validate(cambiada)))
    assert cambios == {"paciente.nombres": "CORREGIDO", "cirujano": "AGREGADO", "aseguradora.nombre": "BORRADO",
                       "aseguradora.tipo": "BORRADO", "procedimientos.codigos": "CORREGIDO",
                       "procedimientos.cantidad": "CORREGIDO"}


def test_confirmar_registra_los_campos_corregidos_sin_los_valores(cliente, conn):
    doc = subir(cliente).json()
    datos = copy.deepcopy(CONFIRMAR)
    datos["paciente"]["nombres"] = "Mariana"
    datos["cirujano"] = "Dr. Cirujano Ficticio"
    assert cliente.post(f"/api/documentos/{doc['documento_id']}/confirmar", json=datos).status_code == 201
    filas = conn.execute("SELECT * FROM correccion_lectura ORDER BY campo").fetchall()
    assert [(f["campo"], f["cambio"], f["documento_id"], f["anestesiologo_id"]) for f in filas] == [
        ("cirujano", "AGREGADO", doc["documento_id"], 1), ("paciente.nombres", "CORREGIDO", doc["documento_id"], 1)]
    # no se guarda ningún dato del paciente
    assert "Mariana" not in str([dict(f) for f in filas])

    # el administrador ve el porcentaje sobre las órdenes leídas
    assert cliente.get("/api/calidad-lectura").status_code == 403
    conn.execute("UPDATE anestesiologo SET es_admin = TRUE WHERE anestesiologo_id = 1")
    conn.commit()
    r = cliente.get("/api/calidad-lectura").json()
    assert r["ordenes_leidas"] == 1
    assert {c["campo"]: c["porcentaje"] for c in r["campos"]} == {"cirujano": 100, "paciente.nombres": 100}
    assert r["campos"][0]["nombre"] in ("Cirujano", "Nombres")


def test_que_te_falto(cliente, conn):
    doc = subir(cliente).json()
    r = cliente.post("/api/comentarios-lectura", json={"texto": "No leyó el segundo procedimiento",
                                                       "documento_id": doc["documento_id"]})
    assert r.status_code == 201, r.text
    assert cliente.post("/api/comentarios-lectura", json={"texto": "x"}).status_code == 422

    # el comentario de otro anestesiólogo sobre un documento ajeno se guarda sin el documento
    otro_id = repositorio.crear_usuario(conn, "Dr. Otro", "otro@clinica.co", None, auth.hash_password("clave-de-prueba-9"))
    conn.execute("UPDATE anestesiologo SET debe_cambiar_clave = FALSE WHERE anestesiologo_id = %s", (otro_id,))
    conn.commit()
    otro = TestClient(main.app)
    otro.cookies.set(auth.COOKIE, auth.crear_sesion(otro_id))
    assert otro.post("/api/comentarios-lectura", json={"texto": "Confundió la aseguradora",
                                                       "documento_id": doc["documento_id"]}).status_code == 201
    filas = conn.execute("SELECT anestesiologo_id, documento_id FROM comentario_lectura ORDER BY comentario_id").fetchall()
    assert [(f["anestesiologo_id"], f["documento_id"]) for f in filas] == [(1, doc["documento_id"]), (otro_id, None)]

    conn.execute("UPDATE anestesiologo SET es_admin = TRUE WHERE anestesiologo_id = 1")
    conn.commit()
    comentarios = cliente.get("/api/calidad-lectura").json()["comentarios"]
    assert [k["texto"] for k in comentarios] == ["Confundió la aseguradora", "No leyó el segundo procedimiento"]
