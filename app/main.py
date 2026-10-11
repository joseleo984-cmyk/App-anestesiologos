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
from datetime import date
from pathlib import Path
from typing import Literal, Optional

from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from app import almacenamiento, auth, catalogo, config, exportar, extraccion, inicio, repositorio
from app.modelos import OrdenConfirmada, Sugerencia

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
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


def cuenta_sesion(sesion: str | None = Cookie(default=None), conn=Depends(get_conn)) -> dict:
    """Cuenta de la sesión: la cookie debe ser válida, la cuenta estar activa y la sesión
    no haber sido cerrada (cambio de clave o desactivación suben la versión)."""
    datos = auth.leer_sesion(sesion)
    cuenta = repositorio.obtener_cuenta(conn, datos[0]) if datos else None
    if cuenta is None or not cuenta["activo"] or cuenta["version_sesion"] != datos[1]:
        raise HTTPException(401, "Inicia sesión para continuar.")
    return cuenta


def anestesiologo_actual(cuenta: dict = Depends(cuenta_sesion)) -> int:
    if cuenta["debe_cambiar_clave"]:
        raise HTTPException(403, {"mensaje": "Cambia tu contraseña temporal para continuar.", "cambiar_clave": True})
    return cuenta["anestesiologo_id"]


def admin_actual(cuenta: dict = Depends(cuenta_sesion), _=Depends(anestesiologo_actual)) -> dict:
    if not cuenta["es_admin"]:
        raise HTTPException(403, "Solo el administrador puede gestionar las cuentas.")
    return cuenta


def poner_cookie(response: Response, anestesiologo_id: int, version: int) -> None:
    response.set_cookie(auth.COOKIE, auth.crear_sesion(anestesiologo_id, version),
                        max_age=auth.DURACION_SESION, httponly=True, samesite="lax",
                        secure=config.COOKIE_SEGURA)


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


def _leer_subida(archivo: UploadFile) -> tuple[bytes, str]:
    """Lee el archivo subido y valida tamaño y tipo real (por contenido)."""
    datos = archivo.file.read(config.MAX_ARCHIVO_MB * 1024 * 1024 + 1)
    if not datos:
        raise HTTPException(400, "El archivo está vacío.")
    if len(datos) > config.MAX_ARCHIVO_MB * 1024 * 1024:
        raise HTTPException(413, f"El archivo supera {config.MAX_ARCHIVO_MB} MB.")
    tipo = _tipo_real(datos)
    log.info("Archivo recibido: %s, %d bytes, tipo declarado %s, tipo real %s",
             archivo.filename, len(datos), archivo.content_type, tipo)
    if tipo is None:
        raise HTTPException(415, "Solo se aceptan fotos (JPG, PNG, WEBP, HEIC) o PDF.")
    return datos, tipo


@app.get("/", include_in_schema=False)
def pagina_principal(sesion: str | None = Cookie(default=None)):
    # no-store: que el navegador no muestre una copia guardada después de cerrar sesión
    if auth.leer_sesion(sesion) is None:
        return RedirectResponse("/login", status_code=303, headers={"Cache-Control": "no-store"})
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/login", include_in_schema=False)
def pagina_login():
    return FileResponse(STATIC / "login.html")


@app.get("/prueba-archivo", include_in_schema=False)
def pagina_prueba_archivo():
    """Página mínima para diagnosticar el selector de archivos del navegador (no sube nada)."""
    return FileResponse(STATIC / "prueba-archivo.html", headers={"Cache-Control": "no-store"})


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
    if (not usuario or not usuario["activo"]
            or not auth.verificar_password(datos.password, usuario["password_hash"])):
        time.sleep(1)  # frena los intentos de adivinar contraseñas
        raise HTTPException(401, "Correo o contraseña incorrectos.")
    poner_cookie(response, usuario["anestesiologo_id"], usuario["version_sesion"])
    return {"nombre": usuario["nombre"], "debe_cambiar_clave": usuario["debe_cambiar_clave"]}


