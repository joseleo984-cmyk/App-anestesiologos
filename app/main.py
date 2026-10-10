"""API de la app de anestesiólogos.

Flujo:
  1. POST /api/documentos            sube la foto/PDF; la IA extrae los datos (estado EXTRAIDO)
  2. El usuario revisa y corrige los datos en pantalla
  3. POST /api/documentos/{id}/confirmar  guarda la cirugía (estado VALIDADO)
  4. GET  /api/cirugias              lista las cirugías del anestesiólogo
"""
import hashlib
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import almacenamiento, auth, config, extraccion, inicio, repositorio
from app.modelos import OrdenConfirmada

log = logging.getLogger(__name__)


@asynccontextmanager
async def ciclo_de_vida(_app):
    inicio.preparar_base_de_datos()
    almacenamiento.preparar_bucket()
    yield


app = FastAPI(title="App Anestesiólogos", lifespan=ciclo_de_vida)
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

EXTENSIONES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
               "image/gif": ".gif", "image/heic": ".heic", "application/pdf": ".pdf"}


def get_conn():
    with repositorio.conectar() as conn:
        yield conn


def anestesiologo_actual(sesion: str | None = Cookie(default=None), conn=Depends(get_conn)) -> int:
    anestesiologo_id = auth.leer_sesion(sesion)
    if anestesiologo_id is None or not repositorio.existe_anestesiologo(conn, anestesiologo_id):
        raise HTTPException(401, "Inicia sesión para continuar.")
    return anestesiologo_id


def _tipo_real(datos: bytes) -> str | None:
    """Identifica el archivo por su contenido, no por lo que diga el navegador."""
    firmas = [(b"%PDF", "application/pdf"), (b"\xff\xd8\xff", "image/jpeg"),
              (b"\x89PNG\r\n\x1a\n", "image/png"), (b"GIF8", "image/gif")]
    for firma, tipo in firmas:
        if datos.startswith(firma):
            return tipo
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "image/webp"
    # Fotos de iPhone/Mac (HEIC/HEIF)
    if datos[4:8] == b"ftyp" and datos[8:12] in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"):
        return "image/heic"
    return None


@app.get("/", include_in_schema=False)
def pagina_principal(sesion: str | None = Cookie(default=None)):
    # no-store: que el navegador no muestre una copia guardada después de cerrar sesión
    if auth.leer_sesion(sesion) is None:
        return RedirectResponse("/login", status_code=303, headers={"Cache-Control": "no-store"})
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/login", include_in_schema=False)
def pagina_login():
    return FileResponse(STATIC / "login.html")


@app.get("/salud", include_in_schema=False)
def salud(conn=Depends(get_conn)):
    conn.execute("SELECT 1")
    return {"estado": "ok"}


class Credenciales(BaseModel):
    email: str
    password: str


@app.post("/api/login")
def iniciar_sesion(datos: Credenciales, response: Response, conn=Depends(get_conn)):
    usuario = repositorio.buscar_anestesiologo_por_email(conn, datos.email)
    if not usuario or not auth.verificar_password(datos.password, usuario["password_hash"]):
        time.sleep(1)  # frena los intentos de adivinar contraseñas
        raise HTTPException(401, "Correo o contraseña incorrectos.")
    response.set_cookie(auth.COOKIE, auth.crear_sesion(usuario["anestesiologo_id"]),
                        max_age=auth.DURACION_SESION, httponly=True, samesite="lax",
                        secure=config.COOKIE_SEGURA)
    return {"nombre": usuario["nombre"]}


@app.post("/api/logout")
def cerrar_sesion(response: Response):
    response.delete_cookie(auth.COOKIE, httponly=True, samesite="lax", secure=config.COOKIE_SEGURA)
    return {"ok": True}


