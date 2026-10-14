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
