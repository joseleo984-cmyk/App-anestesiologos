"""Restaura una copia de seguridad de Auditorías AP (el .zip cifrado que descarga el administrador).

Uso (en un computador con Python y las dependencias de requirements.txt):
    DATABASE_URL="postgresql://..." python db/mantenimiento/restaurar_copia.py copia-auditorias-ap-AAAA-MM-DD.zip

- La base de destino debe tener el esquema: si es un proyecto nuevo de Supabase, basta con arrancar la app una vez
  apuntando a él (crea las tablas), o correr db/schema.sql.
- Con --vaciar se BORRAN primero todos los datos de la base de destino (pide confirmación).
- La clave de la copia se pide al correr; nunca se escribe en la línea de comandos.
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app import copia  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("archivo")
    p.add_argument("--vaciar", action="store_true", help="borra los datos actuales antes de restaurar")
    a = p.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Falta la variable DATABASE_URL con la dirección de la base de destino.")
    if a.vaciar and input("Se BORRARÁN todos los datos de la base de destino. Escriba BORRAR para seguir: ") != "BORRAR":
        sys.exit("Cancelado.")
    clave = getpass.getpass("Clave de la copia: ")
    with psycopg.connect(url, row_factory=dict_row, prepare_threshold=None) as conn:
        try:
            filas = copia.restaurar(conn, Path(a.archivo).read_bytes(), clave, vaciar=a.vaciar)
        except ValueError as e:
            conn.rollback()
            sys.exit(str(e))
        conn.commit()
    for t, n in filas.items():
        print(f"{t}: {n}")
    print("Copia restaurada.")


if __name__ == "__main__":
    main()
