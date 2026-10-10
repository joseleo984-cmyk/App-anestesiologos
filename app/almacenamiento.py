"""Dónde se guardan las fotos y PDF de las órdenes.

Con SUPABASE_URL y SUPABASE_SERVICE_KEY van a un bucket privado de Supabase
Storage; sin ellas, a la carpeta UPLOAD_DIR (desarrollo local).
"""
import logging
from typing import Optional

import httpx

from app import config

log = logging.getLogger(__name__)


class AlmacenamientoError(Exception):
    pass


def usa_supabase() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)


def _cliente(cliente: Optional[httpx.Client]) -> httpx.Client:
    return cliente or httpx.Client(
        base_url=f"{config.SUPABASE_URL.rstrip('/')}/storage/v1", headers=_encabezados(), timeout=60)


def _encabezados() -> dict:
    clave = config.SUPABASE_SERVICE_KEY.strip()
    # Las claves nuevas (sb_secret_...) van solo en "apikey"; las antiguas service_role
    # (un JWT que empieza con eyJ) van también como Bearer.
    if clave.startswith("sb_"):
        return {"apikey": clave}
    return {"apikey": clave, "Authorization": f"Bearer {clave}"}


def preparar_bucket(cliente: Optional[httpx.Client] = None) -> None:
    """Crea el bucket privado si no existe. Si falla, se avisa en el log y la app sigue."""
    if not usa_supabase():
        return
    with _cliente(cliente) as c:
        r = c.post("/bucket", json={"id": config.SUPABASE_BUCKET, "name": config.SUPABASE_BUCKET, "public": False})
    if r.is_success:
        log.info("Bucket %s creado en Supabase Storage", config.SUPABASE_BUCKET)
    elif r.status_code in (400, 409) and ("exist" in r.text.lower() or "duplicate" in r.text.lower()):
        pass  # ya existía
    else:
        log.warning("No se pudo crear el bucket %s (%s): %s", config.SUPABASE_BUCKET, r.status_code, r.text[:200])


def guardar(nombre: str, datos: bytes, content_type: str, cliente: Optional[httpx.Client] = None) -> str:
    """Guarda el archivo y devuelve su ubicación (para documento_fuente.url_archivo)."""
    if not usa_supabase():
        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        ruta = config.UPLOAD_DIR / nombre
        ruta.write_bytes(datos)
        return str(ruta)
    try:
        with _cliente(cliente) as c:
            r = c.post(f"/object/{config.SUPABASE_BUCKET}/{nombre}", content=datos,
                       headers={"Content-Type": content_type, "x-upsert": "false"})
    except httpx.HTTPError as e:
        raise AlmacenamientoError("No se pudo guardar el archivo, intenta de nuevo.") from e
    if not r.is_success:
        log.error("Supabase Storage respondió %s: %s", r.status_code, r.text[:200])
        raise AlmacenamientoError("No se pudo guardar el archivo, intenta de nuevo.")
    return f"supabase://{config.SUPABASE_BUCKET}/{nombre}"
