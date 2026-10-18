"""Importación de extractos bancarios (tarjetas de crédito, cuentas, créditos) como gastos reales del mes.

Flujo:
  1. Se suben el PDF (de muchas hojas, con clave o sin ella), las fotos, o el Excel/CSV que da el banco.
  2. El PDF y las fotos se leen con la IA por partes de 10 hojas; el Excel/CSV se lee sin IA y la IA solo
     sugiere las categorías. Se queda solo con los gastos: los pagos a la tarjeta, abonos, consignaciones y
     traslados entre cuentas propias no son gastos.
  3. Las categorías aprendidas de las correcciones del anestesiólogo mandan sobre las de la IA.
  4. Cada fila lleva una huella (fecha, valor, comercio); lo ya importado se marca y no se repite.
  5. El usuario revisa y confirma: solo entonces se anotan los gastos. El archivo del banco no se guarda.
"""
import csv
import hashlib
import io
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from psycopg.types.json import Jsonb

from app import extraccion, finanzas, uso_ia

log = logging.getLogger(__name__)

HOJAS_POR_PARTE = 10
MAX_HOJAS = 100            # un extracto mensual rara vez pasa de 30 hojas
FILAS_POR_LOTE = 150       # filas de Excel/CSV por consulta de categorías
MINUTOS_ATASCADA = 30      # una lectura que no avanza en este tiempo se da por fallida
TIPOS_CUENTA = [("TARJETA_CREDITO", "Tarjeta de crédito"), ("CUENTA_AHORROS", "Cuenta de ahorros"),
                ("CUENTA_CORRIENTE", "Cuenta corriente"), ("CREDITO", "Crédito o préstamo"), ("OTRO", "Otro")]
TIPOS_MOVIMIENTO = ["COMPRA", "PAGO_TARJETA", "TRANSFERENCIA_PROPIA", "PAGO_CREDITO", "INTERESES", "CUOTA_MANEJO",
                    "COMISION", "AVANCE", "RETIRO", "CONSIGNACION", "TRANSFERENCIA", "OTRO"]
CATEGORIAS = [c[0] for c in finanzas.CATEGORIAS]


class ExtractoError(Exception):
    """El extracto no se pudo leer (clave errada, formato no soportado…)."""


# ------------------------------------------------------------------ texto y números
def _sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


# Palabras que los bancos ponen antes del comercio y no lo identifican
_RUIDO = {"COMPRA", "COMPRAS", "PAGO", "PAGOS", "PSE", "POS", "EN", "DE", "DEL", "LA", "EL", "TRANSACCION", "TRANSF",
          "CARGO", "DEBITO", "AUTOMATICO", "INTERNET", "APP", "WEB", "CO", "COL", "SAS", "S", "A", "LTDA", "INT",
          "NAL", "NACIONAL", "TARJ", "TARJETA", "CREDITO", "VISA", "MASTERCARD", "MC", "QR", "BRE", "B"}


def clave_comercio(descripcion: str) -> str:
    """Comercio normalizado para aprender categorías: 'COMPRA POS EXITO 123 BQUILLA' -> 'EXITO BQUILLA'."""
    texto = _sin_tildes((descripcion or "").upper())
    # palabras con letras (se descartan números de autorización y referencias: "D1" sí, "000123" no)
    tokens = [t for t in re.findall(r"[A-Z0-9]+", texto)
              if re.search(r"[A-Z]", t) and sum(c.isdigit() for c in t) <= 2]
    palabras = [t for t in tokens if t not in _RUIDO and len(t) > 1]
    if not palabras:  # ej. "PAGO TARJETA": se deja la descripción completa
        palabras = tokens
    return " ".join(palabras[:2])[:80]


