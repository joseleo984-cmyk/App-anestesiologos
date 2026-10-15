import logging
import os
import secrets
from pathlib import Path

from urllib.parse import quote

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///anestesia").strip()
# Permite pegar la dirección de Supabase tal cual (con [YOUR-PASSWORD]) y dar la
# contraseña aparte; se codifica para que los símbolos no rompan la dirección.
if "[YOUR-PASSWORD]" in DATABASE_URL and os.environ.get("DATABASE_PASSWORD"):
    DATABASE_URL = DATABASE_URL.replace("[YOUR-PASSWORD]", quote(os.environ["DATABASE_PASSWORD"].strip(), safe=""))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads"))
# Supabase Storage (opcional): si están definidos, las órdenes se guardan allí y no en UPLOAD_DIR
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "ordenes")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
# Modelo para resumir noticias (opcional): puede ser uno más económico que el de las órdenes
NOTICIAS_MODEL = os.environ.get("NOTICIAS_MODEL", "").strip() or None
MAX_ARCHIVO_MB = int(os.environ.get("MAX_ARCHIVO_MB", "20"))
# Dirección pública de la app, para los enlaces de los correos (si falta, se toma de la solicitud)
APP_URL = os.environ.get("APP_URL", "").strip().rstrip("/")
# Registro propio de anestesiólogos (quedan pendientes hasta que el administrador los apruebe). "no" lo cierra.
REGISTRO_ABIERTO = os.environ.get("REGISTRO_ABIERTO", "si").strip().lower() not in ("no", "false", "0")
# Ciudad que se usa cuando la orden no la trae y la clínica no tiene una conocida (vacío = ninguna)
CIUDAD_POR_DEFECTO = os.environ.get("CIUDAD_POR_DEFECTO", "Barranquilla").strip() or None
SMLMV = os.environ.get("SMLMV", "").replace(".", "").strip() or None  # salario mínimo para la liquidación

# Firma de las cookies de sesión. En producción debe venir del entorno;
# sin ella se genera una al azar y las sesiones se pierden al reiniciar.
SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)
if "SESSION_SECRET" not in os.environ:
    logging.getLogger(__name__).warning("SESSION_SECRET no está definido: se usa uno temporal")
# Solo enviar la cookie por HTTPS (activar en producción)
COOKIE_SEGURA = os.environ.get("COOKIE_SEGURA", "false").lower() == "true"

# Usuario inicial: se crea (o se le actualiza la contraseña) al arrancar
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ADMIN_NOMBRE = os.environ.get("ADMIN_NOMBRE", "Anestesiólogo")

# Versión publicada: Render define RENDER_GIT_COMMIT con el commit desplegado
VERSION = (os.environ.get("RENDER_GIT_COMMIT") or "local")[:7]
