# Contrato de transmisión de datos personales (anestesiólogo → plataforma)

**Borrador para revisión del abogado, 18 de octubre de 2026.** No usar con datos reales hasta que lo apruebe un
abogado colombiano. Los campos entre corchetes `[ ]` faltan. ⚠ marca puntos por verificar.

Base normativa: Ley 1581 de 2012 (arts. 3 lit. d y e, 4, 17, 18 y 25); Decreto 1377 de 2013, arts. 24 y 25
(compilado en el Decreto 1074 de 2015, arts. 2.2.2.25.5.1 y 2.2.2.25.5.2, ⚠ verificar numeración); Ley 527 de
1999, arts. 14 y 15 (contratos por medios electrónicos).

---

## Contrato de transmisión de datos personales

**Versión:** {VERSION}

Este contrato se celebra entre:

- **El RESPONSABLE:** el médico anestesiólogo titular de la cuenta, identificado con los datos registrados en ella,
  que lo acepta por medios electrónicos al marcar la casilla correspondiente en la plataforma.
- **El ENCARGADO:** [razón social o nombre], identificado con [NIT o cédula], domiciliado en [ciudad y dirección],
  correo [correo], que administra la plataforma [nombre de la app] (en adelante, «la plataforma»).

### 1. Objeto

El RESPONSABLE transmite al ENCARGADO los datos personales de sus pacientes que contienen las órdenes, reportes de
pago, radicados y demás documentos que sube a la plataforma, para que el ENCARGADO los trate **por cuenta y según
las instrucciones del RESPONSABLE**, únicamente con las finalidades de la cláusula 3.

Este contrato no cubre los datos personales del propio anestesiólogo, que la plataforma trata como responsable
según su política de tratamiento de datos.

### 2. Datos transmitidos

- Datos de identificación del paciente: nombre, tipo y número de documento.
- Datos de salud (datos sensibles, Ley 1581 de 2012, art. 5): procedimiento, diagnóstico o información clínica que
  aparezca en la orden, clínica y fechas de atención.
- Datos de aseguramiento y cobro: aseguradora o entidad pagadora, número de orden o autorización, valores.
- Las imágenes y archivos PDF de los documentos que contienen esos datos.

### 3. Finalidades y actividades autorizadas

El ENCARGADO solo podrá:

1. Recibir, guardar y mostrar al RESPONSABLE los documentos y datos que este sube.
2. Leer los documentos con herramientas de inteligencia artificial para extraer los datos de la cirugía.
3. Cruzar las cirugías con los reportes de pago, radicados y volantes del RESPONSABLE, y calcular las liquidaciones.
4. Generar los reportes y exportaciones que el RESPONSABLE pida.
5. Hacer copias de seguridad cifradas y mantener registros de seguridad (bitácora).
6. Calcular estadísticas internas de calidad de la lectura (por ejemplo, qué campos se corrigen más), **sin
   identificar pacientes** y sin conservar copias adicionales de sus datos. ⚠ verificar con el abogado si esta
   finalidad debe quedar o retirarse.

El ENCARGADO **no** usará los datos para fines propios ni de terceros, no los venderá, no los cederá, no los usará
para entrenar modelos de inteligencia artificial ni los comunicará a la asociación o agremiación del RESPONSABLE
(incluida Anestesiólogos Permanentes), salvo instrucción escrita del RESPONSABLE.

### 4. Obligaciones del ENCARGADO

De acuerdo con la Ley 1581 de 2012, art. 18, y el Decreto 1377 de 2013, art. 25, el ENCARGADO se obliga a:

1. Tratar los datos según los principios de la Ley 1581 de 2012, art. 4, y solo según las instrucciones de este
   contrato.
2. **Seguridad:** mantener medidas técnicas, humanas y administrativas para evitar la adulteración, pérdida,
   consulta, uso o acceso no autorizado. Como mínimo: conexión cifrada, contraseñas guardadas con función de
   derivación (hash), verificación en dos pasos para administradores, separación de los datos de cada
   anestesiólogo, bitácora de accesos y copias cifradas.
3. **Confidencialidad:** guardar reserva sobre los datos, también después de terminado este contrato. Solo tendrán
   acceso las personas del ENCARGADO que lo necesiten para operar, dar soporte o restaurar copias, y todas habrán
   firmado un acuerdo de confidencialidad.
4. **Incidentes:** informar al RESPONSABLE, sin demora y a más tardar en [72 horas] desde que lo conozca, cualquier
   incidente de seguridad que afecte sus datos, con lo ocurrido, los datos afectados y las medidas tomadas; y
   reportarlo a la Superintendencia de Industria y Comercio en lo que le corresponda (Ley 1581, art. 18 lit. k).
   ⚠ verificar el plazo con el abogado.
