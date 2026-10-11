"""Extracción de datos de una orden quirúrgica (foto o PDF) con Claude."""
import base64
import io
import json

import anthropic
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()  # permite abrir fotos HEIC de iPhone/Mac

from app import config
from app.modelos import OrdenExtraida, ReportePagoExtraido

TIPOS_IMAGEN = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/heic"}
TIPO_PDF = "application/pdf"
# La API acepta imágenes de hasta 5 MB y las reduce si superan ~1.600 px por lado;
# las fotos del celular se reducen aquí para no exceder el límite.
MAX_BYTES_IMAGEN = 4_500_000
MAX_LADO_PX = 2400


class ExtraccionError(Exception):
    """La IA no pudo leer la orden."""


def _nullable(tipo: dict) -> dict:
    return {"anyOf": [tipo, {"type": "null"}]}


_TEXTO = {"type": "string"}
ESQUEMA = {
    "type": "object",
    "properties": {
        "paciente": {
            "type": "object",
            "properties": {
                "tipo_documento": _nullable({"type": "string", "enum": ["CC", "TI", "CE", "RC", "PA", "PPT", "MS", "AS"]}),
                "numero_documento": _nullable(_TEXTO),
                "nombres": _nullable(_TEXTO),
                "apellidos": _nullable(_TEXTO),
            },
            "required": ["tipo_documento", "numero_documento", "nombres", "apellidos"],
            "additionalProperties": False,
        },
        "aseguradora": {
            "type": "object",
            "properties": {
                "nombre": _nullable(_TEXTO),
                "tipo": _nullable({"type": "string", "enum": ["EPS", "PREPAGADA", "POLIZA"]}),
                "numero_poliza": _nullable(_TEXTO),
                "plan": _nullable(_TEXTO),
            },
            "required": ["nombre", "tipo", "numero_poliza", "plan"],
            "additionalProperties": False,
        },
        "clinica": {
            "type": "object",
            "properties": {"nombre": _nullable(_TEXTO), "ciudad": _nullable(_TEXTO)},
            "required": ["nombre", "ciudad"],
            "additionalProperties": False,
        },
        "procedimientos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "codigo": _nullable(_TEXTO),
                    "nombre": _nullable(_TEXTO),
                    "es_principal": {"type": "boolean"},
                },
                "required": ["codigo", "nombre", "es_principal"],
                "additionalProperties": False,
            },
        },
        "fecha_procedimiento": _nullable(_TEXTO),
        "cirujano": _nullable(_TEXTO),
        "numero_orden": _nullable(_TEXTO),
        "confianza": {"type": "number"},
        "campos_dudosos": {"type": "array", "items": _TEXTO},
        "observaciones": _nullable(_TEXTO),
    },
    "required": [
        "paciente", "aseguradora", "clinica", "procedimientos",
        "fecha_procedimiento", "cirujano", "numero_orden", "confianza", "campos_dudosos", "observaciones",
    ],
    "additionalProperties": False,
}

