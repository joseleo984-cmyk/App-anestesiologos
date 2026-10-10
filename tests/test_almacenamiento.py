import json

import httpx
import pytest

from app import almacenamiento, config


@pytest.fixture
def supabase(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", "https://proyecto.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_SERVICE_KEY", "clave-servicio")
    monkeypatch.setattr(config, "SUPABASE_BUCKET", "ordenes")


def cliente(respuesta, solicitudes):
    def manejar(req: httpx.Request):
        solicitudes.append(req)
        return respuesta
    return httpx.Client(base_url="https://proyecto.supabase.co/storage/v1",
                        headers={"Authorization": "Bearer clave-servicio"},
                        transport=httpx.MockTransport(manejar))


def test_sin_supabase_guarda_en_disco(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SUPABASE_URL", None)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path)
    ubicacion = almacenamiento.guardar("a.pdf", b"%PDF", "application/pdf")
    assert (tmp_path / "a.pdf").read_bytes() == b"%PDF" and ubicacion == str(tmp_path / "a.pdf")


def test_sube_a_supabase(supabase):
    solicitudes = []
    ubicacion = almacenamiento.guardar("x.jpg", b"\xff\xd8\xff", "image/jpeg",
                                       cliente(httpx.Response(200, json={"Key": "ordenes/x.jpg"}), solicitudes))
    req = solicitudes[0]
    assert req.method == "POST" and req.url.path == "/storage/v1/object/ordenes/x.jpg"
    assert req.headers["content-type"] == "image/jpeg" and req.content == b"\xff\xd8\xff"
    assert ubicacion == "supabase://ordenes/x.jpg"


def test_error_de_supabase(supabase):
    with pytest.raises(almacenamiento.AlmacenamientoError):
        almacenamiento.guardar("x.jpg", b"1", "image/jpeg", cliente(httpx.Response(403, text="denied"), []))


def test_bucket_privado_y_ya_existente(supabase):
    solicitudes = []
    almacenamiento.preparar_bucket(cliente(httpx.Response(200, json={"name": "ordenes"}), solicitudes))
    assert json.loads(solicitudes[0].content) == {"id": "ordenes", "name": "ordenes", "public": False}
    # Si ya existe no falla
    almacenamiento.preparar_bucket(cliente(httpx.Response(409, text='{"error":"Duplicate","message":"The resource already exists"}'), []))


def test_encabezados_segun_tipo_de_clave(supabase, monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_SERVICE_KEY", "sb_secret_abc")
    assert almacenamiento._encabezados() == {"apikey": "sb_secret_abc"}
    monkeypatch.setattr(config, "SUPABASE_SERVICE_KEY", " eyJhbGciOi.x.y ")
    assert almacenamiento._encabezados() == {"apikey": "eyJhbGciOi.x.y", "Authorization": "Bearer eyJhbGciOi.x.y"}
