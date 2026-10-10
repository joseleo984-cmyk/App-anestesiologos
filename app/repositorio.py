"""Acceso a la base de datos.

Guardar una orden confirmada reutiliza los registros que ya existen
(paciente por documento, aseguradora por nombre y tipo, clínica por nombre y
ciudad) para no duplicar información cuando llega una nueva orden.
"""
from typing import Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app import config
from app.modelos import OrdenConfirmada, OrdenExtraida


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


# ------------------------------------------------------------ documentos
def buscar_documento_por_hash(conn, hash_sha256: str) -> Optional[dict]:
    return conn.execute(
        "SELECT documento_id, estado FROM documento_fuente WHERE hash_sha256 = %s", (hash_sha256,)
    ).fetchone()


def crear_documento(conn, anestesiologo_id: int, tipo_archivo: str, url_archivo: str, hash_sha256: str) -> int:
    fila = conn.execute(
        """INSERT INTO documento_fuente (anestesiologo_id, tipo_archivo, url_archivo, hash_sha256)
           VALUES (%s, %s, %s, %s) RETURNING documento_id""",
        (anestesiologo_id, tipo_archivo, url_archivo, hash_sha256),
    ).fetchone()
    return fila["documento_id"]


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


def _obtener_o_crear_clinica(conn, c) -> int:
    nombre = _nombre_catalogo(c.nombre)
    ciudad = _nombre_catalogo(c.ciudad) if c.ciudad else None
    fila = conn.execute(
        "SELECT clinica_id FROM clinica WHERE nombre = %s AND ciudad IS NOT DISTINCT FROM %s",
        (nombre, ciudad),
    ).fetchone()
    if fila:
        return fila["clinica_id"]
    return conn.execute(
        "INSERT INTO clinica (nombre, ciudad) VALUES (%s, %s) RETURNING clinica_id", (nombre, ciudad)
    ).fetchone()["clinica_id"]


# ------------------------------------------------------------ cirugía
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

    paciente_id = _upsert_paciente(conn, orden.paciente)
    cobertura_id = None
    if orden.aseguradora:
        aseguradora_id = _upsert_aseguradora(conn, orden.aseguradora)
        cobertura_id = _obtener_o_crear_cobertura(conn, paciente_id, aseguradora_id, orden.aseguradora)
    clinica_id = _obtener_o_crear_clinica(conn, orden.clinica)

    cirugia_id = conn.execute(
        """INSERT INTO cirugia (paciente_id, cobertura_id, clinica_id, anestesiologo_id,
                                documento_id, fecha_procedimiento)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING cirugia_id""",
        (paciente_id, cobertura_id, clinica_id, anestesiologo_id, documento_id, orden.fecha_procedimiento),
    ).fetchone()["cirugia_id"]

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

    if documento_id is not None:
        conn.execute("UPDATE documento_fuente SET estado = 'VALIDADO' WHERE documento_id = %s", (documento_id,))
    return cirugia_id


def listar_cirugias(conn, anestesiologo_id: int, limite: int = 50) -> list[dict]:
    return conn.execute(
        """SELECT c.cirugia_id, c.fecha_procedimiento, c.estado,
                  p.tipo_documento, p.numero_documento, p.nombres || ' ' || p.apellidos AS paciente,
                  cl.nombre AS clinica,
                  COALESCE(a.nombre, 'PARTICULAR') AS aseguradora, a.tipo AS tipo_aseguradora,
                  (SELECT json_agg(json_build_object('codigo', pr.codigo, 'nombre', pr.nombre,
                                                     'es_principal', cp.es_principal)
                                   ORDER BY cp.es_principal DESC, pr.codigo)
                     FROM cirugia_procedimiento cp JOIN procedimiento pr USING (codigo)
                    WHERE cp.cirugia_id = c.cirugia_id) AS procedimientos
             FROM cirugia c
             JOIN paciente p   USING (paciente_id)
             JOIN clinica cl   USING (clinica_id)
             LEFT JOIN cobertura cb  USING (cobertura_id)
             LEFT JOIN aseguradora a ON a.aseguradora_id = cb.aseguradora_id
            WHERE c.anestesiologo_id = %s
            ORDER BY c.fecha_procedimiento DESC, c.cirugia_id DESC
            LIMIT %s""",
        (anestesiologo_id, limite),
    ).fetchall()


def existe_anestesiologo(conn, anestesiologo_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM anestesiologo WHERE anestesiologo_id = %s", (anestesiologo_id,)
    ).fetchone() is not None


def buscar_anestesiologo_por_email(conn, email: str) -> Optional[dict]:
    return conn.execute(
        "SELECT anestesiologo_id, nombre, password_hash FROM anestesiologo WHERE email = %s",
        (email.strip().lower(),),
    ).fetchone()


def obtener_anestesiologo(conn, anestesiologo_id: int) -> Optional[dict]:
    return conn.execute(
        "SELECT anestesiologo_id, nombre, email FROM anestesiologo WHERE anestesiologo_id = %s",
        (anestesiologo_id,),
    ).fetchone()
