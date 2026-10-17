"""Defensas transversales: cabeceras del navegador, verificación de origen (CSRF) y textos seguros para Excel."""
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse

from app import config

# La app usa scripts y estilos en la propia página («unsafe-inline») y las tipografías de Google Fonts; todo lo demás
# solo puede venir de la propia app. Nadie puede incrustar la app en otra página (frame-ancestors).
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob:",
    "connect-src 'self'",
    "worker-src 'self' blob:",
    "frame-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

CABECERAS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
METODOS_QUE_CAMBIAN = {"POST", "PUT", "DELETE", "PATCH"}


def origen_permitido(request: Request) -> bool:
    """Defensa extra contra CSRF: si el navegador manda Origin (siempre lo hace en peticiones que cambian datos),
    debe ser la propia app. Sin Origin (herramientas, pruebas) se deja pasar: no trae cookies de otra página."""
    origen = request.headers.get("origin")
    if not origen:
        return True
    if origen == "null":
        return False
    return urlparse(origen).netloc == request.headers.get("host", "")


async def cabeceras_de_seguridad(request: Request, call_next):
    if request.method in METODOS_QUE_CAMBIAN and not origen_permitido(request):
        respuesta = JSONResponse({"detail": "Petición de origen no permitido."}, status_code=403)
    else:
        respuesta = await call_next(request)
    for nombre, valor in CABECERAS.items():
        respuesta.headers.setdefault(nombre, valor)
    if config.COOKIE_SEGURA:  # solo con HTTPS: el navegador recuerda no abrir nunca la app sin cifrar
        respuesta.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith("/api/"):
        respuesta.headers.setdefault("Cache-Control", "no-store")   # datos de pacientes: que no queden en cachés
    return respuesta


def texto_seguro(valor):
    """Excel ejecuta como fórmula lo que empieza con = + - @ (o tabulador / retorno): un nombre de paciente
    o un texto leído de un documento podría traer una. Se antepone una comilla para que sea solo texto."""
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valor
    return valor


def fila_segura(fila: list) -> list:
    return [texto_seguro(v) for v in fila]
