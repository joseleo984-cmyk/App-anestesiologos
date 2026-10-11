"""Construye db/seeds/cups.csv desde el PDF de la resolución CUPS del Ministerio de Salud.

Uso: python3 scripts/construir_cups.py Resolucion-No-2706-de-2025.pdf
(necesita pdfplumber: pip install pdfplumber)

Toma las tablas CÓDIGO | DESCRIPCIÓN del listado tabular. Guarda los procedimientos (código de
6 caracteres, p. ej. 47.1.1.02 -> 471102) con la categoría a la que pertenecen (47.1.1. APENDICECTOMÍA).
"""
import csv
import re
import sys
from pathlib import Path

import pdfplumber

PROCEDIMIENTO = re.compile(r"^([0-9A-Z]{2})\.([0-9A-Z])\.([0-9A-Z])\.([0-9A-Z]{2})$")
CATEGORIA = re.compile(r"^([0-9A-Z]{2})\.([0-9A-Z])\.([0-9A-Z])\.$")
SALIDA = Path(__file__).resolve().parent.parent / "db" / "seeds" / "cups.csv"


def filas(ruta):
    with pdfplumber.open(ruta) as pdf:
        for pagina in pdf.pages:
            for tabla in pagina.extract_tables():
                for fila in tabla:
                    if len(fila) >= 2:
                        yield (fila[0] or "").strip(), " ".join((fila[1] or "").split())


def construir(ruta):
    procedimientos, categoria, anterior = {}, "", None
    for codigo, descripcion in filas(ruta):
        codigo = codigo.replace(" ", "")
        if m := PROCEDIMIENTO.match(codigo):
            anterior = "".join(m.groups())
            procedimientos.setdefault(anterior, [descripcion, categoria])
        elif CATEGORIA.match(codigo):
            categoria, anterior = descripcion, None
        elif not codigo and descripcion and anterior and descripcion.upper() == descripcion:
            # la descripción siguió en la página siguiente
            procedimientos[anterior][0] += " " + descripcion
        else:
            anterior = None  # encabezados, capítulos, "Incluye:", "Excluye:"
    return procedimientos


if __name__ == "__main__":
    datos = construir(sys.argv[1])
    with open(SALIDA, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["codigo", "descripcion", "categoria"])
        for codigo in sorted(datos):
            w.writerow([codigo, *datos[codigo]])
    print(f"{len(datos)} procedimientos -> {SALIDA}")