def numero(v) -> Optional[Decimal]:
    """Lee valores como los escriben los bancos: '1.234.567,89', '1,234,567.89', '-45.000', '$ 45.000', '(3.500)'."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v))
    s = str(v).strip().replace("$", "").replace("COP", "").replace(" ", "").replace(" ", "")
    negativo = s.startswith("-") or s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("-()+")
    if not s or not re.fullmatch(r"[\d.,]+", s):
        return None
    if "." in s and "," in s:
        decimal_sep = "." if s.rfind(".") > s.rfind(",") else ","
        miles = "," if decimal_sep == "." else "."
        s = s.replace(miles, "").replace(decimal_sep, ".")
    elif "." in s or "," in s:
        sep = "." if "." in s else ","
        partes = s.split(sep)
        if len(partes) > 2 or (len(partes) == 2 and len(partes[1]) == 3):
            s = s.replace(sep, "")              # separador de miles
        else:
            s = s.replace(sep, ".")             # separador decimal
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return -d if negativo else d


def fecha(v, anio_defecto: Optional[int] = None) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if not v:
        return None
    s = str(v).strip()[:10]
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%y", "%d-%m-%y", "%d.%m.%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, formato).date()
        except ValueError:
            pass
    if anio_defecto:  # "05/10" sin año
        try:
            return datetime.strptime(f"{s}/{anio_defecto}", "%d/%m/%Y").date()
        except ValueError:
            pass
    return None


# ------------------------------------------------------------------ archivos
def tipo_archivo(datos: bytes, nombre: str = "") -> str:
    """PDF, IMAGEN, EXCEL o CSV según el contenido (y la extensión para el CSV)."""
    if datos.startswith(b"%PDF"):
        return "PDF"
    if datos.startswith(b"\xd0\xcf\x11\xe0"):
        raise ExtractoError("Ese Excel es del formato antiguo (.xls). Conviene abrirlo y guardarlo como .xlsx o CSV, "
                            "o subir el PDF del extracto.")
    if datos.startswith(b"PK\x03\x04"):
        return "EXCEL"
    tipo = _tipo_imagen(datos)
    if tipo:
        return "IMAGEN"
    if nombre.lower().endswith((".csv", ".txt")) or _parece_texto(datos):
        return "CSV"
    raise ExtractoError("Solo se aceptan extractos en PDF, fotos, Excel (.xlsx) o CSV.")


def _tipo_imagen(datos: bytes) -> Optional[str]:
    firmas = [(b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"GIF8", "image/gif")]
    for firma, tipo in firmas:
        if datos.startswith(firma):
            return tipo
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "image/webp"
    if datos[4:8] == b"ftyp" and datos[8:12] in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"):
        return "image/heic"
    return None


def _parece_texto(datos: bytes) -> bool:
    muestra = datos[:4000]
    return b"\x00" not in muestra and (b"," in muestra or b";" in muestra or b"\t" in muestra)


def partes_pdf(datos: bytes, clave: Optional[str] = None) -> tuple[list[bytes], int]:
    """Divide el PDF en partes de 10 hojas (sin clave). Devuelve las partes y el total de hojas."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.errors import PdfReadError

    try:
        lector = PdfReader(io.BytesIO(datos))
        if lector.is_encrypted:
            if not lector.decrypt(clave or ""):
                raise ExtractoError("El PDF tiene clave. Escribirla en «Clave del PDF» (suele ser la cédula)."
                                    if not clave else "La clave del PDF no es correcta.")
        total = len(lector.pages)
    except ExtractoError:
        raise
    except (PdfReadError, ValueError, KeyError) as e:
        raise ExtractoError("El PDF está dañado o no se pudo abrir.") from e
    if total > MAX_HOJAS:
        raise ExtractoError(f"El PDF tiene {total} hojas; el máximo es {MAX_HOJAS}. Conviene subirlo por meses.")
    partes = []
    for inicio in range(0, total, HOJAS_POR_PARTE):
        escritor = PdfWriter()
        for i in range(inicio, min(inicio + HOJAS_POR_PARTE, total)):
            escritor.add_page(lector.pages[i])
        salida = io.BytesIO()
        escritor.write(salida)
        partes.append(salida.getvalue())
    return partes, total


def preparar_partes(archivos: list[tuple[bytes, str]], clave: Optional[str] = None) -> dict:
    """Ordena lo subido en partes para la IA ({'partes': [[(bytes, mime)]], 'hojas': n}) o en filas
    ya leídas del Excel/CSV ({'filas': [...]})."""
    tipos = [tipo_archivo(d, n) for d, n in archivos]
    if any(t in ("EXCEL", "CSV") for t in tipos):
        if len(archivos) > 1:
            raise ExtractoError("El Excel o CSV se sube solo, un archivo a la vez.")
        datos, nombre = archivos[0]
        filas = leer_excel(datos) if tipos[0] == "EXCEL" else leer_csv(datos)
        if not filas:
            raise ExtractoError("No se encontraron movimientos en el archivo. Revisar que tenga columnas de fecha, "
                                "descripción y valor, o subir el PDF del extracto.")
        return {"filas": filas, "hojas": 0}
    partes: list[list] = []
    hojas = 0
    fotos: list = []
    for (datos, _), tipo in zip(archivos, tipos):
        if tipo == "PDF":
            trozos, n = partes_pdf(datos, clave)
            partes.extend([[(t, extraccion.TIPO_PDF)] for t in trozos])
            hojas += n
        else:
            fotos.append((datos, _tipo_imagen(datos)))
            hojas += 1
    for i in range(0, len(fotos), HOJAS_POR_PARTE):
        partes.append(fotos[i:i + HOJAS_POR_PARTE])
    if hojas > MAX_HOJAS:
        raise ExtractoError(f"Son {hojas} hojas; el máximo es {MAX_HOJAS}. Conviene subirlas por meses.")
    return {"partes": partes, "hojas": hojas}


