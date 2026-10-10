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

export DATABASE_URL=postgresql:///anestesia
export ANTHROPIC_API_KEY=sk-ant-...
export ADMIN_EMAIL=tu@correo.com ADMIN_PASSWORD='una-clave-de-10-o-mas'
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Al arrancar, la app crea las tablas si la base está vacía y deja listo el usuario
`ADMIN_EMAIL` con la contraseña `ADMIN_PASSWORD` (cambiar la variable y reiniciar cambia la contraseña).
Abrir `http://localhost:8000` (desde el celular, con la IP del computador en la misma red).

### En Render

El archivo [`render.yaml`](render.yaml) crea todo de una vez: en Render, **New → Blueprint**,
elegir este repositorio y la rama, y escribir `ANTHROPIC_API_KEY`, `ADMIN_EMAIL` y `ADMIN_PASSWORD`
cuando los pida. Render crea la base PostgreSQL, la app con HTTPS y un disco de 1 GB para las órdenes.

| Variable | Por defecto | Para qué |
|---|---|---|
| `DATABASE_URL` | `postgresql:///anestesia` | Conexión a PostgreSQL |
| `ANTHROPIC_API_KEY` | — | Clave de la API de Claude |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Modelo que lee las órdenes |
| `UPLOAD_DIR` | `uploads` | Carpeta donde se guardan las fotos y PDF |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | — | Usuario inicial (contraseña de 10 caracteres o más) |
| `ADMIN_NOMBRE` | `Anestesiólogo` | Nombre que se muestra del usuario inicial |
| `SESSION_SECRET` | aleatorio | Firma de las sesiones; fijarlo para que no se cierren al reiniciar |
| `COOKIE_SEGURA` | `false` | `true` en producción (solo HTTPS) |
| `MAX_ARCHIVO_MB` | `20` | Tamaño máximo del archivo |

## API

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `/api/login` · `/api/logout` | Iniciar y cerrar sesión (todo lo demás exige sesión) |
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

- Pantalla para agregar más anestesiólogos (hoy solo el usuario inicial).
- Módulo de honorarios (`db/honorarios.sql`, tabla UVR del ISS 2001 en `db/seeds/`):
  diseñado, pendiente el valor de la UVR del anestesiólogo.
- Las fotos y PDF contienen datos de pacientes: en producción deben guardarse cifrados
  y servirse solo por HTTPS.
