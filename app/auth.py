"""Inicio de sesión: contraseñas con scrypt y sesión en una cookie firmada."""
import base64
import hashlib
import hmac
import secrets
import time
from typing import Optional

from app import config

COOKIE = "sesion"
DURACION_SESION = 30 * 24 * 3600  # 30 días
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=sal, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(sal).decode()}${base64.b64encode(h).decode()}"


def verificar_password(password: str, guardado: Optional[str]) -> bool:
    if not guardado:
        return False
    try:
        _, n, r, p, sal, h = guardado.split("$")
        calculado = hashlib.scrypt(password.encode(), salt=base64.b64decode(sal), n=int(n), r=int(r), p=int(p))
    except ValueError:
        return False
    return hmac.compare_digest(calculado, base64.b64decode(h))


def _firma(datos: str) -> str:
    return hmac.new(config.SESSION_SECRET.encode(), datos.encode(), hashlib.sha256).hexdigest()


def crear_sesion(anestesiologo_id: int, version: int = 0) -> str:
    """La versión permite cerrar todas las sesiones de alguien (al cambiar su clave o desactivarlo)."""
    datos = f"{anestesiologo_id}.{version}.{int(time.time())}"
    return f"{datos}.{_firma(datos)}"


def leer_sesion(valor: Optional[str]) -> Optional[tuple[int, int]]:
    """(anestesiólogo, versión) de la cookie si la firma es válida y no ha vencido."""
    if not valor:
        return None
    try:
        anestesiologo_id, version, emitida, firma = valor.split(".")
        if not hmac.compare_digest(firma, _firma(f"{anestesiologo_id}.{version}.{emitida}")):
            return None
        if time.time() - int(emitida) > DURACION_SESION:
            return None
        return int(anestesiologo_id), int(version)
    except ValueError:
        return None


def clave_temporal() -> str:
    """Clave fácil de dictar: sin letras ni números que se confundan (0/O, 1/l)."""
    alfabeto = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(3))