# ------------------------------------------------------------------ Excel y CSV del banco
_COL_FECHA = ("fecha",)
_COL_DESC = ("descripcion", "concepto", "detalle", "transaccion", "movimiento", "establecimiento", "comercio",
             "referencia", "narrativa", "nombre")
_COL_VALOR = ("valor", "monto", "importe", "total")
_COL_DEBITO = ("debito", "debitos", "cargo", "cargos", "retiro", "retiros", "salida", "egreso")
_COL_CREDITO = ("credito", "creditos", "abono", "abonos", "deposito", "consignacion", "entrada", "ingreso")


def _columnas(fila: list) -> Optional[dict]:
    """Si la fila es el encabezado, dice qué columna es cada cosa."""
    nombres = [_sin_tildes(str(c or "")).lower().strip() for c in fila]

    def buscar(claves, excluir=()):
        for i, n in enumerate(nombres):
            palabras = re.findall(r"[a-z]+", n)
            if any(k in palabras for k in claves) and i not in excluir:
                return i
        return None

    f = buscar(_COL_FECHA)
    d = buscar(_COL_DESC, excluir=(f,))
    deb = buscar(_COL_DEBITO, excluir=(f, d))
    cre = buscar(_COL_CREDITO, excluir=(f, d, deb))
    val = buscar(_COL_VALOR, excluir=(f, d, deb, cre))
    if f is None or d is None or (val is None and deb is None):
        return None
    return {"fecha": f, "descripcion": d, "valor": val, "debito": deb, "credito": cre}


def _filas_de_tabla(tabla: list[list]) -> list[dict]:
    cols = None
    filas = []
    for fila in tabla:
        if cols is None:
            cols = _columnas(fila)
            continue
        def celda(k):
            i = cols[k]
            return fila[i] if i is not None and i < len(fila) else None
        f = fecha(celda("fecha"))
        desc = " ".join(str(celda("descripcion") or "").split())
        if f is None or not desc:
            continue
        if cols["debito"] is not None:
            deb, cre = numero(celda("debito")) or Decimal(0), numero(celda("credito")) or Decimal(0)
            if deb:
                valor, naturaleza = abs(deb), "CARGO"
            elif cre:
                valor, naturaleza = abs(cre), "ABONO"
            else:
                continue
        else:
            v = numero(celda("valor"))
            if not v:
                continue
            valor, naturaleza = abs(v), ("ABONO" if v > 0 else "CARGO")
        filas.append({"fecha": f, "descripcion": desc[:160], "valor": valor, "naturaleza": naturaleza})
    # Con una sola columna de valor, si no hay ningún negativo el banco escribe los cargos en positivo
    # (es el caso de las tarjetas de crédito): todo es cargo y la IA decide qué es un pago o abono.
    if cols and cols["debito"] is None and filas and all(f["naturaleza"] == "ABONO" for f in filas):
        for f in filas:
            f["naturaleza"] = "CARGO"
    return filas


def leer_excel(datos: bytes) -> list[dict]:
    import openpyxl
    try:
        libro = openpyxl.load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    except Exception as e:
        raise ExtractoError("El Excel no se pudo abrir.") from e
    for hoja in libro.worksheets:
        filas = _filas_de_tabla([list(f) for f in hoja.iter_rows(values_only=True)])
        if filas:
            return filas
    return []


def leer_csv(datos: bytes) -> list[dict]:
    for codificacion in ("utf-8-sig", "latin-1"):
        try:
            texto = datos.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    muestra = texto[:5000]
    separador = max([";", ",", "\t", "|"], key=muestra.count)
    return _filas_de_tabla(list(csv.reader(io.StringIO(texto), delimiter=separador)))