@app.get("/api/yo")
def usuario_actual(conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    return repositorio.obtener_anestesiologo(conn, anestesiologo_id)


@app.post("/api/documentos", status_code=201)
def subir_documento(archivo: UploadFile, conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    # Función normal (no async): FastAPI la ejecuta en otro hilo, así la lectura con la IA
    # no bloquea al servidor mientras atiende otras solicitudes.
    datos = archivo.file.read(config.MAX_ARCHIVO_MB * 1024 * 1024 + 1)
    if not datos:
        raise HTTPException(400, "El archivo está vacío.")
    if len(datos) > config.MAX_ARCHIVO_MB * 1024 * 1024:
        raise HTTPException(413, f"El archivo supera {config.MAX_ARCHIVO_MB} MB.")
    tipo = _tipo_real(datos)
    if tipo is None:
        raise HTTPException(415, "Solo se aceptan fotos (JPG, PNG, WEBP, HEIC) o PDF.")

    hash_sha256 = hashlib.sha256(datos).hexdigest()
    existente = repositorio.buscar_documento_por_hash(conn, hash_sha256)
    if existente and existente["estado"] != "ERROR":
        raise HTTPException(409, {"mensaje": "Este archivo ya se había subido.",
                                  "documento_id": existente["documento_id"]})
    if existente:  # un intento anterior falló: se reintenta con el mismo registro
        documento_id = existente["documento_id"]
    else:
        try:
            ubicacion = almacenamiento.guardar(f"{uuid.uuid4().hex}{EXTENSIONES[tipo]}", datos, tipo)
        except almacenamiento.AlmacenamientoError as e:
            raise HTTPException(502, str(e))
        documento_id = repositorio.crear_documento(
            conn, anestesiologo_id, "PDF" if tipo == "application/pdf" else "IMAGEN", ubicacion, hash_sha256)
    conn.commit()

    try:
        orden = extraccion.extraer_orden(datos, tipo)
    except extraccion.ExtraccionError as e:
        repositorio.marcar_error(conn, documento_id, str(e))
        conn.commit()
        raise HTTPException(422, {"mensaje": str(e), "documento_id": documento_id})
    except Exception:
        log.exception("Error inesperado extrayendo el documento %s", documento_id)
        repositorio.marcar_error(conn, documento_id, "error inesperado")
        conn.commit()
        raise HTTPException(502, {"mensaje": "No se pudo leer el documento, intenta de nuevo.",
                                  "documento_id": documento_id})

    repositorio.guardar_extraccion(conn, documento_id, orden)
    conn.commit()
    return {"documento_id": documento_id, "estado": "EXTRAIDO", "datos": orden.model_dump(mode="json")}


@app.get("/api/documentos/{documento_id}")
def ver_documento(documento_id: int, conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    doc = repositorio.obtener_documento(conn, documento_id, anestesiologo_id)
    if doc is None:
        raise HTTPException(404, "Documento no encontrado.")
    return doc


@app.post("/api/documentos/{documento_id}/confirmar", status_code=201)
def confirmar_documento(documento_id: int, orden: OrdenConfirmada,
                        conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    try:
        cirugia_id = repositorio.guardar_orden(conn, anestesiologo_id, orden, documento_id)
    except repositorio.DocumentoNoEncontrado:
        conn.rollback()
        raise HTTPException(404, "Documento no encontrado.")
    except repositorio.DocumentoYaValidado as e:
        conn.rollback()
        raise HTTPException(409, {"mensaje": "Esta orden ya fue guardada.", "cirugia_id": e.cirugia_id})
    conn.commit()
    return {"cirugia_id": cirugia_id}


@app.post("/api/cirugias", status_code=201)
def crear_cirugia_manual(orden: OrdenConfirmada, conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    """Registro sin foto, escribiendo los datos a mano."""
    cirugia_id = repositorio.guardar_orden(conn, anestesiologo_id, orden)
    conn.commit()
    return {"cirugia_id": cirugia_id}


@app.get("/api/cirugias")
def listar_cirugias(limite: int = 50, conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    return repositorio.listar_cirugias(conn, anestesiologo_id, min(max(limite, 1), 200))