INSTRUCCIONES = """Eres un asistente que lee órdenes quirúrgicas, autorizaciones y programaciones de cirugía \
de Colombia para un anestesiólogo. Extrae del documento:

- Paciente: tipo de documento (CC cédula de ciudadanía, TI tarjeta de identidad, CE cédula de \
extranjería, RC registro civil, PA pasaporte, PPT permiso por protección temporal, MS menor sin \
identificación, AS adulto sin identificación), número de documento, nombres y apellidos por separado.
- Aseguradora: nombre de la entidad que paga y su tipo: EPS (régimen contributivo o subsidiado), \
PREPAGADA (medicina prepagada o plan complementario) o POLIZA (póliza de salud de una aseguradora). \
Número de póliza, contrato o afiliación y plan si aparecen. Si el paciente es particular, deja la aseguradora en null.
- Clínica u hospital donde se realiza el procedimiento y su ciudad. La ciudad solo si está escrita \
en el documento (por ejemplo en la dirección o el membrete de la clínica); no la deduzcas del nombre de \
la clínica, de un indicativo telefónico ni de otra pista: en ese caso devuelve null. Si la tomaste del \
membrete o la dirección y no es claro que sea donde se opera, incluye "clinica.ciudad" en campos_dudosos.
- Procedimientos: código CUPS (normalmente 6 caracteres) y nombre tal como aparecen. Marca \
es_principal=true solo en el procedimiento principal (si no se distingue, el primero).
- cirujano: nombre completo del cirujano que realiza el procedimiento (o del médico que ordena la \
cirugía si es el cirujano tratante), sin títulos como "Dr." ni el registro médico. null si no aparece.
- numero_orden: número de la orden o de la autorización de la aseguradora tal como aparece. Si hay \
varios (por ejemplo número de orden y número de autorización), júntalos separados por "/". null si no aparece.
- fecha_procedimiento: fecha programada de la cirugía en formato AAAA-MM-DD. No uses la fecha de \
expedición de la orden ni la de autorización; si la fecha de cirugía no aparece, devuelve null.

Reglas:
- Copia los datos tal como están escritos. Nunca inventes ni completes un dato que no se lee: usa null.
- Números de documento sin puntos ni espacios.
- confianza: de 0 a 1, qué tan seguro estás de la lectura completa.
- campos_dudosos: rutas de los campos que conviene revisar (ilegibles, borrosos o ambiguos), \
por ejemplo "paciente.numero_documento", "procedimientos[1].codigo", "fecha_procedimiento".
- observaciones: frase breve con lo que no se pudo leer o cualquier aclaración útil; null si no hay nada."""


def preparar_imagen(datos: bytes) -> tuple[bytes, str]:
    """Corrige la orientación de la foto y la reduce si es muy grande."""
    img = Image.open(io.BytesIO(datos))
    img = ImageOps.exif_transpose(img)
    if len(datos) <= MAX_BYTES_IMAGEN and max(img.size) <= MAX_LADO_PX and img.format in ("JPEG", "PNG"):
        return datos, Image.MIME[img.format]
    img.thumbnail((MAX_LADO_PX, MAX_LADO_PX))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    salida = io.BytesIO()
    calidad = 90
    while True:
        salida.seek(0)
        salida.truncate()
        img.save(salida, format="JPEG", quality=calidad)
        if salida.tell() <= MAX_BYTES_IMAGEN or calidad <= 50:
            return salida.getvalue(), "image/jpeg"
        calidad -= 10


def _bloque_documento(datos: bytes, media_type: str) -> dict:
    if media_type == TIPO_PDF:
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": TIPO_PDF, "data": base64.standard_b64encode(datos).decode()},
        }
    if media_type in TIPOS_IMAGEN:
        datos, media_type = preparar_imagen(datos)
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(datos).decode()},
        }
    raise ExtraccionError(f"Tipo de archivo no soportado: {media_type}")


Archivo = tuple[bytes, str]  # (contenido, tipo MIME)


