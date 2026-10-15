"""Calidad de la lectura con IA: qué campos corrige el anestesiólogo antes de guardar una orden, y los comentarios
de «¿Qué te faltó?». Solo se guardan los NOMBRES de los campos y el tipo de cambio, nunca los valores (son datos
del paciente)."""
import re
import unicodedata
from typing import Optional

from app.modelos import OrdenConfirmada

# campo -> cómo sacarlo de lo leído (dict) y de lo confirmado (modelo)
CAMPOS = {
    "paciente.tipo_documento": (lambda e: (e.get("paciente") or {}).get("tipo_documento"), lambda c: c.paciente.tipo_documento),
    "paciente.numero_documento": (lambda e: (e.get("paciente") or {}).get("numero_documento"), lambda c: c.paciente.numero_documento),
    "paciente.nombres": (lambda e: (e.get("paciente") or {}).get("nombres"), lambda c: c.paciente.nombres),
    "paciente.apellidos": (lambda e: (e.get("paciente") or {}).get("apellidos"), lambda c: c.paciente.apellidos),
    "aseguradora.nombre": (lambda e: (e.get("aseguradora") or {}).get("nombre"), lambda c: c.aseguradora and c.aseguradora.nombre),
    "aseguradora.tipo": (lambda e: (e.get("aseguradora") or {}).get("tipo"), lambda c: c.aseguradora and c.aseguradora.tipo),
    "aseguradora.numero_poliza": (lambda e: (e.get("aseguradora") or {}).get("numero_poliza"), lambda c: c.aseguradora and c.aseguradora.numero_poliza),
    "aseguradora.plan": (lambda e: (e.get("aseguradora") or {}).get("plan"), lambda c: c.aseguradora and c.aseguradora.plan),
    "clinica.nombre": (lambda e: (e.get("clinica") or {}).get("nombre"), lambda c: c.clinica.nombre),
    "clinica.ciudad": (lambda e: (e.get("clinica") or {}).get("ciudad"), lambda c: c.clinica.ciudad),
    "fecha_procedimiento": (lambda e: e.get("fecha_procedimiento"), lambda c: c.fecha_procedimiento and c.fecha_procedimiento.isoformat()),
    "cirujano": (lambda e: e.get("cirujano"), lambda c: c.cirujano),
    "numero_orden": (lambda e: e.get("numero_orden"), lambda c: c.numero_orden),
    "procedimientos.codigos": (lambda e: sorted(p.get("codigo") or "" for p in e.get("procedimientos") or []),
                               lambda c: sorted(p.codigo or "" for p in c.procedimientos)),
    "procedimientos.cantidad": (lambda e: len(e.get("procedimientos") or []), lambda c: len(c.procedimientos)),
}

NOMBRES = {
    "paciente.tipo_documento": "Tipo de documento", "paciente.numero_documento": "Número de documento",
    "paciente.nombres": "Nombres", "paciente.apellidos": "Apellidos", "aseguradora.nombre": "Aseguradora",
    "aseguradora.tipo": "Tipo de aseguradora", "aseguradora.numero_poliza": "Nº de póliza", "aseguradora.plan": "Plan",
    "clinica.nombre": "Clínica", "clinica.ciudad": "Ciudad", "fecha_procedimiento": "Fecha", "cirujano": "Cirujano",
    "numero_orden": "Nº de orden", "procedimientos.codigos": "Códigos de procedimiento",
    "procedimientos.cantidad": "Número de procedimientos",
}


def _normal(v):
    """Compara sin tildes, mayúsculas, espacios ni puntos: 'Clínica  del Caribe.' = 'CLINICA DEL CARIBE'."""
    if v is None or v == "" or v == []:
        return None
    if isinstance(v, list):
        return [_normal(x) for x in v]
    if isinstance(v, (int, float)):
        return v
    t = unicodedata.normalize("NFKD", str(v)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]", "", t) or None


def campos_corregidos(extraido: dict, confirmado: OrdenConfirmada) -> list[tuple[str, str]]:
    """[(campo, AGREGADO | CORREGIDO | BORRADO)] para cada campo que el anestesiólogo cambió frente a la lectura."""
    cambios = []
    for campo, (leido, final) in CAMPOS.items():
        a, b = _normal(leido(extraido)), _normal(final(confirmado))
        if a == b:
            continue
        cambios.append((campo, "AGREGADO" if a is None else "BORRADO" if b is None else "CORREGIDO"))
    return cambios


def registrar_correcciones(conn, anestesiologo_id: int, documento_id: int, confirmado: OrdenConfirmada) -> int:
    fila = conn.execute("SELECT datos_extraidos FROM documento_fuente WHERE documento_id = %s AND anestesiologo_id = %s",
                        (documento_id, anestesiologo_id)).fetchone()
    if not fila or not fila["datos_extraidos"]:
        return 0
    cambios = campos_corregidos(fila["datos_extraidos"], confirmado)
    for campo, cambio in cambios:
        conn.execute("""INSERT INTO correccion_lectura (documento_id, anestesiologo_id, campo, cambio)
                        VALUES (%s, %s, %s, %s)""", (documento_id, anestesiologo_id, campo, cambio))
    return len(cambios)


def guardar_comentario(conn, anestesiologo_id: int, documento_id: Optional[int], texto: str) -> int:
    return conn.execute(
        """INSERT INTO comentario_lectura (documento_id, anestesiologo_id, texto) VALUES (%s, %s, %s)
           RETURNING comentario_id""", (documento_id, anestesiologo_id, texto.strip()[:1000])).fetchone()["comentario_id"]


def resumen(conn) -> dict:
    """Para el administrador: los campos más corregidos (sobre el total de órdenes leídas y guardadas) y los comentarios."""
    leidas = conn.execute("""SELECT count(*) AS n FROM documento_fuente WHERE estado = 'VALIDADO'
                              AND subido_en > now() - interval '90 days'""").fetchone()["n"]
    campos = conn.execute(
        """SELECT campo, count(DISTINCT documento_id) AS ordenes,
                  count(*) FILTER (WHERE cambio = 'AGREGADO') AS agregados,
                  count(*) FILTER (WHERE cambio = 'CORREGIDO') AS corregidos,
                  count(*) FILTER (WHERE cambio = 'BORRADO') AS borrados
             FROM correccion_lectura WHERE creado_en > now() - interval '90 days'
            GROUP BY campo ORDER BY ordenes DESC""").fetchall()
    for c in campos:
        c["nombre"] = NOMBRES.get(c["campo"], c["campo"])
        c["porcentaje"] = round(c["ordenes"] / leidas * 100) if leidas else None
    comentarios = conn.execute(
        """SELECT k.comentario_id, k.texto, k.creado_en, k.documento_id, a.nombre
             FROM comentario_lectura k JOIN anestesiologo a USING (anestesiologo_id)
            ORDER BY k.creado_en DESC LIMIT 50""").fetchall()
    return {"ordenes_leidas": leidas, "campos": campos, "comentarios": comentarios}
