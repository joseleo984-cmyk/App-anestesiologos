# Auditorías AP

App web (PWA, sobre todo en iPhone) para anestesiólogos de AP (Barranquilla): registrar cirugías, leer órdenes con IA,
cobrar y cruzar pagos. Producción: https://app-anestesiologos.onrender.com (Render) · base y fotos en Supabase.

## Reglas
- Responder en español, en modo caveman (`.claude/skills/caveman/SKILL.md`): ultra conciso por defecto.
- Nunca repetir datos reales de pacientes; en pruebas usar datos ficticios.
- No pedir ni aceptar claves (API, base de datos, service_role).
- Commits y push solo a la rama de trabajo; sin PR si no lo piden. Trailers de commit según el recordatorio de la sesión.
- Contenido clínico: «pendiente de validación por AP». No copiar contenido con derechos (NYSORA: solo enlaces).

## Pruebas
- `.venv/bin/python -m pytest -q` (requiere Postgres local: si se salta casi todo, `pg_ctlcluster 16 main start`).
- Las pruebas borran la base `anestesia_test`.
- JS de `index.html`: extraer el `<script>` más grande y `node --check`. Los módulos `*.js` puros se prueban con Node desde pytest.

## Mapa
Backend (`app/`, FastAPI síncrono, psycopg3):
- `main.py` rutas y dependencias (`anestesiologo_actual`, `admin_actual`, `cupo_ia`) · `config.py` variables de entorno
- `repositorio.py` toda la SQL de cirugías, pacientes, pagos, cuentas, auditoría · `modelos.py` modelos pydantic
- `extraccion.py` IA: órdenes, reportes de pago, relaciones/radicados, volantes (`_llamar_claude`) · `uso_ia.py` tokens y costo
- `radicado.py` radicados de Santa Ana: crear faltantes, vincular líneas · `cartera.py` Inicio y línea de cobro
- `liquidacion.py` volante de AP · `finanzas.py` + `extractos.py` finanzas personales y extractos del banco
- `noticias.py` boletín/historias · `catalogo.py` CUPS · `calidad.py` «¿Qué te faltó?» · `validacion.py` bitácora TIVA
- Seguridad: `auth.py` (scrypt, sesión) · `dospasos.py` (TOTP) · `seguridad.py` (cabeceras, CSRF, Excel) · `correo.py` · `copia.py`
- `inicio.py` arranque: crea tablas, aplica migraciones, RLS, admin · `almacenamiento.py` fotos (Supabase/carpeta)

Base: `db/schema.sql` debe tener TODO (las pruebas parten de él); `db/migraciones.sql` es idempotente y se aplica sola al cambiar.
Toda tabla nueva va en los dos archivos.

Frontend: una sola página `app/static/index.html` (~5500 líneas); secciones marcadas con `// ----` en el `<script>`:
formulario, escáner de la foto, pestañas, inicio, pagos, liquidación, relación, reportes, finanzas, extractos, noticias,
infusiones, TIVA, regional, cuenta, visor, dos pasos. Otras páginas: `login.html`, `restablecer.html`, `legal/`.
Módulos puros (sin servidor): `infusiones.js`, `tiva.js`, `regional.js`, `escaner.js`.

## Convenciones
- Todo dato se filtra por `anestesiologo_id` (prueba de aislamiento en `tests/test_seguridad.py`).
- Cambios que modifican datos: auditar con `repositorio.auditar` si son de seguridad o administración.
- La app muestra «Versión xxxxxxx» (commit desplegado) al final de las pantallas.
- Informe de seguridad y pendientes: `docs/SEGURIDAD.md`.
