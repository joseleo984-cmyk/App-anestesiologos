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
| `CIUDAD_POR_DEFECTO` | `Barranquilla` | Ciudad cuando la orden no la trae y la clínica no tiene una conocida (vacío = ninguna) |
| `MAX_ARCHIVO_MB` | `20` | Tamaño máximo del archivo |

## API

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `/api/login` · `/api/logout` | Iniciar y cerrar sesión (todo lo demás exige sesión) |
| `POST` | `/api/cambiar-clave` | Cambia la propia contraseña (cierra las otras sesiones) |
| `GET` · `POST` | `/api/usuarios` | Administrador: lista y crea cuentas (devuelve la clave temporal) |
| `PUT` · `POST` | `/api/usuarios/{id}` · `/restablecer` | Administrador: activa/desactiva · nueva clave temporal |
| `POST` | `/api/documentos` | Sube la orden en una o varias fotos/PDF (`archivos`, máx. 8) y devuelve los datos leídos |
| `GET` | `/api/relacion` · `/api/relacion.xlsx` | Relación de órdenes para facturación; `tipo`, `aseguradora_id` y `clinica_id` admiten varios valores; el Excel recibe `ids` (filas elegidas) y `mes` |
| `GET` | `/api/pagos/{id}/liquidacion` | Volante calculado con la fórmula de AP sobre el recaudo neto del reporte |
| `POST` | `/api/pagos/{id}/volante` | Lee el volante que entregó AP (IA) y lo compara concepto por concepto (no se guarda) |
| `GET` | `/api/finanzas?mes=` | Estado financiero del anestesiólogo: ingreso base, gastos con semáforo, metas, compromisos, el mes elegido y consejos |
| `POST` · `DELETE` | `/api/finanzas/movimientos` | Gastos reales y aportes a metas (el aporte suma a lo ahorrado) |
| `PUT` | `/api/finanzas/metas/{id}/compromiso` | Compromiso de ahorro mensual de una meta (null lo quita) |
| `POST` · `PUT` · `DELETE` | `/api/finanzas/partidas` · `/api/finanzas/metas` | Gastos, ingresos adicionales y metas de ahorro |
| `POST` · `DELETE` | `/api/volantes` · `/api/volantes/{mes}` | Sube el volante de un mes (queda como ingreso real) o lo quita |
| `GET` | `/api/clinicas` | Clínicas registradas (para sugerirlas al escribir) |
| `GET` | `/api/procedimientos?q=` | Busca en el catálogo CUPS por nombre o por inicio del código (autocompletar) |
| `GET` | `/api/documentos/{id}` | Estado del documento y datos extraídos |
| `POST` | `/api/documentos/{id}/confirmar` | Guarda la cirugía con los datos revisados |
| `POST` | `/api/cirugias` | Registra una cirugía escrita a mano |
| `GET` | `/api/cirugias` | Lista con filtros: `desde`, `hasta`, `cirujano_id`, `clinica_id`, `aseguradora_id` (o `PARTICULAR`), `estado`, `q` |
| `GET` · `PUT` | `/api/cirugias/{id}` | Detalle y corrección de una cirugía (cirujano, estado, valor, fecha de pago…) |
| `GET` | `/api/documentos/{id}/archivo?pagina=N` | Foto o PDF original de la orden (cada página) |
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

## Código CUPS sugerido

Si la orden trae el nombre del procedimiento pero no el código, la app lo busca en la CUPS vigente
(Resolución 2706 de 2025 del Ministerio de Salud, `db/seeds/cups.csv`, 9.459 procedimientos):

- Si el nombre coincide claramente con uno solo ("Colecistectomía laparoscópica" → 512104), pone el
  código y lo marca en amarillo para revisarlo.
- Si hay varias opciones (p. ej. "Apendicectomía": vía abierta 471102 o laparoscópica 471110), deja
  el código vacío y muestra las opciones para tocar la correcta.
- Al escribir un nombre o un código a mano también aparecen opciones del catálogo.

Cuando salga la resolución CUPS del año siguiente, se regenera con
`python3 scripts/construir_cups.py Resolucion.pdf` (necesita `pip install pdfplumber`).
El catálogo del manual ISS 2001 con sus UVR queda en `db/seeds/iss2001_catalogo.csv` para el
módulo de honorarios.