@app.post("/api/logout")
def cerrar_sesion(response: Response):
    response.delete_cookie(auth.COOKIE, httponly=True, samesite="lax", secure=config.COOKIE_SEGURA)
    return {"ok": True}


@app.get("/api/yo")
def usuario_actual(cuenta: dict = Depends(cuenta_sesion)):
    return {"anestesiologo_id": cuenta["anestesiologo_id"], "nombre": cuenta["nombre"], "email": cuenta["email"],
            "es_admin": cuenta["es_admin"], "debe_cambiar_clave": cuenta["debe_cambiar_clave"],
            "ciudad_por_defecto": config.CIUDAD_POR_DEFECTO, "version": config.VERSION}


class CambioClave(BaseModel):
    actual: str
    nueva: str = Field(min_length=10, max_length=200)


@app.post("/api/cambiar-clave")
def cambiar_mi_clave(datos: CambioClave, response: Response, conn=Depends(get_conn),
                     cuenta: dict = Depends(cuenta_sesion)):
    if not auth.verificar_password(datos.actual, cuenta["password_hash"]):
        time.sleep(1)
        raise HTTPException(400, "La contraseña actual no es correcta.")
    if datos.nueva == datos.actual:
        raise HTTPException(400, "La contraseña nueva debe ser distinta de la actual.")
    version = repositorio.cambiar_clave(conn, cuenta["anestesiologo_id"], auth.hash_password(datos.nueva), False)
    conn.commit()
    poner_cookie(response, cuenta["anestesiologo_id"], version)  # esta sesión sigue; las demás se cierran
    return {"ok": True}


