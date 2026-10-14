"""Acceso a la base de datos.

Guardar una orden confirmada reutiliza los registros que ya existen
(paciente por documento, aseguradora por nombre y tipo, clínica por nombre y
ciudad) para no duplicar información cuando llega una nueva orden.
"""
import re
import unicodedata
from typing import Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app import config
from app.modelos import OrdenConfirmada, OrdenExtraida, ReportePagoExtraido


class DocumentoNoEncontrado(Exception):
    pass


class DocumentoYaValidado(Exception):
    def __init__(self, cirugia_id: Optional[int]):
        self.cirugia_id = cirugia_id


def conectar() -> psycopg.Connection:
    # prepare_threshold=None: sin sentencias preparadas, necesario con el pooler de Supabase
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row, prepare_threshold=None)


def _nombre_catalogo(nombre: str) -> str:
    """Las aseguradoras y clínicas se guardan en mayúsculas para que 'Sura' y 'SURA' sean la misma."""
    return " ".join(nombre.split()).upper()


def clave_nombre(nombre: Optional[str]) -> str:
    """Para comparar nombres sin importar tildes, mayúsculas ni puntuación: 'Clínica  del Caribe.' = 'CLINICA DEL CARIBE'."""
    t = unicodedata.normalize("NFKD", nombre or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).upper()
    return " ".join(re.sub(r"[^A-Z0-9]", " ", t).split())


# ------------------------------------------------------------ documentos
def buscar_documento_por_hash(conn, anestesiologo_id: int, hash_sha256: str) -> Optional[dict]:
    return conn.execute(
        "SELECT documento_id, estado FROM documento_fuente WHERE anestesiologo_id = %s AND hash_sha256 = %s",
        (anestesiologo_id, hash_sha256),
    ).fetchone()


def crear_documento(conn, anestesiologo_id: int, paginas: list[tuple[str, str]], hash_sha256: str) -> int:
    """paginas: [(ubicación, 'IMAGEN'|'PDF'), ...] en orden. La primera queda también en documento_fuente."""
    url, tipo = paginas[0]
    documento_id = conn.execute(
        """INSERT INTO documento_fuente (anestesiologo_id, tipo_archivo, url_archivo, hash_sha256)
           VALUES (%s, %s, %s, %s) RETURNING documento_id""",
        (anestesiologo_id, tipo, url, hash_sha256),
    ).fetchone()["documento_id"]
    for numero, (url, tipo) in enumerate(paginas, start=1):
        conn.execute(
            "INSERT INTO documento_pagina (documento_id, numero, url_archivo, tipo_archivo) VALUES (%s, %s, %s, %s)",
            (documento_id, numero, url, tipo),
        )
    return documento_id


def guardar_extraccion(conn, documento_id: int, orden: OrdenExtraida) -> None:
    conn.execute(
        """UPDATE documento_fuente
              SET estado = 'EXTRAIDO', datos_extraidos = %s, confianza = %s
            WHERE documento_id = %s""",
        (Jsonb(orden.model_dump(mode="json")), round(orden.confianza, 3), documento_id),
    )


def marcar_error(conn, documento_id: int, mensaje: str) -> None:
    conn.execute(
        """UPDATE documento_fuente SET estado = 'ERROR', datos_extraidos = %s
            WHERE documento_id = %s""",
        (Jsonb({"error": mensaje}), documento_id),
    )


def obtener_documento(conn, documento_id: int, anestesiologo_id: int) -> Optional[dict]:
    return conn.execute(
        """SELECT d.documento_id, d.tipo_archivo, d.estado, d.datos_extraidos, d.confianza, d.subido_en,
                  c.cirugia_id
             FROM documento_fuente d
             LEFT JOIN cirugia c ON c.documento_id = d.documento_id
            WHERE d.documento_id = %s AND d.anestesiologo_id = %s""",
        (documento_id, anestesiologo_id),
    ).fetchone()


# ------------------------------------------------------------ catálogos
def _upsert_paciente(conn, p) -> int:
    return conn.execute(
        """INSERT INTO paciente (tipo_documento, numero_documento, nombres, apellidos)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (tipo_documento, numero_documento)
           DO UPDATE SET nombres = EXCLUDED.nombres, apellidos = EXCLUDED.apellidos
           RETURNING paciente_id""",
        (p.tipo_documento, p.numero_documento, p.nombres, p.apellidos),
    ).fetchone()["paciente_id"]


def _upsert_aseguradora(conn, a) -> int:
    # La misma aseguradora escrita con o sin tildes o puntos ("S.A" / "S.A.") no se duplica
    clave = clave_nombre(a.nombre)
    for fila in conn.execute("SELECT aseguradora_id, nombre FROM aseguradora WHERE tipo = %s ORDER BY aseguradora_id",
                             (a.tipo,)):
        if clave_nombre(fila["nombre"]) == clave:
            return fila["aseguradora_id"]
    return conn.execute(
        """INSERT INTO aseguradora (nombre, tipo) VALUES (%s, %s)
           ON CONFLICT (nombre, tipo) DO UPDATE SET nombre = EXCLUDED.nombre
           RETURNING aseguradora_id""",
        (_nombre_catalogo(a.nombre), a.tipo),
    ).fetchone()["aseguradora_id"]


def _obtener_o_crear_cobertura(conn, paciente_id: int, aseguradora_id: int, a) -> int:
    # numero_poliza puede ser NULL, y en SQL dos NULL no chocan en un UNIQUE: se busca primero
    fila = conn.execute(
        """SELECT cobertura_id FROM cobertura
            WHERE paciente_id = %s AND aseguradora_id = %s AND numero_poliza IS NOT DISTINCT FROM %s""",
        (paciente_id, aseguradora_id, a.numero_poliza),
    ).fetchone()
    if fila:
        if a.plan:
            conn.execute("UPDATE cobertura SET plan = %s, activa = TRUE WHERE cobertura_id = %s",
                         (a.plan, fila["cobertura_id"]))
        return fila["cobertura_id"]
    return conn.execute(
        """INSERT INTO cobertura (paciente_id, aseguradora_id, numero_poliza, plan)
           VALUES (%s, %s, %s, %s) RETURNING cobertura_id""",
        (paciente_id, aseguradora_id, a.numero_poliza, a.plan),
    ).fetchone()["cobertura_id"]


