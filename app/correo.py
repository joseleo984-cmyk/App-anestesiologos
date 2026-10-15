"""Envío de correos (por ahora, el enlace para restablecer la contraseña).

Se usa el primer proveedor configurado en Render:
- BREVO_API_KEY: Brevo (gratis hasta 300 correos al día). Basta verificar el correo remitente, no hace falta dominio.
- RESEND_API_KEY: Resend (requiere un dominio propio verificado).
- SMTP_HOST, SMTP_USUARIO, SMTP_CLAVE (y SMTP_PUERTO): servidor de correo propio.
CORREO_REMITENTE es el correo que aparece como remitente (debe estar verificado en el proveedor).
Las llamadas a la API van por HTTPS: el plan gratis de Render puede bloquear los puertos de SMTP.
"""
import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Optional

import httpx

log = logging.getLogger(__name__)
NOMBRE_REMITENTE = "Auditorías AP"


class CorreoError(Exception):
    pass


def _conf(nombre: str) -> str:
    return os.environ.get(nombre, "").strip()


def proveedor() -> Optional[str]:
    if not _conf("CORREO_REMITENTE"):
        return None
    if _conf("BREVO_API_KEY"):
        return "brevo"
    if _conf("RESEND_API_KEY"):
        return "resend"
    if _conf("SMTP_HOST") and _conf("SMTP_USUARIO"):
        return "smtp"
    return None


def configurado() -> bool:
    return proveedor() is not None


def enviar(destino: str, asunto: str, texto: str, html: str, cliente: Optional[httpx.Client] = None) -> None:
    p, remitente = proveedor(), _conf("CORREO_REMITENTE")
    if p is None:
        raise CorreoError("El envío de correos no está configurado.")
    try:
        if p == "smtp":
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = f"{NOMBRE_REMITENTE} <{remitente}>", destino, asunto
            msg.set_content(texto)
            msg.add_alternative(html, subtype="html")
            with smtplib.SMTP(_conf("SMTP_HOST"), int(_conf("SMTP_PUERTO") or 587), timeout=20) as s:
                s.starttls()
                s.login(_conf("SMTP_USUARIO"), _conf("SMTP_CLAVE"))
                s.send_message(msg)
            return
        http = cliente or httpx.Client(timeout=20)
        if p == "brevo":
            r = http.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": _conf("BREVO_API_KEY")},
                          json={"sender": {"name": NOMBRE_REMITENTE, "email": remitente}, "to": [{"email": destino}],
                                "subject": asunto, "textContent": texto, "htmlContent": html})
        else:
            r = http.post("https://api.resend.com/emails", headers={"Authorization": f"Bearer {_conf('RESEND_API_KEY')}"},
                          json={"from": f"{NOMBRE_REMITENTE} <{remitente}>", "to": [destino],
                                "subject": asunto, "text": texto, "html": html})
        if r.status_code >= 300:
            raise CorreoError(f"{p} respondió {r.status_code}: {r.text[:200]}")
    except (httpx.HTTPError, smtplib.SMTPException, OSError) as e:
        raise CorreoError(f"No se pudo enviar el correo por {p}: {e}") from e
