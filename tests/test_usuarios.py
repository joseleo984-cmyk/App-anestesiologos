"""Varios anestesiólogos: cuentas, claves temporales, sesiones y aislamiento de datos."""
import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import auth, config, extraccion, inicio, main
from app.modelos import OrdenExtraida
from tests.conftest import EMAIL, PASSWORD
from tests.test_api import CONFIRMAR
from tests.test_extraccion import RESPUESTA, foto


@pytest.fixture
def app_multi(db_url, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(extraccion, "extraer_orden", lambda archivos: OrdenExtraida.model_validate(RESPUESTA))
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute("UPDATE anestesiologo SET es_admin = TRUE WHERE anestesiologo_id = 1")
    return db_url


def entrar(email, clave):
    c = TestClient(main.app)
    r = c.post("/api/login", json={"email": email, "password": clave})
    assert r.status_code == 200, r.text
    return c


def crear_cuenta(admin, email="otro@clinica.co"):
    r = admin.post("/api/usuarios", json={"nombre": "Dr. Otro Anestesiólogo", "email": email})
    assert r.status_code == 201, r.text
    return r.json()


def entrar_y_cambiar(email, temporal, nueva="clave-nueva-123"):
    c = entrar(email, temporal)
    assert c.post("/api/cambiar-clave", json={"actual": temporal, "nueva": nueva}).status_code == 200
    return c


def test_cuenta_nueva_debe_cambiar_la_clave(app_multi):
    admin = entrar(EMAIL, PASSWORD)
    nueva = crear_cuenta(admin)
    otro = entrar("Otro@Clinica.co", nueva["clave_temporal"])
    assert otro.get("/api/yo").json()["debe_cambiar_clave"] is True
    r = otro.get("/api/cirugias")
    assert r.status_code == 403 and r.json()["detail"]["cambiar_clave"] is True
    assert otro.post("/api/cambiar-clave", json={"actual": "mala", "nueva": "clave-nueva-123"}).status_code == 400
    assert otro.post("/api/cambiar-clave", json={"actual": nueva["clave_temporal"], "nueva": "corta"}).status_code == 422
    assert otro.post("/api/cambiar-clave",
                     json={"actual": nueva["clave_temporal"], "nueva": "clave-nueva-123"}).status_code == 200
    assert otro.get("/api/cirugias").status_code == 200  # la misma sesión sigue abierta
    assert admin.post("/api/usuarios", json={"nombre": "Repetido", "email": "otro@clinica.co"}).status_code == 409


def test_solo_el_admin_gestiona_cuentas(app_multi):
    admin = entrar(EMAIL, PASSWORD)
    otro = entrar_y_cambiar("otro@clinica.co", crear_cuenta(admin)["clave_temporal"])
    assert otro.get("/api/usuarios").status_code == 403
    assert otro.post("/api/usuarios", json={"nombre": "Intruso", "email": "x@y.co"}).status_code == 403
    assert otro.post("/api/usuarios/1/restablecer").status_code == 403
    assert admin.put("/api/usuarios/1", json={"activo": False}).status_code == 400  # no a sí mismo
    assert {u["email"] for u in admin.get("/api/usuarios").json()} == {EMAIL, "otro@clinica.co"}


def test_aislamiento_entre_anestesiologos(app_multi, monkeypatch):
    admin = entrar(EMAIL, PASSWORD)
    otro = entrar_y_cambiar("otro@clinica.co", crear_cuenta(admin)["clave_temporal"])
    archivo = {"archivo": ("orden.jpg", foto(), "image/jpeg")}

    doc = admin.post("/api/documentos", files=archivo).json()
    cid = admin.post(f"/api/documentos/{doc['documento_id']}/confirmar", json={**CONFIRMAR, "cirujano": "Ana Ruiz"}).json()["cirugia_id"]

    # El otro anestesiólogo puede subir su propia copia del MISMO archivo
    assert otro.post("/api/documentos", files=archivo).status_code == 201
    # ...pero no ve ni toca nada del primero
    assert otro.get("/api/cirugias").json() == []
    assert otro.get(f"/api/cirugias/{cid}").status_code == 404
    assert otro.put(f"/api/cirugias/{cid}", json=CONFIRMAR).status_code == 404
    assert otro.get(f"/api/documentos/{doc['documento_id']}").status_code == 404
    assert otro.get(f"/api/documentos/{doc['documento_id']}/archivo").status_code == 404
    assert otro.post(f"/api/documentos/{doc['documento_id']}/confirmar", json=CONFIRMAR).status_code == 404
    assert otro.get("/api/opciones").json()["cirujanos"] == []
    assert otro.get("/api/reportes").json()["totales"]["cirugias"] == 0
    assert otro.get("/api/cirugias.xlsx").status_code == 200
    # Los datos del primero siguen intactos
    assert admin.get(f"/api/cirugias/{cid}").json()["cirujano"] == "ANA RUIZ"


def test_el_mismo_paciente_es_independiente_para_cada_anestesiologo(app_multi):
    """Dos anestesiólogos con el mismo paciente (mismo documento): cada uno ve y corrige su propia ficha."""
    admin = entrar(EMAIL, PASSWORD)
    otro = entrar_y_cambiar("otro@clinica.co", crear_cuenta(admin)["clave_temporal"])
    paciente = {"tipo_documento": "CC", "numero_documento": "900111222", "nombres": "Ana", "apellidos": "Ficticia"}
    poliza = {"nombre": "Sura", "tipo": "PREPAGADA", "numero_poliza": "P-1", "plan": "Oro"}
    mia = admin.post("/api/cirugias", json={**CONFIRMAR, "paciente": paciente, "aseguradora": poliza}).json()["cirugia_id"]
    suya = otro.post("/api/cirugias", json={**CONFIRMAR, "paciente": {**paciente, "nombres": "Anita", "apellidos": "Otra"},
                                            "aseguradora": {**poliza, "plan": "Plata"}}).json()["cirugia_id"]
    a, b = admin.get(f"/api/cirugias/{mia}").json(), otro.get(f"/api/cirugias/{suya}").json()
    assert (a["paciente"]["nombres"], a["aseguradora"]["plan"]) == ("Ana", "Oro")
    assert (b["paciente"]["nombres"], b["aseguradora"]["plan"]) == ("Anita", "Plata")
    # corregir el nombre en una cuenta no cambia la otra
    assert otro.put(f"/api/cirugias/{suya}", json={**CONFIRMAR, "paciente": {**paciente, "nombres": "Ana María"}}).status_code == 200
    assert admin.get(f"/api/cirugias/{mia}").json()["paciente"]["nombres"] == "Ana"
    assert otro.get(f"/api/cirugias/{suya}").json()["paciente"]["nombres"] == "Ana María"
    # y cada uno tiene su propia fila de paciente y de cobertura
    with psycopg.connect(app_multi) as c:
        assert c.execute("SELECT count(*) FROM paciente WHERE numero_documento = '900111222'").fetchone()[0] == 2
        assert c.execute("""SELECT count(DISTINCT cb.cobertura_id) FROM cirugia ci JOIN cobertura cb USING (cobertura_id)
                             WHERE ci.cirugia_id IN (%s, %s)""", (mia, suya)).fetchone()[0] == 2


def test_desactivar_y_restablecer_cierran_sesiones(app_multi):
    admin = entrar(EMAIL, PASSWORD)
    nueva = crear_cuenta(admin)
    otro = entrar_y_cambiar("otro@clinica.co", nueva["clave_temporal"])
    uid = nueva["anestesiologo_id"]

    assert admin.put(f"/api/usuarios/{uid}", json={"activo": False}).status_code == 200
    assert otro.get("/api/cirugias").status_code == 401
    assert TestClient(main.app).post("/api/login", json={"email": "otro@clinica.co", "password": "clave-nueva-123"}).status_code == 401
    assert admin.put(f"/api/usuarios/{uid}", json={"activo": True}).status_code == 200

    otro = entrar("otro@clinica.co", "clave-nueva-123")
    temporal = admin.post(f"/api/usuarios/{uid}/restablecer").json()["clave_temporal"]
    assert otro.get("/api/yo").status_code == 401                       # su sesión se cerró
    nuevo = entrar("otro@clinica.co", temporal)
    assert nuevo.get("/api/yo").json()["debe_cambiar_clave"] is True


def test_cambiar_clave_cierra_las_otras_sesiones(app_multi):
    celular, computador = entrar(EMAIL, PASSWORD), entrar(EMAIL, PASSWORD)
    assert celular.post("/api/cambiar-clave", json={"actual": PASSWORD, "nueva": "otra-clave-larga"}).status_code == 200
    assert celular.get("/api/cirugias").status_code == 200
    assert computador.get("/api/cirugias").status_code == 401


def test_clave_de_render_no_pisa_la_cambiada_en_la_app(db_url, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "ADMIN_EMAIL", "jefe@clinica.co")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "clave-de-render-1")
    inicio.preparar_base_de_datos()
    jefe = entrar("jefe@clinica.co", "clave-de-render-1")
    assert jefe.get("/api/yo").json()["es_admin"] is True
    jefe.post("/api/cambiar-clave", json={"actual": "clave-de-render-1", "nueva": "clave-desde-la-app"})

    inicio.preparar_base_de_datos()                      # reinicio con la misma variable
    entrar("jefe@clinica.co", "clave-desde-la-app")      # se conserva la de la app

    monkeypatch.setattr(config, "ADMIN_PASSWORD", "clave-de-render-2")
    inicio.preparar_base_de_datos()                      # la variable cambió en Render: se aplica
    entrar("jefe@clinica.co", "clave-de-render-2")