# Palabras que traen casi todos los nombres de clínicas y no ayudan a distinguirlas
_GENERICAS = {"CLINICA", "IPS", "SAS", "SA", "S", "A", "LTDA", "ESE", "E", "ORGANIZACION", "DE", "DEL", "LA", "EL", "LAS", "LOS"}


def sin_genericas(clave: str) -> str:
    """'CLINICA DEL CARIBE S A S' -> 'CARIBE' (recibe un nombre ya pasado por clave_nombre)."""
    return " ".join(p for p in clave.split() if p not in _GENERICAS)


def cargar_clinicas_base(conn, filas: list[dict]) -> int:
    """Agrega las clínicas del listado base que aún no existan en su ciudad (sin importar tildes,
    mayúsculas, puntuación ni palabras como 'Clínica' o 'S.A.S.'). Devuelve cuántas agregó."""
    existentes = {(sin_genericas(clave_nombre(c["nombre"])), clave_nombre(c["ciudad"])) for c in listar_clinicas(conn)}
    nuevas = 0
    for f in filas:
        clave = (sin_genericas(clave_nombre(f["nombre"])), clave_nombre(f["ciudad"]))
        if clave in existentes:
            continue
        conn.execute("INSERT INTO clinica (nombre, ciudad) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                     (_nombre_catalogo(f["nombre"]), _nombre_catalogo(f["ciudad"])))
        existentes.add(clave)
        nuevas += 1
    return nuevas


def catalogos_para_sugerir(conn) -> dict:
    """Aseguradoras y cirujanos registrados, para sugerirlos al escribir (como las clínicas)."""
    return {
        "aseguradoras": conn.execute("SELECT aseguradora_id AS id, nombre, tipo FROM aseguradora ORDER BY nombre").fetchall(),
        "cirujanos": conn.execute("SELECT cirujano_id AS id, nombre FROM cirujano ORDER BY nombre").fetchall(),
    }


def listar_clinicas(conn) -> list[dict]:
    """Todas las clínicas registradas (son las mismas para todos los anestesiólogos)."""
    return conn.execute("SELECT clinica_id AS id, nombre, ciudad FROM clinica ORDER BY nombre, ciudad").fetchall()


def _obtener_o_crear_clinica(conn, c) -> int:
    nombre = _nombre_catalogo(c.nombre)
    ciudad = _nombre_catalogo(c.ciudad) if c.ciudad else None
    # La misma clínica escrita con o sin tildes ("CLÍNICA" / "CLINICA") no se duplica
    clave, clave_ciudad = clave_nombre(nombre), clave_nombre(ciudad)
    for fila in listar_clinicas(conn):
        if clave_nombre(fila["nombre"]) == clave and clave_nombre(fila["ciudad"]) == clave_ciudad:
            return fila["id"]
    return conn.execute(
        "INSERT INTO clinica (nombre, ciudad) VALUES (%s, %s) RETURNING clinica_id", (nombre, ciudad)
    ).fetchone()["clinica_id"]


# ------------------------------------------------------------ cirugía
def _nombre_cirujano(nombre: str) -> str:
    """'Dr. Juan  Pérez' -> 'JUAN PÉREZ' (sin título, para no duplicar al mismo cirujano)."""
    partes = _nombre_catalogo(nombre).split(" ")
    while partes and partes[0].rstrip(".") in ("DR", "DRA", "DOCTOR", "DOCTORA"):
        partes = partes[1:]
    return " ".join(partes)


def _obtener_o_crear_cirujano(conn, nombre: Optional[str]) -> Optional[int]:
    nombre = _nombre_cirujano(nombre) if nombre else ""
    if not nombre:
        return None
    clave = clave_nombre(nombre)  # "José Pérez" y "JOSE PEREZ" son el mismo cirujano
    for fila in conn.execute("SELECT cirujano_id, nombre FROM cirujano ORDER BY cirujano_id"):
        if clave_nombre(fila["nombre"]) == clave:
            return fila["cirujano_id"]
    return conn.execute(
        """INSERT INTO cirujano (nombre) VALUES (%s)
           ON CONFLICT (nombre) DO UPDATE SET nombre = EXCLUDED.nombre
           RETURNING cirujano_id""",
        (nombre,),
    ).fetchone()["cirujano_id"]


def _resolver_relaciones(conn, orden: OrdenConfirmada) -> dict:
    """Crea o reutiliza paciente, cobertura, clínica y cirujano de la orden."""
    paciente_id = _upsert_paciente(conn, orden.paciente)
    cobertura_id = None
    if orden.aseguradora:
        aseguradora_id = _upsert_aseguradora(conn, orden.aseguradora)
        cobertura_id = _obtener_o_crear_cobertura(conn, paciente_id, aseguradora_id, orden.aseguradora)
    return {
        "paciente_id": paciente_id,
        "cobertura_id": cobertura_id,
        "clinica_id": _obtener_o_crear_clinica(conn, orden.clinica),
        "cirujano_id": _obtener_o_crear_cirujano(conn, orden.cirujano),
    }


def _guardar_procedimientos(conn, cirugia_id: int, orden: OrdenConfirmada) -> None:
    conn.execute("DELETE FROM cirugia_procedimiento WHERE cirugia_id = %s", (cirugia_id,))
    for p in orden.procedimientos:
        # El catálogo conserva su nombre oficial si el código ya existe
        conn.execute(
            "INSERT INTO procedimiento (codigo, nombre) VALUES (%s, %s) ON CONFLICT (codigo) DO NOTHING",
            (p.codigo, p.nombre),
        )
        conn.execute(
            "INSERT INTO cirugia_procedimiento (cirugia_id, codigo, es_principal) VALUES (%s, %s, %s)",
            (cirugia_id, p.codigo, p.es_principal),
        )


def guardar_orden(conn, anestesiologo_id: int, orden: OrdenConfirmada, documento_id: Optional[int] = None) -> int:
    """Crea la cirugía con sus procedimientos. Debe ejecutarse dentro de una transacción."""
    if documento_id is not None:
        doc = conn.execute(
            """SELECT d.estado, c.cirugia_id FROM documento_fuente d
                 LEFT JOIN cirugia c ON c.documento_id = d.documento_id
                WHERE d.documento_id = %s AND d.anestesiologo_id = %s
                FOR UPDATE OF d""",
            (documento_id, anestesiologo_id),
        ).fetchone()
        if doc is None:
            raise DocumentoNoEncontrado()
        if doc["estado"] == "VALIDADO":
            raise DocumentoYaValidado(doc["cirugia_id"])

    r = _resolver_relaciones(conn, orden)
    cirugia_id = conn.execute(
        """INSERT INTO cirugia (paciente_id, cobertura_id, clinica_id, cirujano_id, anestesiologo_id,
                                documento_id, fecha_procedimiento, estado, valor_honorarios,
                                fecha_pago, observaciones, numero_orden)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING cirugia_id""",
        (r["paciente_id"], r["cobertura_id"], r["clinica_id"], r["cirujano_id"], anestesiologo_id,
         documento_id, orden.fecha_procedimiento, orden.estado, orden.valor_honorarios,
         orden.fecha_pago, orden.observaciones, orden.numero_orden),
    ).fetchone()["cirugia_id"]
    _guardar_procedimientos(conn, cirugia_id, orden)

    if documento_id is not None:
        conn.execute("UPDATE documento_fuente SET estado = 'VALIDADO' WHERE documento_id = %s", (documento_id,))
    cruzar_paciente(conn, anestesiologo_id, r["paciente_id"])
    return cirugia_id


def actualizar_orden(conn, anestesiologo_id: int, cirugia_id: int, orden: OrdenConfirmada) -> bool:
    """Corrige una cirugía existente. Devuelve False si no existe o es de otro anestesiólogo."""
    existe = conn.execute(
        "SELECT clinica_id FROM cirugia WHERE cirugia_id = %s AND anestesiologo_id = %s FOR UPDATE",
        (cirugia_id, anestesiologo_id),
    ).fetchone()
    if not existe:
        return False
    r = _resolver_relaciones(conn, orden)
    conn.execute(
        """UPDATE cirugia
              SET paciente_id = %s, cobertura_id = %s, clinica_id = %s, cirujano_id = %s,
                  fecha_procedimiento = %s, estado = %s, valor_honorarios = %s,
                  fecha_pago = %s, observaciones = %s, numero_orden = %s
            WHERE cirugia_id = %s""",
        (r["paciente_id"], r["cobertura_id"], r["clinica_id"], r["cirujano_id"],
         orden.fecha_procedimiento, orden.estado, orden.valor_honorarios,
         orden.fecha_pago, orden.observaciones, orden.numero_orden, cirugia_id),
    )
    _guardar_procedimientos(conn, cirugia_id, orden)
    cruzar_paciente(conn, anestesiologo_id, r["paciente_id"])
    if existe["clinica_id"] != r["clinica_id"]:
        # Si se corrigió el nombre de la clínica, el nombre viejo no queda suelto en las sugerencias
        conn.execute("""DELETE FROM clinica WHERE clinica_id = %s
                          AND NOT EXISTS (SELECT 1 FROM cirugia WHERE clinica_id = %s)""",
                     (existe["clinica_id"], existe["clinica_id"]))
    return True


def obtener_cirugia(conn, anestesiologo_id: int, cirugia_id: int) -> Optional[dict]:
    """Detalle completo, con la misma forma que el formulario de la página."""
    c = conn.execute(
        """SELECT c.cirugia_id, c.fecha_procedimiento, c.estado, c.valor_honorarios, c.fecha_pago,
                  c.observaciones, c.numero_orden, c.documento_id, d.tipo_archivo,
                  CASE WHEN d.documento_id IS NULL THEN 0
                       ELSE GREATEST((SELECT COUNT(*) FROM documento_pagina x WHERE x.documento_id = d.documento_id), 1)
                  END AS paginas,
                  p.tipo_documento, p.numero_documento, p.nombres, p.apellidos,
                  a.nombre AS aseguradora_nombre, a.tipo AS aseguradora_tipo,
                  cb.numero_poliza, cb.plan,
                  cl.nombre AS clinica_nombre, cl.ciudad AS clinica_ciudad,
                  ci.nombre AS cirujano
             FROM cirugia c
             JOIN paciente p   ON p.paciente_id = c.paciente_id
             JOIN clinica cl   ON cl.clinica_id = c.clinica_id
             LEFT JOIN cobertura cb  ON cb.cobertura_id = c.cobertura_id
             LEFT JOIN aseguradora a ON a.aseguradora_id = cb.aseguradora_id
             LEFT JOIN cirujano ci   ON ci.cirujano_id = c.cirujano_id
             LEFT JOIN documento_fuente d ON d.documento_id = c.documento_id
            WHERE c.cirugia_id = %s AND c.anestesiologo_id = %s""",
        (cirugia_id, anestesiologo_id),
    ).fetchone()
    if c is None:
        return None
    procedimientos = conn.execute(
        """SELECT cp.codigo, pr.nombre, cp.es_principal
             FROM cirugia_procedimiento cp JOIN procedimiento pr USING (codigo)
            WHERE cp.cirugia_id = %s ORDER BY cp.es_principal DESC, cp.codigo""",
        (cirugia_id,),
    ).fetchall()
    return {
        "cirugia_id": c["cirugia_id"],
        "documento_id": c["documento_id"],
        "tipo_archivo": c["tipo_archivo"],
        "paginas": c["paginas"],
        "paciente": {k: c[k] for k in ("tipo_documento", "numero_documento", "nombres", "apellidos")},
        "aseguradora": None if c["aseguradora_nombre"] is None else {
            "nombre": c["aseguradora_nombre"], "tipo": c["aseguradora_tipo"],
            "numero_poliza": c["numero_poliza"], "plan": c["plan"]},
        "clinica": {"nombre": c["clinica_nombre"], "ciudad": c["clinica_ciudad"]},
        "procedimientos": procedimientos,
        "fecha_procedimiento": c["fecha_procedimiento"],
        "cirujano": c["cirujano"],
        "estado": c["estado"],
        "valor_honorarios": c["valor_honorarios"],
        "fecha_pago": c["fecha_pago"],
        "observaciones": c["observaciones"],
        "numero_orden": c["numero_orden"],
    }


def _filtros(anestesiologo_id: int, f: dict) -> tuple[str, list]:
    """WHERE común para la lista, el Excel y los reportes."""
    condiciones, params = ["c.anestesiologo_id = %s"], [anestesiologo_id]
    if f.get("desde"):
        condiciones.append("c.fecha_procedimiento >= %s"); params.append(f["desde"])
    if f.get("hasta"):
        condiciones.append("c.fecha_procedimiento <= %s"); params.append(f["hasta"])
    if f.get("clinica_id"):
        condiciones.append("c.clinica_id = %s"); params.append(f["clinica_id"])
    if f.get("cirujano_id"):
        condiciones.append("c.cirujano_id = %s"); params.append(f["cirujano_id"])
    if f.get("aseguradora_id") == "PARTICULAR":
        condiciones.append("c.cobertura_id IS NULL")
    elif f.get("aseguradora_id"):
        condiciones.append("cb.aseguradora_id = %s"); params.append(int(f["aseguradora_id"]))
    if f.get("estado") == "PENDIENTE":  # aún sin pagar (ni pagada ni cancelada)
        condiciones.append("c.estado NOT IN ('PAGADA', 'CANCELADA')")
    elif f.get("estado"):
        condiciones.append("c.estado = %s"); params.append(f["estado"])
    if f.get("q"):
        condiciones.append("(p.nombres || ' ' || p.apellidos ILIKE %s OR p.numero_documento ILIKE %s)")
        params += [f"%{f['q']}%", f"%{f['q']}%"]
    return " AND ".join(condiciones), params


_DESDE = """
             FROM cirugia c
             JOIN paciente p   ON p.paciente_id = c.paciente_id
             JOIN clinica cl   ON cl.clinica_id = c.clinica_id
             LEFT JOIN cobertura cb  ON cb.cobertura_id = c.cobertura_id
             LEFT JOIN aseguradora a ON a.aseguradora_id = cb.aseguradora_id
             LEFT JOIN cirujano ci   ON ci.cirujano_id = c.cirujano_id"""


def listar_cirugias(conn, anestesiologo_id: int, limite: int = 50, filtros: Optional[dict] = None) -> list[dict]:
    where, params = _filtros(anestesiologo_id, filtros or {})
    return conn.execute(
        f"""SELECT c.cirugia_id, c.fecha_procedimiento, c.estado, c.valor_honorarios, c.fecha_pago,
                  c.documento_id, c.numero_orden,
                  p.tipo_documento, p.numero_documento, p.nombres || ' ' || p.apellidos AS paciente,
                  cl.nombre AS clinica,
                  COALESCE(a.nombre, 'PARTICULAR') AS aseguradora, a.tipo AS tipo_aseguradora,
                  cb.numero_poliza, ci.nombre AS cirujano,
                  (SELECT json_agg(json_build_object('codigo', pr.codigo, 'nombre', pr.nombre,
                                                     'es_principal', cp.es_principal)
                                   ORDER BY cp.es_principal DESC, pr.codigo)
                     FROM cirugia_procedimiento cp JOIN procedimiento pr USING (codigo)
                    WHERE cp.cirugia_id = c.cirugia_id) AS procedimientos
            {_DESDE}
            WHERE {where}
            ORDER BY c.fecha_procedimiento DESC, c.cirugia_id DESC
            LIMIT %s""",
        params + [limite],
    ).fetchall()


def relacion_ordenes(conn, anestesiologo_id: int, tipos: list[str], aseguradoras: list[str],
                     clinicas: list[int], desde=None, hasta=None, estado: Optional[str] = None,
                     ids: Optional[list[int]] = None) -> list[dict]:
    """Relación de órdenes para entregar a facturación: una fila por cirugía con entidad, paciente,
    cédula, procedimiento, nº de orden y valor. Los filtros de listas son de selección múltiple
    (vacío = todos). Las canceladas nunca entran."""
    condiciones, params = ["c.anestesiologo_id = %s", "c.estado <> 'CANCELADA'"], [anestesiologo_id]
    if tipos:
        partes = []
        if "PARTICULAR" in tipos:
            partes.append("c.cobertura_id IS NULL")
        if [t for t in tipos if t != "PARTICULAR"]:
            partes.append("a.tipo = ANY(%s)"); params.append([t for t in tipos if t != "PARTICULAR"])
        condiciones.append("(" + " OR ".join(partes) + ")")
    if aseguradoras:
        partes = ["c.cobertura_id IS NULL"] if "PARTICULAR" in aseguradoras else []
        numeros = [int(x) for x in aseguradoras if x != "PARTICULAR"]
        if numeros:
            partes.append("cb.aseguradora_id = ANY(%s)"); params.append(numeros)
        condiciones.append("(" + " OR ".join(partes) + ")")
    if clinicas:
        condiciones.append("c.clinica_id = ANY(%s)"); params.append(clinicas)
    if desde:
        condiciones.append("c.fecha_procedimiento >= %s"); params.append(desde)
    if hasta:
        condiciones.append("c.fecha_procedimiento <= %s"); params.append(hasta)
    if estado == "PENDIENTE":
        condiciones.append("c.estado <> 'PAGADA'")
    elif estado:
        condiciones.append("c.estado = %s"); params.append(estado)
    if ids is not None:
        condiciones.append("c.cirugia_id = ANY(%s)"); params.append(ids)
    return conn.execute(
        f"""SELECT c.cirugia_id, c.fecha_procedimiento, c.estado, c.numero_orden, c.valor_honorarios AS valor,
                  COALESCE(a.nombre, 'PARTICULAR') AS entidad, a.tipo AS tipo_aseguradora,
                  p.nombres || ' ' || p.apellidos AS paciente, p.numero_documento AS cedula,
                  cl.nombre AS clinica,
                  (SELECT string_agg(pr.nombre, ' + ' ORDER BY cp.es_principal DESC, pr.codigo)
                     FROM cirugia_procedimiento cp JOIN procedimiento pr USING (codigo)
                    WHERE cp.cirugia_id = c.cirugia_id) AS procedimiento
            {_DESDE}
            WHERE {" AND ".join(condiciones)}
            ORDER BY c.fecha_procedimiento, c.cirugia_id""",
        params,
    ).fetchall()


def opciones_filtro(conn, anestesiologo_id: int) -> dict:
    """Clínicas, aseguradoras y cirujanos con los que ha trabajado el anestesiólogo."""
    def lista(sql):
        return conn.execute(sql, (anestesiologo_id,)).fetchall()
    return {
        "clinicas": lista("""SELECT DISTINCT cl.clinica_id AS id, cl.nombre FROM cirugia c
                               JOIN clinica cl USING (clinica_id) WHERE c.anestesiologo_id = %s ORDER BY 2"""),
        "aseguradoras": lista("""SELECT DISTINCT a.aseguradora_id AS id, a.nombre, a.tipo FROM cirugia c
                                   JOIN cobertura cb USING (cobertura_id) JOIN aseguradora a USING (aseguradora_id)
                                  WHERE c.anestesiologo_id = %s ORDER BY 2"""),
        "cirujanos": lista("""SELECT DISTINCT ci.cirujano_id AS id, ci.nombre FROM cirugia c
                                JOIN cirujano ci USING (cirujano_id) WHERE c.anestesiologo_id = %s ORDER BY 2"""),
    }


def reporte(conn, anestesiologo_id: int, filtros: Optional[dict] = None) -> dict:
    """Totales del periodo y agrupaciones por cirujano, clínica, aseguradora y mes.
    Las cirugías canceladas no suman en los totales; se cuentan aparte."""
    where, params = _filtros(anestesiologo_id, filtros or {})
    metricas = """COUNT(*) FILTER (WHERE c.estado <> 'CANCELADA') AS cirugias,
                  COALESCE(SUM(c.valor_honorarios) FILTER (WHERE c.estado <> 'CANCELADA'), 0) AS total,
                  COALESCE(SUM(c.valor_honorarios) FILTER (WHERE c.estado = 'PAGADA'), 0) AS pagado,
                  COALESCE(SUM(c.valor_honorarios) FILTER (WHERE c.estado NOT IN ('PAGADA','CANCELADA')), 0) AS por_cobrar,
                  COUNT(*) FILTER (WHERE c.estado <> 'CANCELADA' AND c.valor_honorarios IS NULL) AS sin_valor"""

    def agrupar(etiqueta: str, orden: str = "total DESC, cirugias DESC"):
        return conn.execute(
            f"""SELECT {etiqueta} AS nombre, {metricas}
                {_DESDE} WHERE {where}
                GROUP BY 1 HAVING COUNT(*) FILTER (WHERE c.estado <> 'CANCELADA') > 0
                ORDER BY {orden}""", params).fetchall()

    totales = conn.execute(
        f"""SELECT {metricas}, COUNT(*) FILTER (WHERE c.estado = 'CANCELADA') AS canceladas,
                  COUNT(*) FILTER (WHERE c.estado NOT IN ('PAGADA', 'CANCELADA')) AS pendientes
            {_DESDE} WHERE {where}""", params).fetchone()
    registradas = conn.execute("SELECT COUNT(*) AS n FROM cirugia WHERE anestesiologo_id = %s",
                               (anestesiologo_id,)).fetchone()["n"]
    return {
        "totales": totales,
        "registradas": registradas,  # todas las del anestesiólogo, sin filtro de periodo
        "por_cirujano": agrupar("COALESCE(ci.nombre, 'SIN CIRUJANO')"),
        "por_clinica": agrupar("cl.nombre"),
        "por_aseguradora": agrupar("COALESCE(a.nombre, 'PARTICULAR')"),
        "por_mes": agrupar("to_char(c.fecha_procedimiento, 'YYYY-MM')", "nombre DESC"),
    }


def obtener_archivo(conn, documento_id: int, anestesiologo_id: int, pagina: int = 1) -> Optional[dict]:
    """Ubicación de una página del documento. Los documentos anteriores a las páginas
    tienen un solo archivo, guardado en documento_fuente."""
    return conn.execute(
        """SELECT COALESCE(p.url_archivo, d.url_archivo) AS url_archivo
             FROM documento_fuente d
             LEFT JOIN documento_pagina p ON p.documento_id = d.documento_id AND p.numero = %(pag)s
            WHERE d.documento_id = %(doc)s AND d.anestesiologo_id = %(anest)s
              AND (p.numero IS NOT NULL OR (%(pag)s = 1 AND NOT EXISTS (
                     SELECT 1 FROM documento_pagina x WHERE x.documento_id = d.documento_id)))""",
        {"doc": documento_id, "anest": anestesiologo_id, "pag": pagina},
    ).fetchone()


def ciudad_conocida(conn, anestesiologo_id: int, clinica: str) -> Optional[str]:
    """Ciudad con la que el anestesiólogo ya registró esa clínica (la más reciente)."""
    fila = conn.execute(
        """SELECT cl.ciudad FROM cirugia c JOIN clinica cl USING (clinica_id)
            WHERE c.anestesiologo_id = %s AND cl.nombre = %s AND cl.ciudad IS NOT NULL
            ORDER BY c.fecha_procedimiento DESC, c.cirugia_id DESC LIMIT 1""",
        (anestesiologo_id, _nombre_catalogo(clinica)),
    ).fetchone()
    return fila["ciudad"] if fila else None


_CUENTA = """anestesiologo_id, nombre, email, password_hash, es_admin, activo, debe_cambiar_clave,
             version_sesion"""


def obtener_cuenta(conn, anestesiologo_id: int) -> Optional[dict]:
    return conn.execute(f"SELECT {_CUENTA} FROM anestesiologo WHERE anestesiologo_id = %s",
                        (anestesiologo_id,)).fetchone()


def buscar_anestesiologo_por_email(conn, email: str) -> Optional[dict]:
    return conn.execute(f"SELECT {_CUENTA} FROM anestesiologo WHERE email = %s",
                        (email.strip().lower(),)).fetchone()


def cambiar_clave(conn, anestesiologo_id: int, password_hash: str, temporal: bool) -> int:
    """Guarda la clave nueva y cierra las sesiones abiertas. Devuelve la nueva versión de sesión."""
    return conn.execute(
        """UPDATE anestesiologo SET password_hash = %s, debe_cambiar_clave = %s,
                  version_sesion = version_sesion + 1
            WHERE anestesiologo_id = %s RETURNING version_sesion""",
        (password_hash, temporal, anestesiologo_id),
    ).fetchone()["version_sesion"]


# ------------------------------------------------------------ administración de cuentas
def listar_usuarios(conn) -> list[dict]:
    return conn.execute(
        """SELECT a.anestesiologo_id, a.nombre, a.email, a.registro_medico, a.es_admin, a.activo,
                  a.debe_cambiar_clave, a.creado_en,
                  (SELECT COUNT(*) FROM cirugia c WHERE c.anestesiologo_id = a.anestesiologo_id) AS cirugias
             FROM anestesiologo a ORDER BY a.activo DESC, a.nombre"""
    ).fetchall()


class EmailYaRegistrado(Exception):
    pass


def crear_usuario(conn, nombre: str, email: str, registro_medico: Optional[str], password_hash: str) -> int:
    try:
        with conn.transaction():
            return conn.execute(
                """INSERT INTO anestesiologo (nombre, email, registro_medico, password_hash, debe_cambiar_clave)
                   VALUES (%s, %s, %s, %s, TRUE) RETURNING anestesiologo_id""",
                (nombre, email.strip().lower(), registro_medico, password_hash),
            ).fetchone()["anestesiologo_id"]
    except psycopg.errors.UniqueViolation as e:
        raise EmailYaRegistrado() from e


def cambiar_activo(conn, anestesiologo_id: int, activo: bool) -> bool:
    return conn.execute(
        """UPDATE anestesiologo SET activo = %s, version_sesion = version_sesion + 1
            WHERE anestesiologo_id = %s""",
        (activo, anestesiologo_id),
    ).rowcount == 1


# ------------------------------------------------------------ reportes de pago
# La fecha de servicio del reporte puede ser muy posterior a la cirugía (radicación): algunas clínicas pagan
# 215 días después de radicado. Se busca la cirugía del paciente hasta DIAS_ANTES antes de esa fecha (o hasta
# DIAS_DESPUES después) y nunca posterior al pago; si hay varias, la más cercana.
DIAS_ANTES, DIAS_DESPUES = 300, 30


def buscar_reporte_por_hash(conn, anestesiologo_id: int, hash_sha256: str) -> Optional[dict]:
    return conn.execute(
        "SELECT reporte_id FROM reporte_pago WHERE anestesiologo_id = %s AND hash_sha256 = %s",
        (anestesiologo_id, hash_sha256),
    ).fetchone()


def crear_reporte(conn, anestesiologo_id: int, url_archivo: str, hash_sha256: str,
                  reporte: ReportePagoExtraido) -> int:
    reporte_id = conn.execute(
        """INSERT INTO reporte_pago (anestesiologo_id, pagador, fecha_proceso, periodo_desde, periodo_hasta,
                                     total_neto, url_archivo, hash_sha256, datos_extraidos)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING reporte_id""",
        (anestesiologo_id, reporte.pagador, reporte.fecha_proceso, reporte.periodo_desde, reporte.periodo_hasta,
         reporte.total_neto, url_archivo, hash_sha256, Jsonb(reporte.model_dump(mode="json"))),
    ).fetchone()["reporte_id"]
    for f in reporte.filas:
        conn.execute(
            """INSERT INTO pago_detalle (reporte_id, empresa, documento_paciente, paciente, fecha_servicio,
                                         factura, autorizacion, total, glosas, descuentos, neto, es_paciente)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (reporte_id, f.empresa, f.documento_paciente, f.paciente, f.fecha_servicio, f.factura,
             f.autorizacion, f.total, f.glosas, f.descuentos, f.neto, f.es_paciente),
        )
    conciliar(conn, anestesiologo_id, reporte_id)
    return reporte_id


def conciliar(conn, anestesiologo_id: int, reporte_id: int) -> None:
    """Busca la cirugía de cada línea: mismo documento del paciente y la fecha más cercana dentro de la
    ventana (DIAS_ANTES / DIAS_DESPUES), sin pasar de la fecha del pago. Una cirugía no se asigna a dos líneas."""
    pago = conn.execute("SELECT fecha_proceso FROM reporte_pago WHERE reporte_id = %s", (reporte_id,)).fetchone()
    filas = conn.execute(
        """SELECT d.detalle_id, d.documento_paciente, d.fecha_servicio, d.cirugia_id, c.estado
             FROM pago_detalle d LEFT JOIN cirugia c ON c.cirugia_id = d.cirugia_id
            WHERE d.reporte_id = %s AND d.es_paciente AND d.documento_paciente IS NOT NULL
            ORDER BY d.detalle_id""",
        (reporte_id,),
    ).fetchall()
    # Las líneas cuya cirugía ya quedó pagada no se vuelven a cruzar (al repetir el cruce)
    usadas: set[int] = {f["cirugia_id"] for f in filas if f["estado"] == "PAGADA"}
    for f in filas:
        if f["estado"] == "PAGADA":
            continue
        candidatas = conn.execute(
            """SELECT c.cirugia_id,
                      CASE WHEN %(fecha)s::date IS NULL THEN 0
                           ELSE abs(c.fecha_procedimiento - %(fecha)s::date) END AS distancia
                 FROM cirugia c JOIN paciente p ON p.paciente_id = c.paciente_id
                WHERE c.anestesiologo_id = %(anest)s AND c.estado <> 'CANCELADA'
                  AND doc_norm(p.numero_documento) = doc_norm(%(doc)s)
                  AND (%(fecha)s::date IS NULL
                       OR c.fecha_procedimiento BETWEEN %(fecha)s::date - %(antes)s AND %(fecha)s::date + %(despues)s)
                  AND (%(pago)s::date IS NULL OR c.fecha_procedimiento <= %(pago)s::date)
                  -- no tomar cirugías ya pagadas por otro reporte aplicado
                  AND NOT EXISTS (SELECT 1 FROM pago_detalle d JOIN reporte_pago r USING (reporte_id)
                                   WHERE d.cirugia_id = c.cirugia_id AND r.estado = 'APLICADO'
                                     AND r.reporte_id <> %(rep)s)
                ORDER BY distancia, c.fecha_procedimiento DESC""",
            {"fecha": f["fecha_servicio"], "anest": anestesiologo_id, "doc": f["documento_paciente"],
             "antes": DIAS_ANTES, "despues": DIAS_DESPUES, "pago": pago["fecha_proceso"] if pago else None,
             "rep": reporte_id},
        ).fetchall()
        elegida = next((c["cirugia_id"] for c in candidatas if c["cirugia_id"] not in usadas), None)
        if elegida:
            usadas.add(elegida)
        conn.execute("UPDATE pago_detalle SET cirugia_id = %s WHERE detalle_id = %s", (elegida, f["detalle_id"]))


def cruzar_paciente(conn, anestesiologo_id: int, paciente_id: int) -> int:
    """Al registrar o corregir una cirugía, la busca en los reportes de pago ya subidos (los pagos suelen
    llegar antes de que se registre la cirugía). En un reporte ya aplicado, la marca pagada de una vez."""
    reportes = conn.execute(
        """SELECT DISTINCT r.reporte_id, r.estado FROM pago_detalle d
             JOIN reporte_pago r USING (reporte_id) JOIN paciente p ON p.paciente_id = %s
            WHERE r.anestesiologo_id = %s AND d.es_paciente AND d.cirugia_id IS NULL
              AND doc_norm(d.documento_paciente) = doc_norm(p.numero_documento)""",
        (paciente_id, anestesiologo_id)).fetchall()
    marcadas = 0
    for r in reportes:
        conciliar(conn, anestesiologo_id, r["reporte_id"])
        if r["estado"] == "APLICADO":
            marcadas += aplicar_reporte(conn, anestesiologo_id, r["reporte_id"])
    return marcadas


def recruzar_todos(conn, anestesiologo_id: int) -> dict:
    """Vuelve a cruzar todos los reportes del anestesiólogo. En los ya aplicados marca pagadas las nuevas."""
    reportes = conn.execute("SELECT reporte_id, estado FROM reporte_pago WHERE anestesiologo_id = %s ORDER BY reporte_id",
                            (anestesiologo_id,)).fetchall()
    contar = """SELECT count(*) AS n FROM pago_detalle d JOIN reporte_pago r USING (reporte_id)
                 WHERE r.anestesiologo_id = %s AND d.cirugia_id IS NOT NULL"""
    antes = conn.execute(contar, (anestesiologo_id,)).fetchone()["n"]
    marcadas = 0
    for r in reportes:
        conciliar(conn, anestesiologo_id, r["reporte_id"])
        if r["estado"] == "APLICADO":
            marcadas += aplicar_reporte(conn, anestesiologo_id, r["reporte_id"])
    despues = conn.execute(contar, (anestesiologo_id,)).fetchone()["n"]
    lineas = conn.execute("""SELECT count(*) AS n FROM pago_detalle d JOIN reporte_pago r USING (reporte_id)
                              WHERE r.anestesiologo_id = %s AND d.es_paciente""", (anestesiologo_id,)).fetchone()["n"]
    return {"reportes": len(reportes), "lineas": lineas, "encontradas": despues,
            "nuevas": despues - antes, "marcadas_pagadas": marcadas}


def obtener_reporte(conn, anestesiologo_id: int, reporte_id: int) -> Optional[dict]:
    cab = conn.execute(
        """SELECT reporte_id, pagador, fecha_proceso, periodo_desde, periodo_hasta, total_neto, estado,
                  subido_en, datos_extraidos->>'prestador' AS prestador
             FROM reporte_pago WHERE reporte_id = %s AND anestesiologo_id = %s""",
        (reporte_id, anestesiologo_id),
    ).fetchone()
    if cab is None:
        return None
    filas = conn.execute(
        """SELECT d.detalle_id, d.empresa, d.documento_paciente, d.paciente, d.fecha_servicio, d.factura,
                  d.autorizacion, d.total, d.glosas, d.descuentos, d.neto, d.es_paciente, d.cirugia_id,
                  c.fecha_procedimiento, c.estado AS estado_cirugia,
                  p.nombres || ' ' || p.apellidos AS paciente_app,
                  CASE WHEN NOT d.es_paciente THEN 'OTRO_CONCEPTO'
                       WHEN d.cirugia_id IS NULL THEN 'SIN_CIRUGIA'
                       WHEN c.estado = 'PAGADA' AND %s <> 'APLICADO' THEN 'YA_PAGADA'
                       ELSE 'COINCIDE' END AS resultado
             FROM pago_detalle d
             LEFT JOIN cirugia c  ON c.cirugia_id = d.cirugia_id
             LEFT JOIN paciente p ON p.paciente_id = c.paciente_id
            WHERE d.reporte_id = %s ORDER BY d.detalle_id""",
        (cab["estado"], reporte_id),
    ).fetchall()
    suma = sum((f["neto"] or 0) for f in filas)
    return {**cab, "suma_neto": suma,
            "cuadra": None if cab["total_neto"] is None else abs(suma - cab["total_neto"]) <= 1,
            "filas": filas}


def aplicar_reporte(conn, anestesiologo_id: int, reporte_id: int) -> int:
    """Marca como PAGADAS las cirugías encontradas, con el neto y la fecha del reporte.
    Las que ya estaban pagadas no se tocan, así que se puede repetir tras volver a cruzar
    (por ejemplo, después de registrar un paciente que faltaba). Devuelve cuántas se marcaron."""
    rep = conn.execute(
        "SELECT estado, fecha_proceso FROM reporte_pago WHERE reporte_id = %s AND anestesiologo_id = %s FOR UPDATE",
        (reporte_id, anestesiologo_id),
    ).fetchone()
    if rep is None:
        raise DocumentoNoEncontrado()
    marcadas = conn.execute(
        """UPDATE cirugia c
              SET estado = 'PAGADA', valor_honorarios = d.neto,
                  fecha_pago = COALESCE(%s, CURRENT_DATE)
             FROM pago_detalle d
            WHERE d.reporte_id = %s AND d.cirugia_id = c.cirugia_id
              AND c.anestesiologo_id = %s AND c.estado NOT IN ('PAGADA', 'CANCELADA')""",
        (rep["fecha_proceso"], reporte_id, anestesiologo_id),
    ).rowcount
    conn.execute("UPDATE reporte_pago SET estado = 'APLICADO' WHERE reporte_id = %s", (reporte_id,))
    return marcadas


def listar_reportes(conn, anestesiologo_id: int) -> list[dict]:
    return conn.execute(
        """SELECT r.reporte_id, r.pagador, r.fecha_proceso, r.periodo_desde, r.periodo_hasta, r.total_neto,
                  r.estado, r.subido_en,
                  COUNT(d.*) FILTER (WHERE d.es_paciente) AS lineas,
                  COUNT(d.*) FILTER (WHERE d.cirugia_id IS NOT NULL) AS encontradas
             FROM reporte_pago r LEFT JOIN pago_detalle d USING (reporte_id)
            WHERE r.anestesiologo_id = %s
            GROUP BY r.reporte_id ORDER BY r.subido_en DESC""",
        (anestesiologo_id,),
    ).fetchall()


def reporte_glosas(conn, anestesiologo_id: int, desde=None, hasta=None) -> dict:
    """Glosas y descuentos de los reportes de pago, por empresa y línea a línea.
    El periodo se toma por la fecha del servicio (la de la cirugía)."""
    where = ["r.anestesiologo_id = %s", "(d.glosas > 0 OR d.descuentos > 0)"]
    params: list = [anestesiologo_id]
    if desde:
        where.append("d.fecha_servicio >= %s"); params.append(desde)
    if hasta:
        where.append("d.fecha_servicio <= %s"); params.append(hasta)
    desde_sql = f"FROM pago_detalle d JOIN reporte_pago r USING (reporte_id) WHERE {' AND '.join(where)}"
    totales = conn.execute(
        f"""SELECT COALESCE(SUM(d.glosas), 0) AS glosas, COALESCE(SUM(d.descuentos), 0) AS descuentos,
                  COALESCE(SUM(d.total), 0) AS facturado, COUNT(*) AS lineas {desde_sql}""", params).fetchone()
    por_empresa = conn.execute(
        f"""SELECT COALESCE(d.empresa, 'SIN EMPRESA') AS nombre, COUNT(*) AS lineas,
                  SUM(d.glosas) AS glosas, SUM(d.descuentos) AS descuentos, SUM(d.total) AS facturado
             {desde_sql} GROUP BY 1 ORDER BY SUM(d.glosas) + SUM(d.descuentos) DESC""", params).fetchall()
    lineas = conn.execute(
        f"""SELECT d.empresa, d.documento_paciente, d.paciente, d.fecha_servicio, d.factura, d.autorizacion,
                  d.total, d.glosas, d.descuentos, d.neto, r.fecha_proceso, r.pagador
             {desde_sql} ORDER BY d.fecha_servicio DESC NULLS LAST, d.detalle_id""", params).fetchall()
    return {"totales": totales, "por_empresa": por_empresa, "lineas": lineas}
