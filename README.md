# App Anestesiólogos

Registra cirugías a partir de una **foto o PDF** de la orden quirúrgica. La IA (Claude)
lee los datos y el anestesiólogo los revisa y confirma antes de guardarlos.

## Cómo funciona

1. **Subir la orden**: foto desde el celular o PDF.
2. **Lectura con IA**: extrae paciente, aseguradora (EPS, prepagada o póliza), clínica,
   procedimientos (código CUPS y nombre) y fecha. Marca en amarillo lo que no leyó con seguridad.
3. **Revisar y confirmar**: el usuario corrige lo necesario y guarda.
4. **Base de datos**: se crea la cirugía reutilizando el paciente, la aseguradora y la clínica
   si ya existían. También se pueden registrar cirugías escribiendo los datos a mano.

La arquitectura de datos está en [`docs/arquitectura-datos.md`](docs/arquitectura-datos.md).

## Puesta en marcha

Requisitos: Python 3.11+, PostgreSQL 14+ y una clave de la API de Claude.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

createdb anestesia
psql -d anestesia -f db/schema.sql -f db/seeds/demo.sql

export DATABASE_URL=postgresql:///anestesia
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abrir `http://localhost:8000` (desde el celular, con la IP del computador en la misma red).

| Variable | Por defecto | Para qué |
|---|---|---|
| `DATABASE_URL` | `postgresql:///anestesia` | Conexión a PostgreSQL |
| `ANTHROPIC_API_KEY` | — | Clave de la API de Claude |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Modelo que lee las órdenes |
| `UPLOAD_DIR` | `uploads` | Carpeta donde se guardan las fotos y PDF |
| `ANESTESIOLOGO_ID` | `1` | Usuario con el que se trabaja mientras no hay inicio de sesión |
| `MAX_ARCHIVO_MB` | `20` | Tamaño máximo del archivo |

## API

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `/api/documentos` | Sube la foto/PDF (`archivo`) y devuelve los datos leídos |
| `GET` | `/api/documentos/{id}` | Estado del documento y datos extraídos |
| `POST` | `/api/documentos/{id}/confirmar` | Guarda la cirugía con los datos revisados |
| `POST` | `/api/cirugias` | Registra una cirugía escrita a mano |
| `GET` | `/api/cirugias` | Lista las cirugías del anestesiólogo |

## Pruebas

```bash
createdb anestesia_test
.venv/bin/python -m pytest
```

Las pruebas no llaman a la API de Claude: usan un cliente falso. La base `anestesia_test`
se borra y se recrea en cada prueba (`TEST_DATABASE_URL` para usar otra).

## Pendiente

- Inicio de sesión para varios anestesiólogos.
- Módulo de honorarios (`db/honorarios.sql`, tabla UVR del ISS 2001 en `db/seeds/`):
  diseñado, pendiente el valor de la UVR del anestesiólogo.
- Las fotos y PDF contienen datos de pacientes: en producción deben guardarse cifrados
  y servirse solo por HTTPS.