# ---------------------------------------------------------------- cuentas (administrador)
class NuevoUsuario(BaseModel):
    nombre: str = Field(min_length=3, max_length=150)
    email: str = Field(min_length=5, max_length=150, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    registro_medico: Optional[str] = Field(default=None, max_length=30)


class EstadoUsuario(BaseModel):
    activo: bool


@app.get("/api/usuarios")
def listar_usuarios(conn=Depends(get_conn), _=Depends(admin_actual)):
    return repositorio.listar_usuarios(conn)


@app.post("/api/usuarios", status_code=201)
def crear_usuario(datos: NuevoUsuario, conn=Depends(get_conn), _=Depends(admin_actual)):
    """Crea la cuenta con una clave temporal que se muestra una sola vez."""
    clave = auth.clave_temporal()
    try:
        nuevo = repositorio.crear_usuario(conn, " ".join(datos.nombre.split()), datos.email,
                                          (datos.registro_medico or "").strip() or None, auth.hash_password(clave))
    except repositorio.EmailYaRegistrado:
        conn.rollback()
        raise HTTPException(409, "Ya existe una cuenta con ese correo o registro médico.")
    conn.commit()
    return {"anestesiologo_id": nuevo, "clave_temporal": clave}


@app.put("/api/usuarios/{usuario_id}")
def activar_usuario(usuario_id: int, datos: EstadoUsuario, conn=Depends(get_conn), admin=Depends(admin_actual)):
    if usuario_id == admin["anestesiologo_id"] and not datos.activo:
        raise HTTPException(400, "No puedes desactivar tu propia cuenta.")
    if not repositorio.cambiar_activo(conn, usuario_id, datos.activo):
        raise HTTPException(404, "Cuenta no encontrada.")
    conn.commit()
    return {"ok": True}


@app.post("/api/usuarios/{usuario_id}/restablecer")
def restablecer_clave(usuario_id: int, conn=Depends(get_conn), admin=Depends(admin_actual)):
    """Nueva clave temporal (se muestra una sola vez); cierra las sesiones abiertas de esa cuenta."""
    if usuario_id == admin["anestesiologo_id"]:
        raise HTTPException(400, "Para tu propia cuenta usa «Cambiar contraseña».")
    if repositorio.obtener_cuenta(conn, usuario_id) is None:
        raise HTTPException(404, "Cuenta no encontrada.")
    clave = auth.clave_temporal()
    repositorio.cambiar_clave(conn, usuario_id, auth.hash_password(clave), True)
    conn.commit()
    return {"clave_temporal": clave}


MAX_PAGINAS = 8


# Palabras que traen casi todos los nombres de clínicas y no ayudan a distinguirlas
_GENERICAS = {"CLINICA", "IPS", "SAS", "SA", "S", "A", "LTDA", "ESE", "E", "ORGANIZACION", "DE", "DEL", "LA", "EL", "LAS", "LOS"}


def _parecido_clinica(a: str, b: str) -> float:
    a = " ".join(p for p in a.split() if p not in _GENERICAS)
    b = " ".join(p for p in b.split() if p not in _GENERICAS)
    if not a or not b:
        return 0
    # "PORTO AZUL" = "PORTOAZUL"; "BONNADONA PREVENIR" ~ "BONNADONA"
    return max(fuzz.token_set_ratio(a, b), fuzz.ratio(a.replace(" ", ""), b.replace(" ", "")))


def ajustar_clinica(conn, orden) -> None:
    """Si la clínica leída se parece mucho a una ya registrada, se usa el nombre registrado
    (así 'Clinica del Caribe S.A.S' y 'CLÍNICA DEL CARIBE' no quedan como dos clínicas)."""
    if not orden.clinica.nombre:
        return
    clinicas = repositorio.listar_clinicas(conn)
    if orden.clinica.ciudad:
        ciudad = repositorio.clave_nombre(orden.clinica.ciudad)
        clinicas = [c for c in clinicas if repositorio.clave_nombre(c["ciudad"]) == ciudad]
    leida = repositorio.clave_nombre(orden.clinica.nombre)
    parecidas = [c for c in clinicas if _parecido_clinica(leida, repositorio.clave_nombre(c["nombre"])) >= 90]
    if len(parecidas) != 1:
        return  # clínica nueva, o se parece a varias: que el anestesiólogo elija
    elegida = parecidas[0]
    if repositorio.clave_nombre(elegida["nombre"]) != leida and "clinica.nombre" not in orden.campos_dudosos:
        orden.campos_dudosos.append("clinica.nombre")
    orden.clinica.nombre = elegida["nombre"]
    orden.clinica.ciudad = orden.clinica.ciudad or elegida["ciudad"]


def completar_codigos(orden) -> None:
    """Procedimientos sin código CUPS: se busca su nombre en el catálogo CUPS. Si la coincidencia es
    clara se pone el código (marcado para revisar); si no, quedan las opciones para elegir."""
    for i, p in enumerate(orden.procedimientos):
        if p.codigo or not p.nombre:
            continue
        elegido, sugerencias = catalogo.codigo_probable(p.nombre)
        p.sugerencias = [Sugerencia(codigo=s["codigo"], descripcion=s["descripcion"]) for s in sugerencias]
        if elegido:
            p.codigo, p.codigo_sugerido = elegido["codigo"], True
        marca = f"procedimientos[{i}].codigo"
        if marca not in orden.campos_dudosos:
            orden.campos_dudosos.append(marca)


@app.post("/api/documentos", status_code=201)
def subir_documento(archivos: list[UploadFile] = File(default=[]), archivo: Optional[UploadFile] = None,
                    conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    """Sube una orden en uno o varios archivos (fotos o páginas de la misma orden) y la lee con la IA.
    Función normal (no async): FastAPI la ejecuta en otro hilo, así la lectura con la IA
    no bloquea al servidor mientras atiende otras solicitudes."""
    subidos = ([archivo] if archivo else []) + list(archivos)
    if not subidos:
        raise HTTPException(400, "No llegó ningún archivo.")
    if len(subidos) > MAX_PAGINAS:
        raise HTTPException(413, f"Máximo {MAX_PAGINAS} fotos o archivos por orden.")
    paginas = [_leer_subida(a) for a in subidos]
    if sum(len(d) for d, _ in paginas) > 2 * config.MAX_ARCHIVO_MB * 1024 * 1024:
        raise HTTPException(413, f"Entre todos los archivos superan {2 * config.MAX_ARCHIVO_MB} MB.")

    # Un solo archivo conserva su huella de siempre; varios, la huella del conjunto en su orden
    huellas = [hashlib.sha256(d).hexdigest() for d, _ in paginas]
    hash_sha256 = huellas[0] if len(huellas) == 1 else hashlib.sha256("".join(huellas).encode()).hexdigest()
    existente = repositorio.buscar_documento_por_hash(conn, anestesiologo_id, hash_sha256)
    if existente and existente["estado"] != "ERROR":
        raise HTTPException(409, {"mensaje": "Esta orden ya se había subido.",
                                  "documento_id": existente["documento_id"]})
    if existente:  # un intento anterior falló: se reintenta con el mismo registro
        documento_id = existente["documento_id"]
    else:
        try:
            ubicaciones = [(almacenamiento.guardar(f"{uuid.uuid4().hex}{EXTENSIONES[t]}", d, t),
                            "PDF" if t == "application/pdf" else "IMAGEN") for d, t in paginas]
        except almacenamiento.AlmacenamientoError as e:
            raise HTTPException(502, str(e))
        documento_id = repositorio.crear_documento(conn, anestesiologo_id, ubicaciones, hash_sha256)
    conn.commit()

    try:
        orden = extraccion.extraer_orden(paginas)
    except extraccion.ExtraccionError as e:
        log.warning("No se pudo leer el documento %s: %s (causa: %r)", documento_id, e, e.__cause__)
        repositorio.marcar_error(conn, documento_id, str(e))
        conn.commit()
        raise HTTPException(422, {"mensaje": str(e), "documento_id": documento_id})
    except Exception:
        log.exception("Error inesperado extrayendo el documento %s", documento_id)
        repositorio.marcar_error(conn, documento_id, "error inesperado")
        conn.commit()
        raise HTTPException(502, {"mensaje": "No se pudo leer el documento, intenta de nuevo.",
                                  "documento_id": documento_id})

    ajustar_clinica(conn, orden)
    # Sin ciudad en la orden: la que el anestesiólogo ya usó para esa clínica o, si no, la de por defecto
    if not orden.clinica.ciudad:
        conocida = (repositorio.ciudad_conocida(conn, anestesiologo_id, orden.clinica.nombre)
                    if orden.clinica.nombre else None)
        orden.clinica.ciudad = conocida or config.CIUDAD_POR_DEFECTO

    completar_codigos(orden)
    repositorio.guardar_extraccion(conn, documento_id, orden)
    conn.commit()
    return {"documento_id": documento_id, "estado": "EXTRAIDO", "paginas": len(paginas),
            "datos": orden.model_dump(mode="json")}


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


@app.get("/api/documentos/{documento_id}/archivo")
def ver_archivo_original(documento_id: int, pagina: int = Query(default=1, ge=1, le=MAX_PAGINAS),
                         conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    """Una foto o PDF original de la orden (solo para su dueño)."""
    doc = repositorio.obtener_archivo(conn, documento_id, anestesiologo_id, pagina)
    if doc is None:
        raise HTTPException(404, "Documento no encontrado.")
    try:
        datos = almacenamiento.leer(doc["url_archivo"])
    except almacenamiento.AlmacenamientoError as e:
        raise HTTPException(502, str(e))
    tipo = _tipo_real(datos) or "application/octet-stream"
    return Response(datos, media_type=tipo,
                    headers={"Content-Disposition": f'inline; filename="orden-{documento_id}-{pagina}{EXTENSIONES.get(tipo, "")}"',
                             "Cache-Control": "private, no-store"})


class Filtros:
    """Filtros comunes de la lista, el Excel y los reportes (query string)."""
    def __init__(self, desde: Optional[date] = None, hasta: Optional[date] = None,
                 clinica_id: Optional[int] = None, cirujano_id: Optional[int] = None,
                 aseguradora_id: Optional[str] = Query(default=None, pattern=r"^(\d+|PARTICULAR)$"),
                 estado: Optional[Literal["PROGRAMADA", "REALIZADA", "CANCELADA", "FACTURADA", "PAGADA",
                                          "PENDIENTE"]] = None,
                 q: Optional[str] = Query(default=None, max_length=100)):
        self.valores = {"desde": desde, "hasta": hasta, "clinica_id": clinica_id, "cirujano_id": cirujano_id,
                        "aseguradora_id": aseguradora_id, "estado": estado, "q": (q or "").strip() or None}


@app.post("/api/cirugias", status_code=201)
def crear_cirugia_manual(orden: OrdenConfirmada, conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    """Registro sin foto, escribiendo los datos a mano."""
    cirugia_id = repositorio.guardar_orden(conn, anestesiologo_id, orden)
    conn.commit()
    return {"cirugia_id": cirugia_id}


@app.get("/api/cirugias")
def listar_cirugias(limite: int = 100, filtros: Filtros = Depends(),
                    conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    return repositorio.listar_cirugias(conn, anestesiologo_id, min(max(limite, 1), 500), filtros.valores)


@app.get("/api/cirugias.xlsx")
def exportar_excel(filtros: Filtros = Depends(), conn=Depends(get_conn),
                   anestesiologo_id=Depends(anestesiologo_actual)):
    cirugias = repositorio.listar_cirugias(conn, anestesiologo_id, 100_000, filtros.valores)
    glosas = repositorio.reporte_glosas(conn, anestesiologo_id, filtros.valores["desde"], filtros.valores["hasta"])
    libro = exportar.libro_cirugias(cirugias, repositorio.reporte(conn, anestesiologo_id, filtros.valores), glosas)
    return Response(libro, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="cirugias-{date.today()}.xlsx"'})


@app.get("/api/clinicas")
def clinicas_registradas(conn=Depends(get_conn), _=Depends(anestesiologo_actual)):
    return repositorio.listar_clinicas(conn)


@app.get("/api/opciones")
def opciones_de_filtro(conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    return repositorio.opciones_filtro(conn, anestesiologo_id)


@app.get("/api/reportes")
def reportes(filtros: Filtros = Depends(), conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    return repositorio.reporte(conn, anestesiologo_id, filtros.valores)


@app.get("/api/procedimientos")
def buscar_procedimientos(q: str = Query(min_length=2, max_length=120), _=Depends(anestesiologo_actual)):
    """Busca en el catálogo CUPS por inicio del código o por nombre (para autocompletar)."""
    resultados = catalogo.por_prefijo(q) if any(ch.isdigit() for ch in q) else catalogo.buscar(q, limite=8)
    return [{"codigo": r["codigo"], "descripcion": r["descripcion"]} for r in resultados]


@app.get("/api/glosas")
def reporte_de_glosas(desde: Optional[date] = None, hasta: Optional[date] = None,
                      conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    return repositorio.reporte_glosas(conn, anestesiologo_id, desde, hasta)


@app.get("/api/cirugias/{cirugia_id}")
def ver_cirugia(cirugia_id: int, conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    cirugia = repositorio.obtener_cirugia(conn, anestesiologo_id, cirugia_id)
    if cirugia is None:
        raise HTTPException(404, "Cirugía no encontrada.")
    return cirugia


@app.put("/api/cirugias/{cirugia_id}")
def corregir_cirugia(cirugia_id: int, orden: OrdenConfirmada,
                     conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    if not repositorio.actualizar_orden(conn, anestesiologo_id, cirugia_id, orden):
        conn.rollback()
        raise HTTPException(404, "Cirugía no encontrada.")
    conn.commit()
    return {"cirugia_id": cirugia_id}


# ---------------------------------------------------------------- reportes de pago
@app.post("/api/pagos", status_code=201)
def subir_reporte_pago(archivo: UploadFile, conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    """Sube la relación de pacientes pagados, la lee con la IA y la cruza con las cirugías."""
    datos, tipo = _leer_subida(archivo)
    hash_sha256 = hashlib.sha256(datos).hexdigest()
    existente = repositorio.buscar_reporte_por_hash(conn, anestesiologo_id, hash_sha256)
    if existente:
        raise HTTPException(409, {"mensaje": "Este reporte ya se había subido.", "reporte_id": existente["reporte_id"]})
    try:
        reporte = extraccion.extraer_reporte_pago(datos, tipo)
    except extraccion.ExtraccionError as e:
        log.warning("No se pudo leer el reporte de pago: %s (causa: %r)", e, e.__cause__)
        raise HTTPException(422, {"mensaje": str(e)})
    if not reporte.filas:
        raise HTTPException(422, {"mensaje": "No se encontraron pagos en el documento. ¿Es un reporte de pagos?"})
    try:
        ubicacion = almacenamiento.guardar(f"pago-{uuid.uuid4().hex}{EXTENSIONES[tipo]}", datos, tipo)
    except almacenamiento.AlmacenamientoError as e:
        raise HTTPException(502, str(e))
    reporte_id = repositorio.crear_reporte(conn, anestesiologo_id, ubicacion, hash_sha256, reporte)
    conn.commit()
    return repositorio.obtener_reporte(conn, anestesiologo_id, reporte_id)


@app.get("/api/pagos")
def listar_reportes_pago(conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    return repositorio.listar_reportes(conn, anestesiologo_id)


@app.get("/api/pagos/{reporte_id}")
def ver_reporte_pago(reporte_id: int, conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    reporte = repositorio.obtener_reporte(conn, anestesiologo_id, reporte_id)
    if reporte is None:
        raise HTTPException(404, "Reporte no encontrado.")
    return reporte


@app.post("/api/pagos/{reporte_id}/aplicar")
def aplicar_reporte_pago(reporte_id: int, conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    try:
        marcadas = repositorio.aplicar_reporte(conn, anestesiologo_id, reporte_id)
    except repositorio.DocumentoNoEncontrado:
        conn.rollback()
        raise HTTPException(404, "Reporte no encontrado.")
    conn.commit()
    return {"marcadas": marcadas}


@app.post("/api/pagos/{reporte_id}/cruzar")
def volver_a_cruzar(reporte_id: int, conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    """Repite el cruce (por ejemplo, después de registrar las cirugías que faltaban)."""
    if repositorio.obtener_reporte(conn, anestesiologo_id, reporte_id) is None:
        raise HTTPException(404, "Reporte no encontrado.")
    repositorio.conciliar(conn, anestesiologo_id, reporte_id)
    conn.commit()
    return repositorio.obtener_reporte(conn, anestesiologo_id, reporte_id)


@app.delete("/api/pagos/{reporte_id}", status_code=204)
def descartar_reporte_pago(reporte_id: int, conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    """Descarta un reporte leído (por ejemplo, si la lectura quedó mal). Uno aplicado no se borra."""
    borrado = conn.execute(
        "DELETE FROM reporte_pago WHERE reporte_id = %s AND anestesiologo_id = %s AND estado = 'LEIDO'",
        (reporte_id, anestesiologo_id),
    ).rowcount
    if not borrado:
        raise HTTPException(409, "Solo se puede descartar un reporte que aún no se ha aplicado.")
    conn.commit()
    return Response(status_code=204)


@app.get("/api/pagos/{reporte_id}/archivo")
def ver_reporte_original(reporte_id: int, conn=Depends(get_conn), anestesiologo_id=Depends(anestesiologo_actual)):
    fila = conn.execute("SELECT url_archivo FROM reporte_pago WHERE reporte_id = %s AND anestesiologo_id = %s",
                        (reporte_id, anestesiologo_id)).fetchone()
    if fila is None:
        raise HTTPException(404, "Reporte no encontrado.")
    try:
        datos = almacenamiento.leer(fila["url_archivo"])
    except almacenamiento.AlmacenamientoError as e:
        raise HTTPException(502, str(e))
    return Response(datos, media_type=_tipo_real(datos) or "application/octet-stream",
                    headers={"Cache-Control": "private, no-store"})
