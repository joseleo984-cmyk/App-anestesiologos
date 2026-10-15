"""Cirugías que faltan en un radicado.

Hasta ahora AP se quedaba con las órdenes físicas, así que muchos pacientes de un radicado no están en la app.
Con los datos de la hoja (paciente, cédula, entidad y procedimiento) se crean esas cirugías para poder cobrarlas;
lo que la hoja no trae (fecha exacta, código CUPS, valor) queda marcado para revisar.
"""
import re
from typing import Optional

from app import catalogo, repositorio
from app.modelos import OrdenConfirmada

ENTIDAD_POR_CONFIRMAR = "ENTIDAD POR CONFIRMAR"
CODIGO_PENDIENTE = "PENDIENTE"   # + número: el procedimiento no tiene un código CUPS claro, se completa al revisar


def tipo_entidad(nombre: str) -> str:
    n = catalogo.normalizar(nombre)
    if re.search(r"PREPAG|SANITAS|MEDICINA PREP|COLMEDICA|MEDPLUS", n):
        return "PREPAGADA"
    if re.search(r"SEGUR|POLIZA|AXA|PREVISORA|ALLIANZ|MAPFRE|BOLIVAR|LIBERTY|SURAMERICANA|COMPANIA|ADMINISTRAD", n):
        return "POLIZA"
    return "EPS"


def separar_nombre(completo: Optional[str]) -> tuple[str, str]:
    """'Ana María Pérez Gómez' -> ('Ana María', 'Pérez Gómez'). Con tres palabras se toman dos apellidos."""
    palabras = (completo or "").split()
    if not palabras:
        return "SIN NOMBRE", "SIN APELLIDO"
    if len(palabras) == 1:
        return palabras[0], "SIN APELLIDO"
    if len(palabras) == 2:
        return palabras[0], palabras[1]
    return " ".join(palabras[:-2]), " ".join(palabras[-2:])


def _procedimientos(textos: list[str]) -> tuple[list[dict], int]:
    """Un procedimiento por cada parte separada con '+' o '/', con el código CUPS si el catálogo lo da claro."""
    procs, sin_codigo = [], 0
    for texto in textos:
        for parte in re.split(r"\s*[+/]\s*", texto or ""):
            parte = parte.strip(" .-")
            if len(parte) < 2:
                continue
            elegido, _ = catalogo.codigo_probable(parte)
            if elegido is None:
                sin_codigo += 1
                codigo = _pendiente(sin_codigo)
            elif any(p["codigo"] == elegido["codigo"] for p in procs):
                continue  # el mismo procedimiento repetido en dos líneas
            else:
                codigo = elegido["codigo"]
            procs.append({"codigo": codigo, "nombre": parte[:255], "es_principal": not procs})
    if not procs:
        procs, sin_codigo = [{"codigo": _pendiente(1), "nombre": "Procedimiento por confirmar", "es_principal": True}], 1
    return procs, sin_codigo


def _pendiente(n: int) -> str:
    """PENDIENTE1, PENDIENTE2…: una cirugía no puede repetir código."""
    return f"{CODIGO_PENDIENTE}{n}" if n < 10 else f"PEND{n}"


def crear_faltantes(conn, anestesiologo_id: int, reporte_id: int) -> dict:
    """Crea una cirugía por cada paciente del radicado que no se encontró en la app (varias líneas con la misma
    cédula son una sola cirugía). Quedan cruzadas con el radicado: facturadas si ya se aplicó y pagadas si ya
    se registró el pago."""
    rep = conn.execute(
        """SELECT reporte_id, pagador, fecha_proceso, tipo FROM reporte_pago
            WHERE reporte_id = %s AND anestesiologo_id = %s""", (reporte_id, anestesiologo_id)).fetchone()
    if rep is None or rep["tipo"] != "RADICADO":
        raise repositorio.DocumentoNoEncontrado()
    if rep["fecha_proceso"] is None:
        raise ValueError("El radicado no tiene fecha: no se puede saber de cuándo son las cirugías.")
    lineas = conn.execute(
        """SELECT documento_paciente, doc_norm(documento_paciente) AS doc, paciente, empresa, procedimiento
             FROM pago_detalle WHERE reporte_id = %s AND es_paciente AND cirugia_id IS NULL
              AND length(doc_norm(documento_paciente)) >= 3 ORDER BY detalle_id""", (reporte_id,)).fetchall()
    por_doc: dict[str, list[dict]] = {}
    for linea in lineas:
        por_doc.setdefault(linea["doc"], []).append(linea)
    clinica = (rep["pagador"] or "Clínica del radicado")[:150]
    creadas = sin_codigo = 0
    for doc, grupo in por_doc.items():
        # Si el paciente ya existe, se conservan sus nombres (los de la hoja a mano pueden venir mal leídos)
        existente = conn.execute(
            """SELECT tipo_documento, nombres, apellidos FROM paciente
                WHERE anestesiologo_id = %s AND doc_norm(numero_documento) = %s LIMIT 1""",
            (anestesiologo_id, doc)).fetchone()
        if existente:
            tipo_doc, nombres, apellidos = existente["tipo_documento"], existente["nombres"], existente["apellidos"]
        else:
            tipo_doc = "CC"
            nombres, apellidos = separar_nombre(grupo[0]["paciente"])
        entidad = next((g["empresa"] for g in grupo if g["empresa"]), None)
        procs, faltan = _procedimientos([g["procedimiento"] for g in grupo])
        sin_codigo += faltan
        orden = OrdenConfirmada.model_validate({
            "paciente": {"tipo_documento": tipo_doc, "numero_documento": doc[:20],
                         "nombres": nombres[:100], "apellidos": apellidos[:100]},
            "aseguradora": {"nombre": (entidad or ENTIDAD_POR_CONFIRMAR)[:150],
                            "tipo": tipo_entidad(entidad) if entidad else "EPS"},
            "clinica": {"nombre": clinica},
            "procedimientos": procs,
            "fecha_procedimiento": rep["fecha_proceso"],
            "estado": "REALIZADA",
            "observaciones": (f"Creada desde el radicado de {clinica} del {rep['fecha_proceso']:%d/%m/%Y}: la fecha es "
                              "la del radicado. Revisa la fecha, el nombre, la entidad, el código y el valor."),
        })
        repositorio.guardar_orden(conn, anestesiologo_id, orden)   # se cruza sola con el radicado
        creadas += 1
    return {"creadas": creadas, "procedimientos_sin_codigo": sin_codigo}