# ------------------------------------------------------------------ lectura con la IA
_N = extraccion._nullable
_TEXTO = {"type": "string"}
ESQUEMA_PARTE = {
    "type": "object",
    "properties": {
        "encabezado": {
            "type": "object",
            "properties": {
                "banco": _N(_TEXTO),
                "tipo_producto": _N({"type": "string", "enum": [t for t, _ in TIPOS_CUENTA]}),
                "ultimos_digitos": _N(_TEXTO),
                "periodo_desde": _N(_TEXTO),
                "periodo_hasta": _N(_TEXTO),
            },
            "required": ["banco", "tipo_producto", "ultimos_digitos", "periodo_desde", "periodo_hasta"],
            "additionalProperties": False,
        },
        "movimientos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fecha": _N(_TEXTO),
                    "descripcion": _TEXTO,
                    "valor": {"type": "number"},
                    "naturaleza": {"type": "string", "enum": ["CARGO", "ABONO"]},
                    "tipo": {"type": "string", "enum": TIPOS_MOVIMIENTO},
                    "es_gasto": {"type": "boolean"},
                    "categoria": _N({"type": "string", "enum": CATEGORIAS}),
                },
                "required": ["fecha", "descripcion", "valor", "naturaleza", "tipo", "es_gasto", "categoria"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["encabezado", "movimientos"],
    "additionalProperties": False,
}

_REGLAS_GASTO = """Qué es un gasto (es_gasto):
- SÍ: compras, débitos automáticos, pagos de servicios, colegios, seguros y suscripciones; la cuota de un \
crédito o préstamo pagada desde la cuenta (tipo PAGO_CREDITO, categoría DEUDAS, o VIVIENDA si es hipotecario o \
leasing habitacional); intereses, cuota de manejo y comisiones (categoría DEUDAS); retiros en cajero y avances \
(categoría OTROS).
- NO: el pago a la tarjeta de crédito (PAGO_TARJETA: lo que se gastó con la tarjeta ya se cuenta en su propio \
extracto), traslados entre cuentas propias (TRANSFERENCIA_PROPIA), abonos, consignaciones, nómina, reversiones, \
devoluciones, ni ningún movimiento de naturaleza ABONO.
- Una transferencia a un tercero sin pista de para qué es: es_gasto=true, categoría OTROS.
Categorías: VIVIENDA (arriendo, administración, cuota hipotecaria), SERVICIOS (energía, agua, gas, internet, \
celular, TV), EDUCACION, SALUD (droguerías, médicos, medicina prepagada, seguros), DEUDAS (cuotas de créditos, \
intereses, cuota de manejo, comisiones), ALIMENTACION (supermercados, mercado, panaderías), TRANSPORTE \
(gasolina, peajes, parqueaderos, taxis, apps de transporte, talleres), ENTRETENIMIENTO (restaurantes, bares, \
cine, viajes, hoteles, tiquetes, streaming), PERSONAL (ropa, calzado, peluquería, gimnasio), OTROS. \
Si no es gasto, categoria = null."""

INSTRUCCIONES_EXTRACTO = f"""Lees extractos bancarios de Colombia (tarjetas de crédito, cuentas de ahorros o \
corrientes, créditos) para el presupuesto personal de un médico. Recibes una parte del extracto (hasta \
{HOJAS_POR_PARTE} hojas).

encabezado: banco, tipo de producto, últimos 4 dígitos de la tarjeta o cuenta y periodo facturado \
(AAAA-MM-DD), si aparecen en esta parte; si no, null.

movimientos: TODAS las filas de movimientos de esta parte, una por transacción, sin saltarte ninguna:
- fecha de la transacción en AAAA-MM-DD. Si la fila trae solo día y mes, usa el año del periodo del extracto \
(ojo con diciembre/enero). null si no se lee.
- descripcion: el comercio o concepto tal como aparece (sin el número de autorización).
- valor: en pesos, positivo, sin signos. En tarjetas de crédito usa el VALOR ORIGINAL de la compra, no la cuota \
del mes ni el saldo pendiente. Compras en dólares: el valor en pesos.
- naturaleza: CARGO si sale plata o aumenta la deuda; ABONO si entra plata o disminuye la deuda.
- No incluyas totales, subtotales, saldos, cupos, resúmenes ni tablas de cuotas futuras.

{_REGLAS_GASTO}

Copia los datos tal como están; no inventes filas."""

INSTRUCCIONES_CATEGORIAS = f"""Clasificas movimientos de un extracto bancario de Colombia para el presupuesto \
personal de un médico. Para cada fila (indice, fecha, descripción, valor y naturaleza CARGO/ABONO) decide el \
tipo de movimiento, si es un gasto y su categoría.

{_REGLAS_GASTO}"""

ESQUEMA_CATEGORIAS = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "indice": {"type": "integer"},
                    "tipo": {"type": "string", "enum": TIPOS_MOVIMIENTO},
                    "es_gasto": {"type": "boolean"},
                    "categoria": _N({"type": "string", "enum": CATEGORIAS}),
                },
                "required": ["indice", "tipo", "es_gasto", "categoria"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}


