# Cambios propuestos en la app para A4 (contrato de transmisión) y A6 (datos de pacientes)

**Para la sesión de desarrollo.** Propuesta del agente de legal, 18 de octubre de 2026. Los textos son borradores:
se publican con datos reales solo después de la revisión del abogado.

## A4. Aceptar el contrato de transmisión en la app

Hoy una sola versión (`TERMINOS_VERSION`) cubre términos y política, y se guarda con fecha. Se propone sumar el
contrato a ese mismo mecanismo, con su propia casilla, para que quede prueba de que se aceptó
(Decreto 1377 de 2013, art. 8; Ley 527 de 1999, art. 14).

1. **Página nueva** `app/static/legal/transmision.html`, con la misma plantilla de `terminos.html` y el texto de
   `docs/legal/contrato-transmision.md` (sin la sección «Notas para el abogado»). Servirla en `/transmision` con
   `_pagina_legal("transmision")` (`app/main.py:486`), que ya reemplaza `{VERSION}`.
2. **Registro** (`app/static/login.html`, después de la casilla `r-autoriza`): una tercera casilla obligatoria.
   > Acepto el [contrato de transmisión de datos](/transmision) para los datos de mis pacientes: la app los trata
   > solo por mi cuenta, para registrar y cobrar mis cirugías.

   En el servidor, sumar `acepta_transmision: bool = False` a `Registro` (`app/main.py:466`) y exigirlo junto con
   los otros dos (`app/main.py:514`).
3. **Nueva aceptación** (`app/static/index.html`, ventana `capa-terminos`): la misma tercera casilla, y que
   «Aceptar y continuar» se habilite solo con las tres. Corregir de paso el texto de `acepto-datos` para que
   mencione los proveedores en el exterior, como en el registro.
4. **Versión:** al publicar, subir `TERMINOS_VERSION` (`app/config.py:26`). Así todos, incluidas las cuentas ya
   creadas, verán la ventana y aceptarán el contrato al entrar.
5. **Archivo de versiones:** guardar una copia de los tres textos de cada versión publicada (por ejemplo,
   `docs/legal/versiones/<versión>/`), para poder probar qué texto exacto aceptó cada quien. [BP]
6. **Pruebas:** que el registro sin `acepta_transmision` responda 422, y que `/transmision` muestre la versión.

## A6. Que el anestesiólogo asuma la responsabilidad frente a sus pacientes

Se propone cubrirlo en tres capas. Ninguna exige casillas en cada subida.

### 1. Cláusula en los términos (reemplaza la §3 de `terminos.html`)

> **3. Datos de tus pacientes**
>
> Las órdenes y reportes que subes contienen datos de salud de tus pacientes, que son datos sensibles (Ley 1581 de
> 2012, art. 5). Frente a tus pacientes, **tú eres el responsable** de esos datos y la app es tu **encargada**: los
> trata solo por tu cuenta y según el contrato de transmisión que aceptas al usar la app.
>
> Al subir un documento declaras que:
> - el paciente fue atendido por ti y lo subes solo para registrar y cobrar tus honorarios;
> - tienes una base legal para tratar y transmitir esos datos [⚠ texto exacto según el abogado, pregunta L1];
> - no subes más de lo necesario (no historias clínicas completas ni documentos de pacientes ajenos);
> - guardas el secreto profesional sobre esa información (Ley 23 de 1981, art. 37).
>
> Si un paciente te pide conocer, corregir o suprimir sus datos, la app te ayuda a responder dentro de los plazos
> de ley. Cada anestesiólogo ve únicamente sus propios registros; la asociación no ve datos de tus pacientes.

### 2. Recordatorio en la pantalla de subir orden

Una línea fija, sin casilla, debajo del texto de ayuda (`app/static/index.html:682`):

> Sube solo órdenes de pacientes que atendiste. Son datos de salud: la app los usa solo para tus cobros.

[BP] Recuerda la obligación en el momento en que se usa, sin entorpecer.

### 3. Fuera de la app: informar a los pacientes [⚠ depende de la respuesta del abogado a L1]

La app no tiene contacto con los pacientes. Si el abogado concluye que hay que informarles, la vía práctica es el
consentimiento o el aviso de privacidad que el paciente ya firma en la clínica o con AP, con una frase como:

> Sus datos de identificación, aseguramiento y del procedimiento podrán ser tratados por su anestesiólogo y por los
> proveedores tecnológicos que este contrate, incluso fuera de Colombia, para registrar y cobrar sus honorarios.

Esto se gestiona con AP y las clínicas, no en el código.

### Relacionado (B3, retención)

Para reducir el riesgo, definir cuánto tiempo se guardan las **fotos** de las órdenes una vez se cruza el pago.
Los datos extraídos bastan para el control; la foto podría borrarse a los [X meses]. ⚠ definir con el abogado
y con José.