5. **Apoyo con los titulares:** ayudar al RESPONSABLE a responder las consultas y reclamos de sus pacientes dentro
   de los plazos de la Ley 1581, arts. 14 y 15, y avisarle dentro de [2 días hábiles] si un paciente se dirige
   directamente al ENCARGADO.
6. **Información:** entregar al RESPONSABLE, cuando la pida, la información razonable para comprobar el cumplimiento
   de este contrato.

### 5. Subencargados y ubicación de los datos

El RESPONSABLE autoriza al ENCARGADO a apoyarse en los siguientes proveedores, que tratan los datos por cuenta del
ENCARGADO y con obligaciones de seguridad y confidencialidad equivalentes a las de este contrato:

| Proveedor | Servicio | Ubicación |
|---|---|---|
| Render | Servidor de la aplicación | Estados Unidos |
| Supabase | Base de datos y archivos | [región, ⚠ verificar] |
| Anthropic | Lectura de documentos con inteligencia artificial | Estados Unidos |
| [Proveedor de correo] | Envío de correos de servicio (no contiene datos de pacientes) | [⚠ verificar] |

El RESPONSABLE acepta que esto implica la **transmisión internacional** de los datos a esos países (Decreto 1377 de
2013, arts. 24 y 25). El ENCARGADO informará en la plataforma, con [30 días] de anticipación, cualquier cambio de
proveedor; si el RESPONSABLE no está de acuerdo, puede terminar este contrato según la cláusula 8.

### 6. Obligaciones del RESPONSABLE

El RESPONSABLE declara y se obliga a:

1. Subir solo documentos de pacientes que haya atendido personalmente, con la finalidad de controlar y cobrar sus
   honorarios profesionales.
2. Contar con una base legal para tratar esos datos y para transmitirlos a la plataforma (Ley 1581 de 2012, arts. 6
   y 9). ⚠ el abogado debe definir cuál es esa base (pregunta L1).
3. No subir más información de la necesaria (por ejemplo, historias clínicas completas, resultados de laboratorio o
   documentos de pacientes ajenos).
4. Atender las consultas y reclamos de sus pacientes, con apoyo del ENCARGADO.
5. Guardar en reserva su contraseña y activar la verificación en dos pasos cuando la plataforma la ofrezca.
6. Cumplir el secreto profesional (Ley 23 de 1981, art. 37).

### 7. Conservación, devolución y supresión

1. Los datos se conservan mientras la cuenta del RESPONSABLE esté activa.
2. Al terminar el contrato, el RESPONSABLE tiene [30 días] para descargar sus datos (exportación a Excel y archivos
   originales).
3. Vencido ese plazo, el ENCARGADO suprimirá los datos de la base activa y las copias de seguridad se borrarán al
   cumplir su ciclo de rotación, que no superará [90 días]. Solo conservará lo que una norma le obligue a guardar,
   en cuyo caso lo indicará. ⚠ verificar plazos con el abogado y con la política de retención.

### 8. Duración y terminación

Este contrato rige desde su aceptación y mientras la cuenta esté activa. Termina cuando el RESPONSABLE cierra su
cuenta, cuando el ENCARGADO la cancela por uso indebido o cuando deja de prestar el servicio. Las obligaciones de
confidencialidad y supresión siguen vigentes después de la terminación.

### 9. Cambios

Si este contrato cambia, la plataforma pedirá aceptarlo de nuevo antes de seguir usándola. Se conservan la versión
y la fecha de cada aceptación.

### 10. Ley aplicable y aceptación electrónica

Este contrato se rige por la ley colombiana. Se celebra por medios electrónicos y tiene plena validez conforme a la
Ley 527 de 1999, arts. 14 y 15. La plataforma conserva como prueba la versión aceptada, la fecha y hora, y la
cuenta que aceptó (Decreto 1377 de 2013, art. 8). [Jurisdicción o mecanismo de solución de controversias, ⚠ definir
con el abogado.]

---

## Notas para el abogado

- **Partes.** Supone que el anestesiólogo es el responsable de los datos de sus pacientes y la plataforma su
  encargada. Si el abogado concluye otra cosa (por ejemplo, que AP o la clínica son responsables), hay que rehacer
  las partes.
- **Aceptación con casilla.** ¿Basta para un contrato de transmisión, o conviene firma electrónica (Decreto 2364 de
  2012, compilado en el Decreto 1074 de 2015)? ⚠ verificar.
- **Plazos entre corchetes** (72 horas, 2 días, 30 días, 90 días): son propuestas del agente [OPINIÓN].
- **Finalidad 6 (estadísticas de calidad):** confirmar si se puede dejar.
- **Administrador:** la cláusula 4.3 obliga a que quien administre firme confidencialidad. Si es una persona de AP,
  revisar si es compatible con la cláusula 3 (AP no ve datos de pacientes).