def leer_parte(archivos: list, numero_parte: int, total_partes: int, contexto: dict) -> dict:
    """Lee una parte del extracto (PDF de hasta 10 hojas o hasta 10 fotos) con la IA."""
    pedido = f"Esta es la parte {numero_parte} de {total_partes} del mismo extracto."
    if contexto.get("periodo_hasta"):
        pedido += f" El periodo del extracto termina el {contexto['periodo_hasta']}."
    if contexto.get("banco"):
        pedido += f" Banco: {contexto['banco']}."
    pedido += " Extrae el encabezado (si aparece) y todos los movimientos."
    return extraccion._llamar_claude(archivos, INSTRUCCIONES_EXTRACTO, ESQUEMA_PARTE, pedido, "low", None, tipo="extracto")


def clasificar(filas: list[dict]) -> dict[int, dict]:
    """Sugiere tipo, si es gasto y categoría de filas ya leídas (Excel/CSV), por lotes, solo con texto."""
    resultado: dict[int, dict] = {}
    for inicio in range(0, len(filas), FILAS_POR_LOTE):
        lote = filas[inicio:inicio + FILAS_POR_LOTE]
        lineas = "\n".join(f"{inicio + i}|{f['fecha']}|{f['descripcion']}|{f['valor']}|{f['naturaleza']}"
                           for i, f in enumerate(lote))
        datos = extraccion._llamar_claude([], INSTRUCCIONES_CATEGORIAS, ESQUEMA_CATEGORIAS,
                                          "Filas (indice|fecha|descripción|valor|naturaleza):\n" + lineas, "low", None,
                                          tipo="extracto_categorias")
        for item in datos.get("items", []):
            resultado[item["indice"]] = item
    return resultado


# Respaldo sin IA para las categorías (si la IA falla al clasificar un Excel/CSV)
_PALABRAS = [
    ("PAGO_TARJETA", None, ("PAGO TARJETA", "PAGO TC", "PAGO TARJ", "ABONO TARJETA")),
    ("TRANSFERENCIA_PROPIA", None, ("TRASLADO", "TRANSFERENCIA ENTRE CUENTAS", "CUENTAS PROPIAS")),
    ("INTERESES", "DEUDAS", ("INTERES", "CUOTA DE MANEJO", "CUOTA MANEJO", "COMISION", "GMF", "4X1000", "IVA COMISION")),
    ("COMPRA", "ALIMENTACION", ("EXITO", "OLIMPICA", "CARULLA", "JUMBO", "D1", "ARA", "ISIMO", "SUPERMERCADO", "PANADERIA")),
    ("COMPRA", "TRANSPORTE", ("TERPEL", "PRIMAX", "TEXACO", "BIOMAX", "ESSO", "GASOLINA", "PEAJE", "PARQUEADERO", "UBER", "DIDI", "CABIFY")),
    ("COMPRA", "SERVICIOS", ("AIR-E", "AIRE", "TRIPLE A", "GASES DEL CARIBE", "CLARO", "MOVISTAR", "TIGO", "WOM", "ETB", "DIRECTV")),
    ("COMPRA", "SALUD", ("DROGUERIA", "FARMACIA", "CRUZ VERDE", "FARMATODO", "LA REBAJA", "COLSANITAS", "SURA", "COOMEVA")),
    ("COMPRA", "ENTRETENIMIENTO", ("RESTAURANTE", "NETFLIX", "SPOTIFY", "DISNEY", "CINE", "HOTEL", "AVIANCA", "LATAM", "RAPPI")),
    ("COMPRA", "PERSONAL", ("ZARA", "FALABELLA", "ARTURO CALLE", "PELUQUERIA", "SMART FIT", "BODYTECH")),
    ("COMPRA", "EDUCACION", ("COLEGIO", "UNIVERSIDAD", "MATRICULA", "PENSION ESCOLAR")),
]


def clasificar_por_palabras(fila: dict) -> dict:
    desc = _sin_tildes(fila["descripcion"].upper())
    if fila["naturaleza"] == "ABONO":
        return {"tipo": "CONSIGNACION", "es_gasto": False, "categoria": None}
    for tipo, categoria, palabras in _PALABRAS:
        if any(re.search(rf"\b{re.escape(p)}\b", desc) for p in palabras):
            return {"tipo": tipo, "es_gasto": categoria is not None, "categoria": categoria}
    return {"tipo": "OTRO", "es_gasto": True, "categoria": "OTROS"}


# ------------------------------------------------------------------ resultado para revisar
def huella(f: date, valor: Decimal, clave: str, repeticion: int) -> str:
    texto = f"{f.isoformat()}|{Decimal(valor):.2f}|{clave}|{repeticion}"
    return hashlib.sha256(texto.encode()).hexdigest()[:40]


