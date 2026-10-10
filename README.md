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

Al arrancar, la app crea las tablas si la base está vacía, aplica `db/migraciones.sql` a las bases existentes y deja listo el
administrador `ADMIN_EMAIL` con la contraseña `ADMIN_PASSWORD`. Esa contraseña se aplica al crearlo y cada vez que la
variable **cambia** en Render; si el administrador la cambia desde la app, reiniciar no la revierte.
Abrir `http://localhost:8000` (desde el celular, con la IP del computador en la misma red).

### En Supabase + Render (pruebas sin costo)

La base de datos y las fotos/PDF van en **Supabase**; la app corre en **Render** (plan gratis).

1. En supabase.com crear un proyecto en la región **East US (North Virginia)**, la misma de Render.
2. Copiar de Supabase: la cadena de conexión **Session pooler** (botón *Connect*), la
   **Project URL** y la clave **service_role** (*Project Settings → API keys*).
3. En Render: **New → Blueprint**, elegir este repositorio y la rama, y pegar esos datos junto con
   `ANTHROPIC_API_KEY`, `ADMIN_EMAIL` y `ADMIN_PASSWORD` cuando los pida ([`render.yaml`](render.yaml)).

Al arrancar, la app crea las tablas, el bucket privado `ordenes` y activa RLS en todas las tablas:
la API pública de Supabase no ve ningún dato; solo la app, que se conecta como dueña de las tablas.

| Variable | Por defecto | Para qué |
|---|---|---|
| `DATABASE_URL` | `postgresql:///anestesia` | Conexión a PostgreSQL |
| `DATABASE_PASSWORD` | — | Si `DATABASE_URL` trae `[YOUR-PASSWORD]` (como la copia Supabase), se reemplaza por esta |
| `ANTHROPIC_API_KEY` | — | Clave de la API de Claude |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Modelo que lee las órdenes |
| `UPLOAD_DIR` | `uploads` | Carpeta de las fotos y PDF si no se usa Supabase |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | — | Guardar las fotos y PDF en Supabase Storage |
| `SUPABASE_BUCKET` | `ordenes` | Bucket privado de Supabase Storage |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | — | Usuario inicial (contraseña de 10 caracteres o más) |
| `ADMIN_NOMBRE` | `Anestesiólogo` | Nombre que se muestra del usuario inicial |
| `SESSION_SECRET` | aleatorio | Firma de las sesiones; fijarlo para que no se cierren al reiniciar |
| `COOKIE_SEGURA` | `false` | `true` en producción (solo HTTPS) |
| `MAX_ARCHIVO_MB` | `20` | Tamaño máximo del archivo |

## API

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `/api/login` · `/api/logout` | Iniciar y cerrar sesión (todo lo demás exige sesión) |
| `POST` | `/api/cambiar-clave` | Cambia la propia contraseña (cierra las otras sesiones) |
| `GET` · `POST` | `/api/usuarios` | Administrador: lista y crea cuentas (devuelve la clave temporal) |
| `PUT` · `POST` | `/api/usuarios/{id}` · `/restablecer` | Administrador: activa/desactiva · nueva clave temporal |
| `POST` | `/api/documentos` | Sube la foto/PDF (`archivo`) y devuelve los datos leídos |
| `GET` | `/api/documentos/{id}` | Estado del documento y datos extraídos |
| `POST` | `/api/documentos/{id}/confirmar` | Guarda la cirugía con los datos revisados |
| `POST` | `/api/cirugias` | Registra una cirugía escrita a mano |
| `GET` | `/api/cirugias` | Lista con filtros: `desde`, `hasta`, `cirujano_id`, `clinica_id`, `aseguradora_id` (o `PARTICULAR`), `estado`, `q` |
| `GET` · `PUT` | `/api/cirugias/{id}` | Detalle y corrección de una cirugía (cirujano, estado, valor, fecha de pago…) |
| `GET` | `/api/documentos/{id}/archivo` | Foto o PDF original de la orden |
| `GET` | `/api/reportes` | Totales y ranking por cirujano, clínica, aseguradora y mes (mismos filtros) |
| `POST` | `/api/pagos` | Sube la relación de pacientes pagados; la IA la lee y la cruza con las cirugías |
| `GET` | `/api/pagos` · `/api/pagos/{id}` | Reportes subidos y detalle del cruce (encontrada, sin cirugía, otro concepto) |
| `POST` | `/api/pagos/{id}/aplicar` · `/cruzar` | Marca como PAGADAS las encontradas (neto y fecha del reporte) · repite el cruce |
| `GET` | `/api/cirugias.xlsx` | Excel con las cirugías y los resúmenes (mismos filtros) |

## Pruebas

```bash
createdb anestesia_test
.venv/bin/python -m pytest
```

Las pruebas no llaman a la API de Claude: usan un cliente falso. La base `anestesia_test`
se borra y se recrea en cada prueba (`TEST_DATABASE_URL` para usar otra).

## Varios anestesiólogos

El administrador (`ADMIN_EMAIL`) crea las cuentas en **menú de la cuenta → Anestesiólogos (cuentas)**: cada una recibe
una clave temporal que se muestra una sola vez y que el anestesiólogo debe cambiar al entrar. Puede desactivar cuentas
y generar claves temporales nuevas; ambas acciones cierran las sesiones abiertas de esa cuenta, igual que cambiar la
propia contraseña cierra las de los demás dispositivos. Cada anestesiólogo ve solo sus cirugías, órdenes, pagos y
reportes, y puede subir su propia copia de un archivo que otro también tenga.

## Pagos: depurar pendientes

La relación de pacientes pagados (p. ej. "Reporte de pagos a prestadores" de la asociación) se sube en
la pestaña **Pagos**. La IA lee cada línea (empresa, documento, fecha, factura, autorización, total,
glosas, descuentos, neto) y la app comprueba que las líneas sumen el total del reporte. Cada línea se
cruza con la cirugía del mismo documento de paciente y la fecha más cercana (hasta 15 días); al
aplicarlo, esas cirugías quedan **PAGADAS** con el neto y la fecha del reporte. Lo que no aparece
queda como **pendiente de pago** (filtro y tarjeta en Reportes).

## Pendiente

- Módulo de honorarios (`db/honorarios.sql`, tabla UVR del ISS 2001 en `db/seeds/`):
  diseñado, pendiente el valor de la UVR del anestesiólogo.
- Las fotos y PDF contienen datos de pacientes: en producción deben guardarse cifrados
  y servirse solo por HTTPS.
