"""Catálogo de procedimientos del Manual ISS 2001 (db/seeds/catalogo_cups.csv) y búsqueda por nombre.

Se usa para sugerir el código CUPS cuando la orden trae el nombre del procedimiento pero no el código.
"""
import csv
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

RUTA = Path(__file__).resolve().parent.parent / "db" / "seeds" / "catalogo_cups.csv"
# Palabras que no ayudan a distinguir un procedimiento de otro
VACIAS = {"DE", "DEL", "LA", "LAS", "EL", "LOS", "Y", "O", "EN", "CON", "POR", "PARA", "A", "AL", "SOD", "NCOC",
          "SIN", "UN", "UNA", "VIA", "TECNICA", "PROCEDIMIENTO", "CIRUGIA", "QUIRURGICO", "QUIRURGICA"}
# Formas comunes en las órdenes -> forma del manual
EQUIVALENCIAS = {"LAPAROSCOPICA": "LAPAROSCOPIA", "LAPAROSCOPICO": "LAPAROSCOPIA", "ARTROSCOPICA": "ARTROSCOPIA",
                 "ARTROSCOPICO": "ARTROSCOPIA", "ENDOSCOPICA": "ENDOSCOPIA", "ENDOSCOPICO": "ENDOSCOPIA",
                 "DERECHA": "", "IZQUIERDA": "", "DERECHO": "", "IZQUIERDO": "", "BILATERAL": "BILATERAL"}


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto).upper())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[^A-Z0-9 ]", " ", t)
    palabras = [EQUIVALENCIAS.get(p, p) for p in t.split()]
    return " ".join(p for p in palabras if p and p not in VACIAS)


# Prefijos del manual que no son procedimientos: C conjuntos integrales (paquetes), S servicios
# (habitación, honorarios), I consultas, A análisis de aguas. No se sugieren como código del procedimiento.
NO_PROCEDIMIENTOS = ("C", "S", "I", "A")


@lru_cache(maxsize=1)
def _cargar() -> tuple[list[dict], dict[str, dict], list[str]]:
    todas = list(csv.DictReader(open(RUTA, encoding="utf-8")))
    for f in todas:
        f["uvr"] = int(f["uvr"]) if f["uvr"] else None
    sugeribles = [f for f in todas if not f["codigo"].startswith(NO_PROCEDIMIENTOS)]
    return sugeribles, {f["codigo"]: f for f in todas}, [normalizar(f["descripcion"]) for f in sugeribles]


def por_codigo(codigo: str) -> dict | None:
    return _cargar()[1].get((codigo or "").strip().upper())


def por_prefijo(codigo: str, limite: int = 8) -> list[dict]:
    """Procedimientos cuyo código empieza por lo escrito (para autocompletar al teclear el código)."""
    codigo = "".join(ch for ch in codigo if ch.isalnum()).upper()
    return [f for c, f in _cargar()[1].items() if c.startswith(codigo)][:limite] if codigo else []


def _puntaje(consulta: str, opcion: str, **_) -> float:
    # token_set premia que estén todas las palabras de la orden; ratio desempata a favor
    # de la descripción más parecida en longitud (la menos específica, ante la duda)
    return 0.7 * fuzz.token_set_ratio(consulta, opcion) + 0.3 * fuzz.token_sort_ratio(consulta, opcion)


MINIMO = 60  # por debajo de esto el parecido es casualidad (p. ej. "cesárea" con "urea")


def buscar(nombre: str, limite: int = 5) -> list[dict]:
    """Procedimientos del catálogo más parecidos al nombre, con su puntaje (0 a 100)."""
    consulta = normalizar(nombre)
    if len(consulta) < 3:
        return []
    filas, _, normalizados = _cargar()
    resultados = process.extract(consulta, normalizados, scorer=_puntaje, limit=limite)
    return [{**filas[i], "puntaje": round(p)} for _, p, i in resultados if p >= MINIMO]


UMBRAL = 85   # puntaje mínimo para poner el código automáticamente
MARGEN = 6    # ventaja mínima sobre la segunda opción (si no, hay que elegir)


def codigo_probable(nombre: str) -> tuple[dict | None, list[dict]]:
    """(procedimiento elegido o None, sugerencias). Solo elige si la coincidencia es clara."""
    sugerencias = buscar(nombre)
    if not sugerencias:
        return None, []
    mejor = sugerencias[0]
    segundo = sugerencias[1]["puntaje"] if len(sugerencias) > 1 else 0
    exacto = normalizar(mejor["descripcion"]) == normalizar(nombre)  # mismo nombre que en el manual
    claro = mejor["puntaje"] >= UMBRAL and mejor["puntaje"] - segundo >= MARGEN
    return (mejor if exacto or claro else None), sugerencias