def armar_resultado(conn, anestesiologo_id: int, encabezado: dict, filas: list[dict]) -> dict:
    """Aplica reglas aprendidas, marca duplicados y decide qué filas quedan marcadas para anotar."""
    reglas = {r["clave"]: r["categoria"] for r in conn.execute(
        "SELECT clave, categoria FROM fin_regla_categoria WHERE anestesiologo_id = %s", (anestesiologo_id,))}
    desde = fecha(encabezado.get("periodo_desde"))
    hasta = fecha(encabezado.get("periodo_hasta"))
    repeticiones: dict[tuple, int] = {}
    items = []
    for i, f in enumerate(filas):
        valor = Decimal(str(f["valor"])).copy_abs().quantize(Decimal("0.01"))
        f_fecha = f["fecha"] if isinstance(f["fecha"], date) else fecha(f["fecha"])
        sin_fecha = f_fecha is None
        f_fecha = f_fecha or hasta or date.today()
        clave = clave_comercio(f["descripcion"])
        k = (f_fecha, valor, clave)
        repeticiones[k] = repeticiones.get(k, 0) + 1
        es_gasto = bool(f.get("es_gasto")) and f.get("naturaleza") != "ABONO" and valor > 0
        categoria = f.get("categoria") if f.get("categoria") in CATEGORIAS else None
        sugerida = categoria
        regla = clave in reglas
        if regla:
            categoria = reglas[clave] or categoria
        if es_gasto and not categoria:
            categoria = "OTROS"
        items.append({"indice": i, "fecha": f_fecha.isoformat(), "descripcion": f["descripcion"][:160],
                      "valor": str(valor), "naturaleza": f.get("naturaleza"), "tipo": f.get("tipo") or "OTRO",
                      "es_gasto": es_gasto, "categoria": categoria, "categoria_sugerida": sugerida,
                      "regla": regla, "clave": clave, "sin_fecha": sin_fecha,
                      "huella": huella(f_fecha, valor, clave, repeticiones[k])})

    huellas = [it["huella"] for it in items]
    ya = {r["huella"] for r in conn.execute(
        "SELECT huella FROM fin_movimiento WHERE anestesiologo_id = %s AND huella = ANY(%s)",
        (anestesiologo_id, huellas))}
    # gastos anotados a mano (sin huella) con la misma fecha y valor
    manuales = {(r["fecha"].isoformat(), f"{r['valor']:.2f}") for r in conn.execute(
        """SELECT fecha, valor FROM fin_movimiento WHERE anestesiologo_id = %s AND clase = 'GASTO'
           AND huella IS NULL AND fecha BETWEEN %s AND %s""",
        (anestesiologo_id, min((it["fecha"] for it in items), default="2000-01-01"),
         max((it["fecha"] for it in items), default="2000-01-01")))}
    for it in items:
        motivo = None
        if it["huella"] in ya:
            motivo = "Ya importado antes"
        elif not it["es_gasto"]:
            motivo = {"PAGO_TARJETA": "Pago de la tarjeta: no es gasto", "TRANSFERENCIA_PROPIA": "Entre cuentas propias",
                      }.get(it["tipo"], "Abono o ingreso: no es gasto" if it["naturaleza"] == "ABONO" else "No es gasto")
        elif (it["fecha"], it["valor"]) in manuales:
            motivo = "Posible duplicado de un gasto anotado a mano"
        elif desde and it["fecha"] < desde.isoformat():
            motivo = "Compra de un mes anterior (diferida)"
        it["duplicado"] = it["huella"] in ya
        it["motivo"] = motivo
        it["incluir"] = it["es_gasto"] and motivo is None
    return {"encabezado": encabezado, "items": items}


def _unir_encabezado(actual: dict, nuevo: dict) -> dict:
    for k, v in (nuevo or {}).items():
        if v and not actual.get(k):
            actual[k] = v
    if actual.get("ultimos_digitos"):
        actual["ultimos_digitos"] = "".join(c for c in str(actual["ultimos_digitos"]) if c.isdigit())[-4:] or None
    return actual


def cuenta_sugerida(conn, anestesiologo_id: int, encabezado: dict) -> Optional[int]:
    """La cuenta registrada que corresponde al extracto (por los últimos dígitos, o por banco y tipo)."""
    cuentas = conn.execute("SELECT cuenta_id, banco, tipo, ultimos_digitos FROM fin_cuenta WHERE anestesiologo_id = %s",
                           (anestesiologo_id,)).fetchall()
    digitos = encabezado.get("ultimos_digitos")
    if digitos:
        for c in cuentas:
            if c["ultimos_digitos"] == digitos:
                return c["cuenta_id"]
    banco = clave_comercio(encabezado.get("banco") or "")
    candidatas = [c for c in cuentas if banco and clave_comercio(c["banco"]).split()[:1] == banco.split()[:1]
                  and c["tipo"] == encabezado.get("tipo_producto") and not (digitos and c["ultimos_digitos"])]
    return candidatas[0]["cuenta_id"] if len(candidatas) == 1 else None


