# Seguridad de Auditorías AP

Informe de la revisión de seguridad (octubre 2026) y lo que queda por hacer. Los datos de pacientes son datos
sensibles de salud (Ley 1581 de 2012, habeas data): la app los trata con ese nivel de cuidado.

## Ya cubierto

| Área | Qué hay |
|---|---|
| Contraseñas | scrypt con sal; mínimo 10 caracteres; claves temporales de un solo uso; el hash nunca sale del servidor |
| Sesión | Cookie firmada (HMAC), `HttpOnly`, `SameSite=Lax`, `Secure` en Render; 30 días; se cierran todas al cambiar o restablecer la clave |
| Fuerza bruta | Bloqueo por cuenta (5 fallos → 15 min, se duplica hasta 24 h), límite por conexión, pausa de 1 s, tiempo de respuesta igual con correo inexistente |
| Recuperación | Enlace de un solo uso, vence en 60 min, se guarda solo su hash, respuesta igual exista o no el correo |
| Autorización | Todas las rutas con datos exigen sesión; las de administración exigen administrador; **cada consulta filtra por el anestesiólogo** (prueba automática recorre todas las rutas con identificadores ajenos) |
| Aislamiento | Pacientes y coberturas por anestesiólogo; Supabase con RLS activado en todas las tablas y bucket privado |
| Navegador | CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS; respuestas de la API sin caché |
| CSRF | `SameSite=Lax` + rechazo de peticiones que cambian datos con `Origin` de otro sitio |
| Subidas | Tipo por contenido (no por nombre), tope de tamaño; las imágenes de regional se reconvierten y se les quita el EXIF |
| Excel | Los textos que empiezan con `= + - @` se neutralizan (inyección de fórmulas) |
| API | Documentación (`/docs`, `/openapi.json`) cerrada; sin SQL armado con datos del usuario (consultas parametrizadas) |
| Costos | Tope de 80 lecturas con IA por anestesiólogo cada 24 h (`MAX_LECTURAS_IA_DIA`) |
| Auditoría | Bitácora (`auditoria`): entradas, fallos, bloqueos, cambios de clave, copias, exportaciones, cuentas |
| Dependencias | `pip-audit`: sin vulnerabilidades conocidas |
| Copias | .zip cifrado AES-256 con clave del administrador |

## Pendiente (en orden de importancia)

1. **Autenticación en dos pasos** (correo o app) para el administrador: su cuenta ve todo y puede descargar la copia.
2. **Supabase**: revisar que el proyecto tenga copias automáticas (plan Pro) y que `SUPABASE_SERVICE_KEY` solo esté en Render. Si alguna vez se pegó en un chat o captura, rotarla.
3. **Datos enviados a la IA**: las fotos y textos de órdenes salen hacia Anthropic. Confirmar en las condiciones de la API la retención y el no uso para entrenamiento, y reflejarlo en la política de privacidad (transferencia internacional de datos).
4. **Textos legales**: completar razón social, NIT y correo en `terminos.html` y `privacidad.html`, con revisión de un abogado; registrar el tratamiento ante la SIC si aplica.
5. **Límites por conexión**: Render pasa la IP real en `X-Forwarded-For`; verificar cuál posición es confiable antes de apoyarse en los límites por IP (el bloqueo por cuenta no depende de esto).
6. **CSP más estricta**: hoy permite `'unsafe-inline'` en scripts porque la app tiene el código dentro de la página; mover el código a archivos y usar *nonces* eliminaría ese riesgo.
7. **Retención**: definir cuánto se guardan fotos, bitácora y copias, y cómo se borran los datos de quien se va.
8. **Plan de incidentes**: a quién avisar y qué hacer si se filtran datos (la ley exige reportar a la SIC).

## Cómo probar

`.venv/bin/python -m pytest -q tests/test_seguridad.py`