## Liquidación del volante (AP)

`app/liquidacion.py` calcula el volante a partir del recaudo neto del reporte de pagos, con la fórmula de
la propuesta de AP:

- Del recaudo se apartan probienestar 20 %, administración 5 %, semestral 2,85 %, anual 2,85 % y
  vacaciones 1 %; queda la base del contrato. De ella, 12,1 % para seguridad social.
- Lo que queda se reparte 60 % compensaciones (ordinaria = 1 SMLMV, el resto extraordinaria) y 40 %
  auxilio sindical. Si el 60 % no alcanza al SMLMV, la ordinaria se completa y el auxilio baja (con aviso).
- Deducciones: salud 4 % y pensión 4 % de las compensaciones, 4 x mil y cuota de sostenimiento (5 % del SMLMV).
- Recaudo bajo (el 60 % no alcanza a 1 SMLMV): todo es compensación, sin auxilio; salud y pensión sobre
  1 SMLMV y un "ajuste sindical" = 22,936 % del SMLMV − 8,3 % del recaudo (deducido de mayo y septiembre).
- La retención en la fuente no se calcula: al comparar se toma del volante y se descuenta del neto.

Verificada contra los volantes reales de abril a octubre de 2026 (`tests/test_liquidacion.py`).

El SMLMV está en `SMLMV` dentro de `app/liquidacion.py` (2026: $1.750.905); la variable de entorno
`SMLMV` lo reemplaza sin tocar el código.

## Finanzas personales

Cada anestesiólogo ve solo las suyas (ni el administrador las ve). `app/finanzas.py`:

- **Ingreso de cada mes:** el volante de AP si se subió (en Pagos al comparar, o en Finanzas); si no, la
  liquidación calculada del reporte de pagos. Neto + tarjeta probienestar (es de libre uso).
- **Ingreso base:** promedio de los 3 meses más bajos de los últimos 12, más los ingresos adicionales.
  Con ingresos tan variables, el presupuesto se arma sobre esa base y no sobre el promedio.
- **Gastos:** cada categoría tiene una referencia sana (% del ingreso base): vivienda 30, servicios 8,
  educación 15, salud 10, deudas 20, alimentación 15, transporte 10, entretenimiento 10, personal 5,
  otros 5. Semáforo: sano, alto (hasta 25 % por encima) o muy alto. Gasto total sano hasta el 80 %
  (ahorro de al menos 20 %); gastos fijos hasta el 50 %.
- **Metas:** cuánto apartar al mes según la fecha; el fondo de emergencias sugerido es de 6 meses de gastos.
- **Consejos:** avisos sobre lo anterior y, cuando un mes entra por encima de la base, llevar el excedente
  a las metas.
- **Lo que viene:** estima cuánto y cuándo pagará AP las cirugías realizadas y aún no pagadas, con el neto
  promedio por paciente (por aseguradora si hay al menos 2 pagos) y la mediana de días entre la cirugía y
  el pago; cada mes se pasa por la liquidación. Las de más de 6 meses se reportan como atrasadas.
- **Ahorros en AP:** semestral, anual, vacaciones y aporte sindical del último volante que los trae.
- **Proyección de metas:** mes a mes, primero el fondo de emergencias y las cuotas de las metas con fecha;
  dice en qué mes se cumple cada una y si llega a tiempo.
- **Créditos:** con saldo y tasa EA, meses para terminar, intereses totales y cuál abonar primero.
- **Compromisos de ahorro:** cada meta muestra cuánto hay que ahorrar al mes para llegar a la fecha; el
  anestesiólogo se compromete a un valor mensual y la app lleva el cumplimiento de cada mes, la racha de
  meses seguidos cumplidos, el historial de 6 meses y en qué mes se cumple la meta a ese ritmo.
- **Este mes (gastos reales):** se anotan los gastos (por categoría) y los ahorros (a una meta, que suman a
  lo ahorrado). Cada categoría se compara con su presupuesto: dentro, pasado (hasta 10 % más), muy pasado
  o sin presupuesto. Se puede mirar cualquier mes anterior.