# ------------------------------------------------------------------ importaciones (en segundo plano)
def crear_importacion(conn, anestesiologo_id: int, nombre: str, preparado: dict) -> int:
    partes = len(preparado.get("partes", [])) or 1
    return conn.execute(
        """INSERT INTO fin_importacion (anestesiologo_id, nombre_archivo, partes_total, paginas_total)
           VALUES (%s, %s, %s, %s) RETURNING importacion_id""",
        (anestesiologo_id, nombre[:200], partes, preparado.get("hojas", 0))).fetchone()["importacion_id"]


def procesar(importacion_id: int, anestesiologo_id: int, preparado: dict) -> None:
    """Lee el extracto parte por parte, guardando el avance para que la pantalla lo muestre."""
    from app.repositorio import conectar
    uso_ia.en_nombre_de(anestesiologo_id)
    with conectar() as conn:
        try:
            encabezado: dict = {}
            if "filas" in preparado:
                filas = preparado["filas"]
                try:
                    sugerencias = clasificar(filas)
                except extraccion.ExtraccionError as e:
                    log.warning("Categorías sin IA para la importación %s: %s", importacion_id, e)
                    sugerencias = {}
                for i, f in enumerate(filas):
                    f.update(sugerencias.get(i) or clasificar_por_palabras(f))
                    f["fecha"] = f["fecha"].isoformat()
                    f["valor"] = str(f["valor"])
                _avance(conn, importacion_id, 1)
            else:
                filas = []
                total = len(preparado["partes"])
                for n, archivos in enumerate(preparado["partes"], start=1):
                    datos = leer_parte(archivos, n, total, encabezado)
                    _unir_encabezado(encabezado, datos.get("encabezado"))
                    filas.extend(datos.get("movimientos", []))
                    _avance(conn, importacion_id, n)
            resultado = armar_resultado(conn, anestesiologo_id, encabezado, filas)
            resultado["cuenta_sugerida"] = cuenta_sugerida(conn, anestesiologo_id, encabezado)
            conn.execute("""UPDATE fin_importacion SET estado = 'LISTO', resultado = %s, actualizado_en = now()
                            WHERE importacion_id = %s""", (Jsonb(resultado), importacion_id))
            conn.commit()
        except Exception as e:  # noqa: BLE001  cualquier falla queda registrada para la pantalla
            conn.rollback()
            mensaje = str(e) if isinstance(e, (extraccion.ExtraccionError, ExtractoError)) else \
                "No se pudo leer el extracto. Intentar de nuevo."
            if not isinstance(e, (extraccion.ExtraccionError, ExtractoError)):
                log.exception("Falló la importación %s", importacion_id)
            conn.execute("""UPDATE fin_importacion SET estado = 'ERROR', error = %s, actualizado_en = now()
                            WHERE importacion_id = %s""", (mensaje, importacion_id))
            conn.commit()


def _avance(conn, importacion_id: int, partes_leidas: int) -> None:
    conn.execute("UPDATE fin_importacion SET partes_leidas = %s, actualizado_en = now() WHERE importacion_id = %s",
                 (partes_leidas, importacion_id))
    conn.commit()


def obtener(conn, anestesiologo_id: int, importacion_id: int) -> Optional[dict]:
    fila = conn.execute(
        """SELECT importacion_id, estado, nombre_archivo, partes_total, partes_leidas, paginas_total, resultado,
                  error, creado_en, actualizado_en
             FROM fin_importacion WHERE importacion_id = %s AND anestesiologo_id = %s""",
        (importacion_id, anestesiologo_id)).fetchone()
    if fila and fila["estado"] == "PROCESANDO" and \
            fila["actualizado_en"] < datetime.now(fila["actualizado_en"].tzinfo) - timedelta(minutes=MINUTOS_ATASCADA):
        # el servidor se reinició a mitad de la lectura
        fila["estado"], fila["error"] = "ERROR", "La lectura se interrumpió. Subir el extracto de nuevo."
        conn.execute("UPDATE fin_importacion SET estado = 'ERROR', error = %s WHERE importacion_id = %s",
                     (fila["error"], importacion_id))
        conn.commit()
    return fila


