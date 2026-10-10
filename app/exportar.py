"""Exportación a Excel de las cirugías y del resumen por cirujano, clínica y aseguradora."""
import io

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

PESOS = '"$"#,##0'
ENCABEZADO = Font(bold=True, color="FFFFFF")
FONDO = PatternFill("solid", fgColor="0B6BCB")


def _hoja(ws, titulos: list[str], filas: list[list], columnas_pesos: set[int], anchos: list[int]) -> None:
    ws.append(titulos)
    for celda in ws[1]:
        celda.font, celda.fill = ENCABEZADO, FONDO
    for fila in filas:
        ws.append(fila)
    for i, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(i)].width = ancho
        if i in columnas_pesos:
            for (celda,) in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                celda.number_format = PESOS
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def libro_cirugias(cirugias: list[dict], reporte: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Cirugías"
    filas = []
    for c in cirugias:
        procs = c["procedimientos"] or []
        filas.append([
            c["fecha_procedimiento"], c["paciente"], c["tipo_documento"], c["numero_documento"],
            c["aseguradora"], c["tipo_aseguradora"] or "PARTICULAR", c["numero_poliza"], c["clinica"],
            c["cirujano"], ", ".join(p["codigo"] for p in procs), "; ".join(p["nombre"] for p in procs),
            c["estado"], float(c["valor_honorarios"]) if c["valor_honorarios"] is not None else None,
            c["fecha_pago"],
        ])
    _hoja(ws, ["Fecha", "Paciente", "Tipo doc.", "Documento", "Aseguradora", "Tipo", "Póliza",
               "Clínica", "Cirujano", "Códigos CUPS", "Procedimientos", "Estado", "Valor honorarios",
               "Fecha de pago"], filas, {13}, [12, 30, 9, 14, 24, 12, 14, 28, 28, 16, 45, 12, 16, 14])
    for (celda,) in ws.iter_rows(min_row=2, min_col=1, max_col=1):
        celda.number_format = "yyyy-mm-dd"

    for titulo, clave in (("Por cirujano", "por_cirujano"), ("Por clínica", "por_clinica"),
                          ("Por aseguradora", "por_aseguradora"), ("Por mes", "por_mes")):
        hoja = wb.create_sheet(titulo)
        _hoja(hoja, [titulo.removeprefix("Por ").capitalize(), "Cirugías", "Total", "Pagado", "Por cobrar",
                     "Sin valor"],
              [[r["nombre"], r["cirugias"], float(r["total"]), float(r["pagado"]), float(r["por_cobrar"]),
                r["sin_valor"]] for r in reporte[clave]],
              {3, 4, 5}, [34, 10, 16, 16, 16, 10])

    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()
