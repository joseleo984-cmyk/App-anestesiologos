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
    # antes de crear, se vuelve a cruzar: una cirugía que ya existe (aunque esté pagada) no se crea otra vez
    repositorio.conciliar(conn, anestesiologo_id, reporte_id)
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
                              "la del radicado. Revisar la fecha, el nombre, la entidad, el código y el valor."),
        })
        repositorio.guardar_orden(conn, anestesiologo_id, orden)   # se cruza sola con el radicado
        creadas += 1
    return {"creadas": creadas, "procedimientos_sin_codigo": sin_codigo}


# ---------------------------------------------------------------- líneas que no se encontraron
def _linea(conn, anestesiologo_id: int, detalle_id: int) -> dict:
    linea = conn.execute(
        """SELECT d.detalle_id, d.reporte_id, d.documento_paciente, doc_norm(d.documento_paciente) AS doc, d.paciente,
                  d.fecha_servicio, d.cirugia_id, d.es_paciente, r.fecha_proceso, r.estado
             FROM pago_detalle d JOIN reporte_pago r USING (reporte_id)
            WHERE d.detalle_id = %s AND r.anestesiologo_id = %s""", (detalle_id, anestesiologo_id)).fetchone()
    if linea is None or not linea["es_paciente"]:
        raise repositorio.DocumentoNoEncontrado()
    return linea


def candidatas(conn, anestesiologo_id: int, detalle_id: int, maximo: int = 5) -> list[dict]:
    """Cirugías que pueden ser las de una línea que no se encontró por cédula: el paciente quedó guardado con la
    cédula mal escrita (o la hoja se leyó mal). Se buscan por nombre parecido o por cédula que difiere en uno o
    dos dígitos, dentro de la misma ventana de fechas del cruce."""
    from rapidfuzz import fuzz
    from rapidfuzz.distance import Levenshtein
    linea = _linea(conn, anestesiologo_id, detalle_id)
    fecha = linea["fecha_servicio"] or linea["fecha_proceso"]
    filas = conn.execute(
        """SELECT c.cirugia_id, c.fecha_procedimiento, c.estado, p.tipo_documento, p.numero_documento,
                  doc_norm(p.numero_documento) AS doc, p.nombres || ' ' || p.apellidos AS paciente, cl.nombre AS clinica
             FROM cirugia c JOIN paciente p ON p.paciente_id = c.paciente_id JOIN clinica cl ON cl.clinica_id = c.clinica_id
            WHERE c.anestesiologo_id = %(anest)s AND c.estado <> 'CANCELADA'
              AND (%(fecha)s::date IS NULL OR c.fecha_procedimiento
                   BETWEEN %(fecha)s::date - %(antes)s AND %(fecha)s::date + %(despues)s)
              -- ni las que ya tiene otra línea de este reporte
              AND NOT EXISTS (SELECT 1 FROM pago_detalle d WHERE d.reporte_id = %(rep)s AND d.cirugia_id = c.cirugia_id)""",
        {"anest": anestesiologo_id, "fecha": fecha, "antes": repositorio.DIAS_ANTES, "despues": repositorio.DIAS_DESPUES,
         "rep": linea["reporte_id"]}).fetchall()
    nombre = catalogo.normalizar(linea["paciente"] or "")
    elegidas = []
    for f in filas:
        parecido = fuzz.token_set_ratio(nombre, catalogo.normalizar(f["paciente"])) if nombre else 0
        cerca = (len(linea["doc"] or "") >= 5 and f["doc"] != linea["doc"]
                 and Levenshtein.distance(linea["doc"], f["doc"]) <= 2)
        if parecido >= 75 or cerca:
            dias = abs((f["fecha_procedimiento"] - fecha).days) if fecha else 0
            elegidas.append({**f, "parecido": round(parecido), "cedula_parecida": cerca, "_orden": (-(parecido + 30 * cerca), dias)})
    elegidas.sort(key=lambda f: f["_orden"])
    return [{k: v for k, v in f.items() if k != "_orden"} for f in elegidas[:maximo]]


def vincular(conn, anestesiologo_id: int, detalle_id: int, cirugia_id: int, cedula_correcta: str) -> None:
    """Une la línea con la cirugía elegida y deja la misma cédula en los dos lados, para que el cruce la
    encuentre siempre (también en reportes futuros):
    - 'radicado': la cédula de la hoja es la buena; se corrige el paciente en la app (todas sus cirugías).
    - 'app': la de la app es la buena (la hoja se leyó o escribió mal); se corrige la línea."""
    linea = _linea(conn, anestesiologo_id, detalle_id)
    cirugia = repositorio.obtener_cirugia(conn, anestesiologo_id, cirugia_id)
    if cirugia is None:
        raise repositorio.DocumentoNoEncontrado()
    if cedula_correcta == "radicado":
        if not linea["doc"] or len(linea["doc"]) < 3:
            raise ValueError("La línea no trae una cédula para copiar al paciente.")
        nueva = linea["doc"][:20]
        pac = conn.execute(
            """SELECT p.paciente_id, (SELECT o.paciente_id FROM paciente o
                                        WHERE o.anestesiologo_id = p.anestesiologo_id AND o.tipo_documento = p.tipo_documento
                                          AND o.numero_documento = %s AND o.paciente_id <> p.paciente_id) AS otro
                 FROM cirugia c JOIN paciente p ON p.paciente_id = c.paciente_id WHERE c.cirugia_id = %s""",
            (nueva, cirugia_id)).fetchone()
        if pac["otro"] is None:
            # se corrige la ficha del paciente: todas sus cirugías quedan con la cédula buena
            conn.execute("UPDATE paciente SET numero_documento = %s WHERE paciente_id = %s", (nueva, pac["paciente_id"]))
            repositorio.cruzar_paciente(conn, anestesiologo_id, pac["paciente_id"])
        else:
            # ya hay una ficha con esa cédula: la cirugía pasa a esa ficha
            cirugia["paciente"]["numero_documento"] = nueva
            repositorio.actualizar_orden(conn, anestesiologo_id, cirugia_id, OrdenConfirmada.model_validate(cirugia))
    else:
        # todas las líneas del reporte con la misma cédula mal escrita son del mismo paciente
        conn.execute(
            """UPDATE pago_detalle SET documento_paciente = %s
                WHERE reporte_id = %s AND (detalle_id = %s OR doc_norm(documento_paciente) = %s)""",
            (cirugia["paciente"]["numero_documento"], linea["reporte_id"], detalle_id, linea["doc"] or ""))
    repositorio.conciliar(conn, anestesiologo_id, linea["reporte_id"])
    # el cruce elige por fecha entre las cirugías del paciente: se respeta la que eligió el anestesiólogo
    ocupada = conn.execute("SELECT 1 FROM pago_detalle WHERE reporte_id = %s AND cirugia_id = %s AND detalle_id <> %s",
                           (linea["reporte_id"], cirugia_id, detalle_id)).fetchone()
    if not ocupada:
        conn.execute("UPDATE pago_detalle SET cirugia_id = %s WHERE detalle_id = %s", (cirugia_id, detalle_id))
    if linea["estado"] in ("APLICADO", "PAGADO"):
        repositorio.aplicar_reporte(conn, anestesiologo_id, linea["reporte_id"])