def confirmar(conn, anestesiologo_id: int, importacion_id: int, datos) -> dict:
    """Anota como gastos las filas aprobadas y aprende las categorías que el usuario corrigió."""
    imp = obtener(conn, anestesiologo_id, importacion_id)
    if imp is None:
        raise LookupError("Importación no encontrada.")
    if imp["estado"] != "LISTO":
        raise ExtractoError("Este extracto ya se anotó." if imp["estado"] == "CONFIRMADA"
                            else "El extracto aún no está listo.")
    cuenta_id = datos.cuenta_id
    if cuenta_id and not conn.execute("SELECT 1 FROM fin_cuenta WHERE cuenta_id = %s AND anestesiologo_id = %s",
                                      (cuenta_id, anestesiologo_id)).fetchone():
        raise LookupError("La cuenta no existe.")
    if not cuenta_id and datos.nueva_cuenta:
        cuenta_id = crear_cuenta(conn, anestesiologo_id, datos.nueva_cuenta)
    items = {it["indice"]: it for it in imp["resultado"]["items"]}
    anotados, total, repetidos = 0, Decimal(0), 0
    for elegido in datos.items:
        it = items.get(elegido.indice)
        if it is None:
            continue
        if elegido.incluir:
            fila = conn.execute(
                """INSERT INTO fin_movimiento (anestesiologo_id, fecha, clase, categoria, descripcion, valor,
                                               cuenta_id, huella)
                   VALUES (%s, %s, 'GASTO', %s, %s, %s, %s, %s)
                   ON CONFLICT (anestesiologo_id, huella) WHERE huella IS NOT NULL DO NOTHING
                   RETURNING movimiento_id""",
                (anestesiologo_id, it["fecha"], elegido.categoria, it["descripcion"], it["valor"], cuenta_id,
                 it["huella"])).fetchone()
            if fila:
                anotados += 1
                total += Decimal(it["valor"])
            else:
                repetidos += 1
            # aprende la corrección: la próxima vez ese comercio llega con la categoría elegida
            if it["clave"] and elegido.categoria != it["categoria_sugerida"]:
                conn.execute(
                    """INSERT INTO fin_regla_categoria (anestesiologo_id, clave, categoria) VALUES (%s, %s, %s)
                       ON CONFLICT (anestesiologo_id, clave) DO UPDATE
                       SET categoria = EXCLUDED.categoria, actualizado_en = now()""",
                    (anestesiologo_id, it["clave"], elegido.categoria))
    # El detalle del extracto no se conserva: solo el resumen
    resumen = {"anotados": anotados, "total": str(total), "repetidos": repetidos, "cuenta_id": cuenta_id,
               "encabezado": imp["resultado"].get("encabezado")}
    conn.execute("""UPDATE fin_importacion SET estado = 'CONFIRMADA', resultado = %s, actualizado_en = now()
                    WHERE importacion_id = %s""", (Jsonb(resumen), importacion_id))
    return resumen


# ------------------------------------------------------------------ cuentas
def listar_cuentas(conn, anestesiologo_id: int) -> list[dict]:
    return conn.execute(
        """SELECT c.cuenta_id, c.banco, c.tipo, c.ultimos_digitos, c.nombre,
                  (SELECT max(m.fecha) FROM fin_movimiento m WHERE m.cuenta_id = c.cuenta_id) AS ultimo_movimiento
             FROM fin_cuenta c WHERE c.anestesiologo_id = %s ORDER BY c.banco, c.tipo, c.cuenta_id""",
        (anestesiologo_id,)).fetchall()


def crear_cuenta(conn, anestesiologo_id: int, c) -> int:
    return conn.execute(
        """INSERT INTO fin_cuenta (anestesiologo_id, banco, tipo, ultimos_digitos, nombre)
           VALUES (%s, %s, %s, %s, %s) RETURNING cuenta_id""",
        (anestesiologo_id, c.banco.strip(), c.tipo, c.ultimos_digitos, c.nombre)).fetchone()["cuenta_id"]


def actualizar_cuenta(conn, anestesiologo_id: int, cuenta_id: int, c) -> bool:
    return conn.execute(
        """UPDATE fin_cuenta SET banco = %s, tipo = %s, ultimos_digitos = %s, nombre = %s
           WHERE cuenta_id = %s AND anestesiologo_id = %s""",
        (c.banco.strip(), c.tipo, c.ultimos_digitos, c.nombre, cuenta_id, anestesiologo_id)).rowcount == 1


def borrar_cuenta(conn, anestesiologo_id: int, cuenta_id: int) -> bool:
    """Los gastos ya anotados se conservan (quedan sin cuenta)."""
    return conn.execute("DELETE FROM fin_cuenta WHERE cuenta_id = %s AND anestesiologo_id = %s",
                        (cuenta_id, anestesiologo_id)).rowcount == 1
