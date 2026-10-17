"""Verificación en dos pasos (TOTP, RFC 6238): el código de 6 dígitos de Google/Microsoft Authenticator, Authy, etc.
Sin servicios externos. También códigos de recuperación de un solo uso por si se pierde el teléfono."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote

import segno

EMISOR = "Auditorías AP"
PASO = 30            # segundos que dura cada código
VENTANA = 1          # se acepta el código anterior y el siguiente (relojes algo desfasados)
CANTIDAD_RECUPERACION = 10


def nuevo_secreto() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _codigo(secreto: str, paso: int) -> str:
    clave = base64.b32decode(secreto + "=" * (-len(secreto) % 8))
    h = hmac.new(clave, struct.pack(">Q", paso), hashlib.sha1).digest()
    o = h[-1] & 15
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def verificar(secreto: str, codigo: str, ultimo_paso: int = 0, ahora: Optional[float] = None) -> Optional[int]:
    """El paso (ventana de 30 s) al que corresponde el código, o None. Un paso ya usado no vale otra vez
    (así no se puede reutilizar un código visto por encima del hombro)."""
    codigo = "".join(c for c in (codigo or "") if c.isdigit())
    if len(codigo) != 6:
        return None
    actual = int((ahora if ahora is not None else time.time()) // PASO)
    for paso in range(actual - VENTANA, actual + VENTANA + 1):
        if paso > ultimo_paso and hmac.compare_digest(_codigo(secreto, paso), codigo):
            return paso
    return None


def uri(secreto: str, email: str) -> str:
    return f"otpauth://totp/{quote(EMISOR)}:{quote(email)}?secret={secreto}&issuer={quote(EMISOR)}&digits=6&period={PASO}"


def qr_svg(texto: str) -> str:
    """El QR se dibuja aquí, en el servidor: el secreto no viaja a ningún servicio externo."""
    return segno.make(texto, error="m").svg_inline(scale=5, border=2, dark="#000000", light="#ffffff")


def _normalizar(codigo: str) -> str:
    return "".join(c for c in (codigo or "").lower() if c.isalnum())


def hash_recuperacion(codigo: str) -> str:
    return hashlib.sha256(_normalizar(codigo).encode()).hexdigest()


def codigos_de_recuperacion() -> list[str]:
    alfabeto = "abcdefghjkmnpqrstuvwxyz23456789"   # sin letras que se confundan (0/o, 1/l)
    return ["-".join("".join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(2))
            for _ in range(CANTIDAD_RECUPERACION)]
