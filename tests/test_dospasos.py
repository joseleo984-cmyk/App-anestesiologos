"""Verificación en dos pasos (TOTP) y códigos de recuperación."""
import time

import pytest
from fastapi.testclient import TestClient

from app import config, dospasos, main
from tests.conftest import EMAIL, PASSWORD
from tests.test_usuarios import app_multi, crear_cuenta, entrar, entrar_y_cambiar  # noqa: F401  (fixture)


def codigo_actual(secreto, desfase=0):
    return dospasos._codigo(secreto, int(time.time() // dospasos.PASO) + desfase)


def test_vector_oficial_rfc_6238():
    # RFC 6238, apéndice B: secreto "12345678901234567890", t = 59 s → 94287082 (8 dígitos); aquí son los últimos 6
    secreto = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert dospasos._codigo(secreto, 59 // 30) == "287082"
    assert dospasos._codigo(secreto, 1111111109 // 30) == "081804"
    assert dospasos.verificar(secreto, "287082", ahora=59) == 1
    assert dospasos.verificar(secreto, "287 082", ahora=60) == 1            # acepta espacios y el paso anterior
    assert dospasos.verificar(secreto, "287082", ahora=59 + 90) is None     # fuera de la ventana
    assert dospasos.verificar(secreto, "287082", ultimo_paso=1, ahora=59) is None   # ya usado
    assert dospasos.verificar(secreto, "28708", ahora=59) is None and dospasos.verificar(secreto, "abcdef", ahora=59) is None


def test_codigos_de_recuperacion():
    codigos = dospasos.codigos_de_recuperacion()
    assert len(set(codigos)) == dospasos.CANTIDAD_RECUPERACION
    assert dospasos.hash_recuperacion("ABCD-efgh") == dospasos.hash_recuperacion("abcdefgh") != "abcdefgh"
    assert dospasos.qr_svg(dospasos.uri("ABC234", "dra@x.co")).startswith("<svg")


def activar(c, conn_db=None):
    r = c.post("/api/2fa/iniciar", json={"password": PASSWORD})
    assert r.status_code == 200, r.text
    inicio = r.json()
    assert inicio["qr"].startswith("<svg") and "otpauth://totp/" in inicio["enlace"] and inicio["secreto"] in inicio["enlace"]
    r = c.post("/api/2fa/activar", json={"codigo": codigo_actual(inicio["secreto"])})
    assert r.status_code == 200, r.text
    return inicio["secreto"], r.json()["codigos"]


def liberar_paso(db_url):
    import psycopg
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute("UPDATE anestesiologo SET totp_ultimo_paso = 0")


def test_activar_y_entrar_con_dos_pasos(app_multi):
    c = entrar(EMAIL, PASSWORD)
    assert c.get("/api/yo").json()["dos_pasos"] is False
    secreto, codigos = activar(c)
    assert len(codigos) == 10 and c.get("/api/yo").json() == {**c.get("/api/yo").json(), "dos_pasos": True, "codigos_recuperacion": 10}
    # el secreto de una cuenta ya activada no se puede volver a pedir
    assert c.post("/api/2fa/iniciar", json={"password": PASSWORD}).status_code == 409

    liberar_paso(app_multi)
    otro = TestClient(main.app)
    r = otro.post("/api/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200 and r.json()["requiere_2fa"] is True and "sesion" not in otro.cookies
    token = r.json()["token_2fa"]
    assert otro.get("/api/yo").status_code == 401                                    # todavía sin sesión
    assert otro.post("/api/login-2fa", json={"token_2fa": token, "codigo": "000000"}).status_code == 401
    r = otro.post("/api/login-2fa", json={"token_2fa": token, "codigo": codigo_actual(secreto)})
    assert r.status_code == 200, r.text
    assert otro.get("/api/yo").status_code == 200
    # el mismo código no sirve dos veces (se vio por encima del hombro)
    tercero = TestClient(main.app)
    tok = tercero.post("/api/login", json={"email": EMAIL, "password": PASSWORD}).json()["token_2fa"]
    assert tercero.post("/api/login-2fa", json={"token_2fa": tok, "codigo": codigo_actual(secreto)}).status_code == 401


def test_el_token_del_segundo_paso_no_es_una_sesion_ni_vale_para_otra_cuenta(app_multi, monkeypatch):
    from app import auth
    c = entrar(EMAIL, PASSWORD)
    activar(c)
    token = auth.crear_token_2fa(1, 0)
    ajeno = TestClient(main.app)
    ajeno.cookies.set(auth.COOKIE, token)            # el token usado como cookie no abre nada
    assert ajeno.get("/api/yo").status_code == 401
    assert auth.leer_token_2fa(token) == (1, 0) and auth.leer_token_2fa(token[:-2] + "00") is None
    assert auth.leer_sesion(auth.crear_sesion(1, 0)) == (1, 0) and auth.leer_token_2fa(auth.crear_sesion(1, 0)) is None
    ahora = time.time()
    monkeypatch.setattr(auth.time, "time", lambda: ahora + auth.PRUEBA_2FA_SEGUNDOS + 5)
    assert auth.leer_token_2fa(token) is None        # vence a los 5 minutos


def test_codigo_de_recuperacion_sirve_una_sola_vez(app_multi):
    c = entrar(EMAIL, PASSWORD)
    secreto, codigos = activar(c)
    for i in range(2):
        otro = TestClient(main.app)
        token = otro.post("/api/login", json={"email": EMAIL, "password": PASSWORD}).json()["token_2fa"]
        r = otro.post("/api/login-2fa", json={"token_2fa": token, "codigo": codigos[0].upper()})
        assert r.status_code == (200 if i == 0 else 401)
    assert c.get("/api/yo").json()["codigos_recuperacion"] == 9


def test_los_fallos_del_segundo_paso_bloquean_la_cuenta(app_multi):
    c = entrar(EMAIL, PASSWORD)
    activar(c)
    otro = TestClient(main.app)
    token = otro.post("/api/login", json={"email": EMAIL, "password": PASSWORD}).json()["token_2fa"]
    estados = [otro.post("/api/login-2fa", json={"token_2fa": token, "codigo": "111111"}).status_code for _ in range(5)]
    assert estados == [401, 401, 401, 401, 429]
    # bloqueada: ni la contraseña correcta ni el código correcto entran
    assert otro.post("/api/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 429
    assert otro.post("/api/login-2fa", json={"token_2fa": token, "codigo": "111111"}).status_code == 429


def test_conocer_la_clave_no_reinicia_el_contador_de_fallos_del_codigo(app_multi):
    c = entrar(EMAIL, PASSWORD)
    activar(c)
    otro = TestClient(main.app)
    for _ in range(3):   # 3 fallos de código, nueva contraseña correcta, 2 fallos más: se bloquea igual (5 acumulados)
        token = otro.post("/api/login", json={"email": EMAIL, "password": PASSWORD}).json()["token_2fa"]
        otro.post("/api/login-2fa", json={"token_2fa": token, "codigo": "222222"})
    token = otro.post("/api/login", json={"email": EMAIL, "password": PASSWORD}).json()["token_2fa"]
    assert otro.post("/api/login-2fa", json={"token_2fa": token, "codigo": "222222"}).status_code == 401
    assert otro.post("/api/login-2fa", json={"token_2fa": token, "codigo": "222222"}).status_code in (401, 429)
    assert otro.post("/api/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 429


def test_desactivar_y_renovar_codigos_piden_clave_y_codigo(app_multi):
    c = entrar(EMAIL, PASSWORD)
    secreto, codigos = activar(c)
    liberar_paso(app_multi)
    assert c.post("/api/2fa/desactivar", json={"password": "equivocada-123", "codigo": codigo_actual(secreto)}).status_code == 400
    assert c.post("/api/2fa/desactivar", json={"password": PASSWORD, "codigo": "000000"}).status_code == 400
    nuevos = c.post("/api/2fa/codigos", json={"password": PASSWORD, "codigo": codigo_actual(secreto)})
    assert nuevos.status_code == 200 and set(nuevos.json()["codigos"]).isdisjoint(codigos)
    # los códigos anteriores ya no sirven
    otro = TestClient(main.app)
    token = otro.post("/api/login", json={"email": EMAIL, "password": PASSWORD}).json()["token_2fa"]
    assert otro.post("/api/login-2fa", json={"token_2fa": token, "codigo": codigos[1]}).status_code == 401
    assert c.post("/api/2fa/desactivar", json={"password": PASSWORD, "codigo": nuevos.json()["codigos"][0]}).status_code == 200
    assert c.get("/api/yo").json()["dos_pasos"] is False
    assert TestClient(main.app).post("/api/login", json={"email": EMAIL, "password": PASSWORD}).json().get("requiere_2fa") is None


def test_activar_pide_la_clave_y_un_codigo_valido(app_multi):
    c = entrar(EMAIL, PASSWORD)
    assert c.post("/api/2fa/iniciar", json={"password": "equivocada-123"}).status_code == 400
    assert c.post("/api/2fa/activar", json={"codigo": "123456"}).status_code == 409      # sin haber iniciado
    secreto = c.post("/api/2fa/iniciar", json={"password": PASSWORD}).json()["secreto"]
    assert c.post("/api/2fa/activar", json={"codigo": "000000"}).status_code == 400
    assert c.get("/api/yo").json()["dos_pasos"] is False                                # nada quedó activo a medias
    assert c.post("/api/2fa/activar", json={"codigo": codigo_actual(secreto)}).status_code == 200


def test_el_administrador_restablece_a_quien_perdio_el_telefono(app_multi):
    admin = entrar(EMAIL, PASSWORD)
    nueva = crear_cuenta(admin)
    otro = entrar_y_cambiar("otro@clinica.co", nueva["clave_temporal"])
    r = otro.post("/api/2fa/iniciar", json={"password": "clave-nueva-123"})
    otro.post("/api/2fa/activar", json={"codigo": codigo_actual(r.json()["secreto"])})
    assert otro.get("/api/yo").json()["dos_pasos"] is True
    assert otro.post(f"/api/usuarios/{nueva['anestesiologo_id']}/restablecer-2fa").status_code == 403   # solo el admin
    assert admin.post(f"/api/usuarios/{nueva['anestesiologo_id']}/restablecer-2fa").status_code == 200
    assert otro.get("/api/yo").status_code == 401                                        # se cerraron sus sesiones
    assert TestClient(main.app).post("/api/login", json={"email": "otro@clinica.co", "password": "clave-nueva-123"}).json().get("requiere_2fa") is None
    assert admin.post("/api/usuarios/1/restablecer-2fa").status_code == 400


def test_dos_pasos_exigido_al_administrador(app_multi, monkeypatch):
    monkeypatch.setattr(config, "EXIGIR_2FA_ADMIN", True)
    c = entrar(EMAIL, PASSWORD)
    assert c.get("/api/yo").json()["exigir_dos_pasos"] is True
    r = c.get("/api/cirugias")
    assert r.status_code == 403 and r.json()["detail"]["activar_2fa"] is True
    secreto, _ = activar(c)                                                              # activar sí se puede
    assert c.get("/api/cirugias").status_code == 200
    assert c.post("/api/2fa/desactivar", json={"password": PASSWORD, "codigo": "000000"}).status_code == 403


def test_cambiar_admin_password_en_render_apaga_los_dos_pasos(db_url, monkeypatch):
    """Salida de emergencia: si se pierden el teléfono y los códigos, cambiar ADMIN_PASSWORD en Render la quita."""
    import psycopg
    from app import inicio
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "ADMIN_EMAIL", "jefe@clinica.co")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "clave-de-render-1")
    inicio.preparar_base_de_datos()
    with psycopg.connect(db_url, autocommit=True) as db:
        estado = lambda: db.execute("SELECT totp_activo, totp_secreto FROM anestesiologo WHERE email = 'jefe@clinica.co'").fetchone()  # noqa: E731
        db.execute("UPDATE anestesiologo SET totp_activo = TRUE, totp_secreto = 'ABC234' WHERE email = 'jefe@clinica.co'")
        inicio.preparar_base_de_datos()                       # reinicio con la misma clave: no se toca
        assert estado() == (True, "ABC234")
        monkeypatch.setattr(config, "ADMIN_PASSWORD", "clave-de-render-2")
        inicio.preparar_base_de_datos()                       # la clave cambió en Render: se apaga
        assert estado() == (False, None)
