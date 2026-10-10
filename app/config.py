import os
from pathlib import Path

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///anestesia")
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads"))
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
# Hasta tener inicio de sesión, la app trabaja a nombre de este anestesiólogo
ANESTESIOLOGO_ID = int(os.environ.get("ANESTESIOLOGO_ID", "1"))
MAX_ARCHIVO_MB = int(os.environ.get("MAX_ARCHIVO_MB", "20"))
