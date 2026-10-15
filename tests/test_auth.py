import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import auth, config, inicio, main
from tests.conftest import EMAIL, PASSWORD


@pytest.fixture
def anonimo(db_url, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    return TestClient(main.app)


def test_sin_sesion_no_hay_datos(anonimo):
    assert anonimo.get("/api/cirugias").status_code == 401
    assert anonimo.post("/api/documentos", files={"archivo": ("a.pdf", b"%PDF", "application/pdf")}).status_code == 401
    r = anonimo.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert anonimo.get("/login").status_code == 200


def test_login_y_logout(anonimo):
    r = anonimo.post("/api/login", json={"email": " Prueba@Ejemplo.com ", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["nombre"] == "Dra. Prueba"
    assert "httponly" in r.headers["set-cookie"].lower()
    assert anonimo.get("/api/yo").json()["email"] == EMAIL
    assert anonimo.get("/api/cirugias").status_code == 200
    assert anonimo.get("/").headers["cache-control"] == "no-store"
    anonimo.post("/api/logout")
    assert anonimo.get("/api/cirugias").status_code == 401


def test_contrasena_incorrecta(anonimo):
    assert anonimo.post("/api/login", json={"email": EMAIL, "password": "otra"}).status_code == 401
    assert anonimo.post("/api/login", json={"email": "nadie@x.co", "password": PASSWORD}).status_code == 401


def test_cookie_alterada_o_vencida(anonimo, monkeypatch):
    sesion = auth.crear_sesion(1)
    anonimo.cookies.set(auth.COOKIE, sesion.replace("1.", "2.", 1))
    assert anonimo.get("/api/cirugias").status_code == 401
    anonimo.cookies.set(auth.COOKIE, sesion)
    assert anonimo.get("/api/cirugias").status_code == 200
    reloj = time.time() + auth.DURACION_SESION + 1
    monkeypatch.setattr(auth.time, "time", lambda: reloj)
    assert anonimo.get("/api/cirugias").status_code == 401


def test_base_vacia_se_prepara_al_arrancar(db_url, monkeypatch):
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    monkeypatch.setattr(config, "ADMIN_EMAIL", "Admin@Clinica.co")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "una-clave-larga")
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with TestClient(main.app) as cliente:  # ejecuta el arranque
        assert cliente.get("/salud").json() == {"estado": "ok"}
        assert cliente.post("/api/login", json={"email": "admin@clinica.co", "password": "una-clave-larga"}).status_code == 200
    with psycopg.connect(db_url) as c:
        sin_rls = c.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND NOT rowsecurity").fetchone()[0]
        assert sin_rls == 0
    # Reiniciar no duplica el usuario y aplica la nueva contraseña
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "otra-clave-larga")
    inicio.preparar_base_de_datos()
    with psycopg.connect(db_url) as c:
        assert c.execute("SELECT count(*) FROM anestesiologo").fetchone()[0] == 1


def test_contrasena_corta_no_arranca(db_url, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_EMAIL", "a@b.co")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "corta")
    with pytest.raises(RuntimeError):
        inicio.preparar_base_de_datos()


def test_las_migraciones_solo_corren_cuando_cambian(db_url, monkeypatch):
    from app import inicio
    from app.repositorio import conectar
    inicio.preparar_base_de_datos()
    with conectar() as c:
        assert c.execute("SELECT count(*) AS n FROM migracion_aplicada").fetchone()["n"] == 1
        # simula una conexión de otra instancia con una transacción abierta sobre anestesiologo
        otra = conectar()
        otra.execute("SELECT 1 FROM anestesiologo LIMIT 1")
        try:
            inicio.preparar_base_de_datos()  # no necesita bloquear tablas: no espera a la otra conexión
        finally:
            otra.close()
        assert c.execute("SELECT count(*) AS n FROM migracion_aplicada").fetchone()["n"] == 1


# ------------------------------------------------ registro propio con aprobación del administrador
NUEVO = {"nombre": "Dr. Nuevo Ficticio", "email": "Nuevo@Ejemplo.com", "registro_medico": "RM-12345",
         "telefono": "3000000000", "password": "clave-nueva-123", "autoriza_datos": True}


def admin_cliente():
    from app.repositorio import conectar
    with conectar() as c:
        c.execute("UPDATE anestesiologo SET es_admin = TRUE WHERE email = %s", (EMAIL,))
        c.commit()
    adm = TestClient(main.app)
    assert adm.post("/api/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200
    return adm


def test_registro_pendiente_y_aprobacion(anonimo, monkeypatch):
    main._registros_por_ip.clear()
    assert anonimo.get("/api/registro").json() == {"abierto": True}
    assert anonimo.post("/api/registro", json={**NUEVO, "autoriza_datos": False}).status_code == 422
    assert anonimo.post("/api/registro", json={**NUEVO, "password": "corta"}).status_code == 422
    assert anonimo.post("/api/registro", json=NUEVO).status_code == 201
    assert anonimo.post("/api/registro", json={**NUEVO, "registro_medico": "otro"}).status_code == 409  # correo repetido
    # pendiente: no entra, con un mensaje claro (solo si la clave es correcta)
    r = anonimo.post("/api/login", json={"email": "nuevo@ejemplo.com", "password": NUEVO["password"]})
    assert r.status_code == 403 and "pendiente" in r.json()["detail"]
    assert anonimo.post("/api/login", json={"email": "nuevo@ejemplo.com", "password": "mala-clave-1"}).status_code == 401

    adm = admin_cliente()
    assert adm.get("/api/inicio").json()["solicitudes"] == 1
    pendiente = next(u for u in adm.get("/api/usuarios").json() if u["estado_registro"] == "PENDIENTE")
    assert pendiente["telefono"] == "3000000000" and pendiente["registro_medico"] == "RM-12345"
    # activar no sirve para una solicitud: hay que aprobarla
    assert adm.put(f"/api/usuarios/{pendiente['anestesiologo_id']}", json={"activo": True}).status_code == 404
    assert adm.post(f"/api/usuarios/{pendiente['anestesiologo_id']}/aprobar").status_code == 200
    assert adm.get("/api/inicio").json()["solicitudes"] == 0
    nuevo = TestClient(main.app)
    r = nuevo.post("/api/login", json={"email": "nuevo@ejemplo.com", "password": NUEVO["password"]})
    assert r.status_code == 200 and r.json()["debe_cambiar_clave"] is False
    assert nuevo.get("/api/cirugias").json() == []      # empieza sin datos: no ve los de otros


def test_rechazo_robots_y_limites(anonimo, monkeypatch):
    main._registros_por_ip.clear()
    assert anonimo.post("/api/registro", json={**NUEVO, "sitio_web": "http://spam"}).status_code == 201
    adm = admin_cliente()
    assert all(u["estado_registro"] != "PENDIENTE" for u in adm.get("/api/usuarios").json())  # el robot no creó nada
    assert anonimo.post("/api/registro", json=NUEVO).status_code == 201
    pid = next(u["anestesiologo_id"] for u in adm.get("/api/usuarios").json() if u["estado_registro"] == "PENDIENTE")
    assert adm.post(f"/api/usuarios/{pid}/rechazar").status_code == 200
    assert anonimo.post("/api/login", json={"email": NUEVO["email"], "password": NUEVO["password"]}).status_code == 401
    # límite por conexión (3 por hora): el robot, la rechazada y esta ya suman 3
    assert anonimo.post("/api/registro", json={**NUEVO, "email": "w@y.co", "registro_medico": "RM-1"}).status_code == 201
    assert anonimo.post("/api/registro", json={**NUEVO, "email": "x@y.co", "registro_medico": "RM-2"}).status_code == 429
    # registro cerrado
    main._registros_por_ip.clear()
    monkeypatch.setattr(config, "REGISTRO_ABIERTO", False)
    assert anonimo.post("/api/registro", json={**NUEVO, "email": "z@y.co", "registro_medico": "RM-3"}).status_code == 403


def test_bloqueo_tras_intentos_fallidos(anonimo, monkeypatch):
    main._fallos_por_ip.clear()
    for _ in range(4):
        assert anonimo.post("/api/login", json={"email": EMAIL, "password": "mala-clave"}).status_code == 401
    r = anonimo.post("/api/login", json={"email": EMAIL, "password": "mala-clave"})       # el 5.º bloquea
    assert r.status_code == 429 and "15 minutos" in r.json()["detail"]
    # bloqueada: ni con la clave correcta entra
    r = anonimo.post("/api/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 429 and "Olvidé mi contraseña" in r.json()["detail"]
    # al vencer el bloqueo entra y el contador vuelve a cero
    from app.repositorio import conectar
    with conectar() as c:
        c.execute("UPDATE anestesiologo SET bloqueado_hasta = now() - interval '1 minute' WHERE email = %s", (EMAIL,))
        c.commit()
    assert anonimo.post("/api/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200
    with conectar() as c:
        assert c.execute("SELECT intentos_fallidos FROM anestesiologo WHERE email = %s", (EMAIL,)).fetchone()["intentos_fallidos"] == 0
        # la segunda tanda de 5 fallos bloquea el doble
        c.execute("UPDATE anestesiologo SET intentos_fallidos = 9 WHERE email = %s", (EMAIL,))
        c.commit()
    r = anonimo.post("/api/login", json={"email": EMAIL, "password": "mala-clave"})
    assert r.status_code == 429 and "30 minutos" in r.json()["detail"]


def test_limite_de_fallos_por_conexion(anonimo):
    main._fallos_por_ip.clear()
    for i in range(main.MAX_FALLOS_IP):
        assert anonimo.post("/api/login", json={"email": f"nadie{i}@x.co", "password": "x"}).status_code == 401
    assert anonimo.post("/api/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 429
    main._fallos_por_ip.clear()