- **Semestral de AP:** se paga con los cortes de junio y diciembre (confirmado con AP).
- **Gráficas:** ingresos por mes (neto + probienestar, con la línea del ingreso base), a dónde va el ingreso
  base (gastos fijos, variables, metas y lo libre), gastos de los últimos 6 meses contra el presupuesto, lo que
  llegaría por mes y, en Reportes, cirugías por mes (pagado y por cobrar). Se tocan para ver el detalle de cada
  mes; los colores están validados para daltonismo y modo oscuro.
- **Extractos del banco** (`app/extractos.py`): se sube el extracto de una tarjeta, cuenta o crédito y la app
  anota los gastos. El PDF (con o sin clave; muchas hojas, máximo 100) y las fotos se leen con la IA de 10 en
  10 hojas, en segundo plano, mostrando el avance. El Excel (.xlsx) o CSV del banco se lee sin IA (detecta las
  columnas de fecha, descripción y valor o débito/crédito) y la IA solo sugiere categorías (texto, barato; si
  falla, se clasifica por palabras clave). Solo cuentan los gastos: el pago a la tarjeta, abonos y traslados
  entre cuentas propias no. Cada fila lleva una huella (fecha, valor, comercio) para no anotar dos veces lo
  mismo; también se avisa si coincide con un gasto anotado a mano y se desmarcan las compras diferidas de
  meses anteriores. El usuario revisa, cambia categorías y confirma; las categorías corregidas se recuerdan
  por comercio. Varias cuentas y tarjetas por anestesiólogo; el archivo del banco no se guarda.

## Noticias de anestesia

`app/noticias.py`. Fuentes curadas que administra el administrador (pestaña Noticias, al final): RSS de
revistas y sociedades o una búsqueda guardada de PubMed. Con «Probar» se revisa la dirección sin guardar nada.

- La primera vez que alguien abre Noticias, si pasaron más de 6 horas, las fuentes se revisan en segundo plano
  (así funciona aunque el servidor gratis se duerma). Solo se traen publicaciones de los últimos 30 días y la
  misma publicación que llega por dos fuentes entra una sola vez.
- La IA resume cada publicación una vez (2 o 3 frases en español), la clasifica por tema y tipo, y descarta lo que
  no sirve (fe de erratas, índices…). El texto original se borra después de resumir; se muestra el título, el
  resumen propio y el enlace al original.
- Cada anestesiólogo elige sus temas, marca como leída (una o todas), guarda favoritas y ve las leídas aparte.
  La pestaña muestra cuántas nuevas tiene. Las noticias de más de 180 días se borran, menos las guardadas.
- Fuentes iniciales (`db/seeds/fuentes_noticias.csv`, se cargan una sola vez): búsquedas de PubMed para guías y
  consensos, revisiones sistemáticas, y las revistas Anesthesiology, BJA, Anesthesia & Analgesia, Anaesthesia,
  RAPM, European Journal of Anaesthesiology y la Revista Colombiana de Anestesiología (sin cartas, comentarios,
  editoriales ni fe de erratas), más el RSS de la APSF.
- `NOTICIAS_MODEL` (opcional, en Render): modelo para resumir noticias, por ejemplo `claude-sonnet-5-5`, distinto
  del de las órdenes. Sin ella se usa `CLAUDE_MODEL`.

## Copia de seguridad

El administrador la descarga en Cuenta → Anestesiólogos (cuentas) → «Copia de seguridad»: todas las tablas en CSV
dentro de un .zip cifrado (AES-256) con una clave de al menos 10 caracteres que escoge al descargarla. Sin la clave
no se abre. Las fotos y PDF de las órdenes (Supabase Storage) no van en la copia.

Para restaurar (en un computador con Python y `pip install -r requirements.txt`), sobre una base con el esquema:

    DATABASE_URL="postgresql://..." python db/mantenimiento/restaurar_copia.py copia-auditorias-ap-AAAA-MM-DD.zip

La clave se pide al correrlo. Con `--vaciar` borra primero los datos de la base de destino (pide escribir BORRAR).

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
