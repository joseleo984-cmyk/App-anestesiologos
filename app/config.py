import logging
import os
import secrets
from pathlib import Path

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///anestesia")
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads"))
# Supabase Storage (opcional): si están definidos, las órdenes se guardan allí y no en UPLOAD_DIR
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "ordenes")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
MAX_ARCHIVO_MB = int(os.environ.get("MAX_ARCHIVO_MB", "20"))

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