def _llamar_claude(archivos: list[Archivo], instrucciones: str, esquema: dict, pedido: str,
                   esfuerzo: str, client: anthropic.Anthropic | None) -> dict:
    """Envía el documento (una o varias páginas) a Claude y devuelve el JSON que cumple el esquema."""
    client = client or anthropic.Anthropic()
    # Si un filtro de seguridad rechaza la solicitud, la API la reintenta con otro modelo.
    # Haiku no tiene ese reintento: con Haiku la opción no se envía.
    reintento = {} if "haiku" in config.CLAUDE_MODEL else {
        "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    try:
        # Streaming: los reportes con muchas filas pueden tardar y no deben cortarse por tiempo
        with client.beta.messages.stream(
            model=config.CLAUDE_MODEL,
            max_tokens=64000,
            system=instrucciones,
            messages=[{
                "role": "user",
                "content": [*(_bloque_documento(d, t) for d, t in archivos), {"type": "text", "text": pedido}],
            }],
            thinking={"type": "adaptive"},
            output_config={"effort": esfuerzo, "format": {"type": "json_schema", "schema": esquema}},
            **reintento,
        ) as flujo:
            respuesta = flujo.get_final_message()
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        raise ExtraccionError("La clave de Claude (ANTHROPIC_API_KEY) no es válida o no tiene crédito. "
                              "Revísala en la configuración de Render.") from e
    except anthropic.BadRequestError as e:
        raise ExtraccionError(f"El archivo no se pudo procesar: {e.message}") from e
    except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
        raise ExtraccionError("El servicio de lectura no está disponible, intenta de nuevo en un momento.") from e

    if respuesta.stop_reason == "refusal":
        raise ExtraccionError("No fue posible leer este documento.")
    if respuesta.stop_reason == "max_tokens":
        raise ExtraccionError("La lectura quedó incompleta, intenta de nuevo.")
    texto = next((b.text for b in respuesta.content if b.type == "text"), None)
    if not texto:
        raise ExtraccionError("La lectura no devolvió datos.")
    return json.loads(texto)


def extraer_orden(archivos: list[Archivo], client: anthropic.Anthropic | None = None) -> OrdenExtraida:
    """Lee la orden. Si llega en varias fotos o archivos, se leen juntos como una sola orden."""
    pedido = ("Extrae los datos de esta orden." if len(archivos) == 1 else
              f"Estos {len(archivos)} archivos son fotos o páginas de la MISMA orden (por ejemplo la orden y su "
              "autorización). Combina la información de todos y extrae los datos de esa única orden.")
    return OrdenExtraida.model_validate(_llamar_claude(archivos, INSTRUCCIONES, ESQUEMA, pedido, "high", client))


# ---------------------------------------------------------------- reportes de pago
_NUMERO = {"type": "number"}
ESQUEMA_PAGO = {
    "type": "object",
    "properties": {
        "pagador": _nullable(_TEXTO),
        "prestador": _nullable(_TEXTO),
        "fecha_proceso": _nullable(_TEXTO),
        "periodo_desde": _nullable(_TEXTO),
        "periodo_hasta": _nullable(_TEXTO),
        "total_neto": _nullable(_NUMERO),
        "filas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "empresa": _nullable(_TEXTO),
                    "documento_paciente": _nullable(_TEXTO),
                    "paciente": _nullable(_TEXTO),
                    "fecha_servicio": _nullable(_TEXTO),
                    "factura": _nullable(_TEXTO),
                    "autorizacion": _nullable(_TEXTO),
                    "total": _nullable(_NUMERO),
                    "glosas": _nullable(_NUMERO),
                    "descuentos": _nullable(_NUMERO),
                    "neto": _nullable(_NUMERO),
                    "es_paciente": {"type": "boolean"},
                },
                "required": ["empresa", "documento_paciente", "paciente", "fecha_servicio", "factura",
                             "autorizacion", "total", "glosas", "descuentos", "neto", "es_paciente"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["pagador", "prestador", "fecha_proceso", "periodo_desde", "periodo_hasta", "total_neto", "filas"],
    "additionalProperties": False,
}

INSTRUCCIONES_PAGO = """Lees reportes de pago que reciben los anestesiólogos en Colombia (por ejemplo \
"Reporte de pagos a prestadores" o "relación de pacientes pagados" de una asociación o pagador). \
Extrae:

- pagador: entidad que emite el reporte y paga (ej. la asociación). prestador: nombre del anestesiólogo.
- fecha_proceso: fecha del proceso o del pago. periodo_desde / periodo_hasta: periodo del reporte.
- total_neto: el total neto general del reporte, si aparece.
- filas: UNA por cada línea de detalle, en el mismo orden del documento. Cada línea pertenece a la \
empresa (aseguradora, EPS, IPS) bajo cuyo encabezado aparece. No incluyas subtotales ni totales como filas.
  - documento_paciente sin puntos ni espacios; paciente tal como aparece.
  - fecha_servicio: la fecha de la línea (fecha de la atención o cirugía).
  - total, glosas, descuentos, neto: valores en pesos como números enteros (700,405 -> 700405).
  - es_paciente: false si la línea no corresponde a un paciente individual (ej. "HONORARIOS", \
pagos globales o conceptos); true en los demás casos.

Reglas: todas las fechas en formato AAAA-MM-DD (en Colombia el formato del documento es día/mes/año). \
Copia los datos tal como están; nunca inventes un valor que no se lee: usa null."""


def extraer_reporte_pago(datos: bytes, media_type: str, client: anthropic.Anthropic | None = None) -> ReportePagoExtraido:
    return ReportePagoExtraido.model_validate(_llamar_claude(
        [(datos, media_type)], INSTRUCCIONES_PAGO, ESQUEMA_PAGO, "Extrae todas las líneas de este reporte de pagos.",
        "medium", client))
