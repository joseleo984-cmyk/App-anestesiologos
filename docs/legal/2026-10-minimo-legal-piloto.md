# Mínimo legal para el piloto con AP, vacíos de los textos y preguntas al abogado y al contador

**Borrador del agente de legal para José, 18 de octubre de 2026.** No es asesoría jurídica: lo revisa un abogado
colombiano (lo tributario, un contador). Marcas: **[EXIGE]** lo pide la ley · **[BP]** buena práctica ·
**[OPINIÓN]** criterio del agente · **⚠ verificar** número, plazo o vigencia por confirmar con el abogado o en
la fuente oficial (SIC, DIAN, INVIMA, Secretaría del Senado). Esta versión no se contrastó en línea: todo
número de circular o de artículo reglamentario va como «verificar».

Lo que revisé: `docs/agentes/legal.md`, `docs/SEGURIDAD.md`, `app/static/legal/terminos.html`,
`app/static/legal/privacidad.html`, las casillas de registro (`app/static/login.html`) y de nueva aceptación
(`app/static/index.html`), y las rutas de administrador (`app/main.py`).

**Idea central:** que el piloto sea gratis no cambia nada en datos personales. Desde el primer anestesiólogo que
sube una orden real hay tratamiento de datos sensibles de salud de terceros (los pacientes), y la Ley 1581 de
2012 aplica completa.

---

## 1. Lista mínima para arrancar el piloto (finales de octubre)

### A. Obligatorio antes de subir datos reales

| # | Qué | Norma | Estado hoy |
|---|---|---|---|
| A1 | **Definir quién es el responsable** (persona natural José o la SAS) y poner nombre o razón social, identificación (CC o NIT), domicilio, dirección, correo y teléfono en la política. Si la SAS no existe a tiempo, el piloto puede arrancar a nombre de José como persona natural y cederse después (⚠ verificar con el abogado cómo hacer esa cesión sin pedir otra autorización). | Ley 1581 de 2012, art. 17 y 18; Decreto 1377 de 2013, art. 13 (compilado en Decreto 1074 de 2015, art. 2.2.2.25.3.1, ⚠ verificar numeración) | Falta: «[razón social, NIT…]» |
| A2 | **Política de tratamiento completa**: además de lo que tiene, el **procedimiento** para consultas y reclamos, el **área o persona** que los atiende, la **fecha de vigencia** de la política y el **periodo de vigencia de la base de datos**. | Decreto 1377 de 2013, art. 13; Ley 1581, arts. 14 y 15 (consultas 10 días hábiles prorrogables 5; reclamos 15 prorrogables 8) | Parcial |
| A3 | **Autorización del anestesiólogo** previa, expresa e informada, **con prueba guardada**. Para datos sensibles (sus finanzas personales y extractos no lo son, pero hay que decirle que responder sobre datos sensibles es facultativo y qué datos sensibles se tratan). | Ley 1581, arts. 6, 9 y 12; Decreto 1377, arts. 5, 6, 7 y 8 | La app ya guarda fecha y versión (bien). Falta el aviso de facultatividad |
| A4 | **Contrato de transmisión de datos** entre cada anestesiólogo (responsable de los datos de sus pacientes) y la app (encargada). Puede ir como cláusula aceptada en línea dentro de los términos (⚠ verificar con el abogado si basta la aceptación electrónica). | Decreto 1377, art. 25 (Decreto 1074, art. 2.2.2.25.5.2, ⚠ verificar); Ley 527 de 1999, arts. 14 y 15 (validez del contrato electrónico) | **No existe** |
| A5 | **Contratos de encargo con los proveedores** (Render, Supabase, Anthropic, correo): aceptar sus DPA o anexos de tratamiento y guardarlos. Confirmar región de Supabase. | Ley 1581, arts. 17 lit. d y 18; Decreto 1377, arts. 24 y 25 | Por revisar |
| A6 | **Cuidado con los datos de pacientes**: dejar escrito en los términos que el anestesiólogo es el responsable frente a sus pacientes y que solo sube órdenes de pacientes que atendió, para cobrar sus honorarios. Revisar con el abogado la base legal (ver pregunta L1). | Ley 1581, arts. 5, 6 y 3 lit. d y e; Ley 23 de 1981, art. 37 (secreto profesional) | Parcial (cláusula 3) |
| A7 | **Seguridad y plan de incidentes mínimo**: quién decide, cómo se avisa al anestesiólogo afectado y el **reporte a la SIC**. | Ley 1581, art. 17 lit. d y n, y art. 18 lit. k; reporte en el RNBD dentro de 15 días hábiles (Circular Única SIC, Título V, ⚠ verificar plazo y si aplica a quien no está obligado al RNBD) | Pendiente 8 de `SEGURIDAD.md` |
| A8 | **Quién es el administrador y qué ve.** El administrador puede descargar la **copia de toda la base** (`/api/copia-seguridad`), con los pacientes de todos. Si es una persona de AP, AP tendría acceso al detalle por paciente, lo que contradice «AP solo ve totales». Mínimo: acuerdo de confidencialidad firmado por quien administre y decirlo en la política. | Ley 1581, art. 4 lit. f (acceso restringido) y lit. h (confidencialidad); Ley 23 de 1981, art. 37 | **No cubierto** |
| A9 | **Uso del nombre «AP»**: «Auditorías AP» usa el nombre de la asociación. Para el piloto, autorización escrita de AP (puede ir en la carta de piloto, punto B1). | Decisión 486 de 2000 de la CAN, art. 155 (si AP tiene la marca registrada, ⚠ verificar en la SIC); Ley 256 de 1996 (competencia desleal, confusión) | Sin autorización escrita conocida |

### B. Muy recomendable para el piloto

| # | Qué | Norma / motivo |
|---|---|---|
| B1 | **Carta o convenio corto de piloto con AP**: duración (2 meses, 30 usuarios), gratis, qué ve AP (solo totales), que AP no recibe datos de pacientes, confidencialidad, uso del nombre, qué pasa con los datos al terminar, sin obligación de compra. | [BP]. Evita que AP quede como responsable o encargado sin contrato (Ley 1581, art. 3 lit. d y e) |
| B2 | **Herramientas clínicas (TIVA, infusiones, bloqueos)**: en el piloto, mostrarlas como «en validación, solo educativo» o apagarlas, y no declarar que «calculan la dosis del paciente». El riesgo depende del uso previsto. | Decreto 4725 de 2005, art. 2 (definición de dispositivo médico, incluye software, ⚠ verificar si INVIMA tiene guía vigente de software como dispositivo médico) |
| B3 | **Retención y borrado**: decir qué se borra si el anestesiólogo se va o si el piloto no sigue (fotos de órdenes, bitácora, copias) y en qué plazo. | Ley 1581, art. 4 lit. b (finalidad); Decreto 1377, art. 11 (temporalidad) |
| B4 | **Casilla aparte para la transmisión al exterior y la lectura con IA**, y el mismo texto completo en la ventana de nueva aceptación (hoy esa ventana no menciona los proveedores). | Ley 1581, art. 12 (deber de informar); [BP] |
| B5 | **Confirmar con Anthropic** retención y no uso para entrenamiento de los datos de la API, y escribirlo en la política. | Ley 1581, art. 4 lit. b y art. 12; pendiente 3 de `SEGURIDAD.md` |
| B6 | **2FA obligatoria para el administrador** antes de cargar datos reales (`EXIGIR_2FA_ADMIN=si`). | Ley 1581, art. 4 lit. g (seguridad) |

### C. Puede esperar (antes de cobrar o de abrir a otros grupos)

| # | Qué | Norma |
|---|---|---|
| C1 | Constituir la SAS | Ley 1258 de 2008 |
| C2 | Términos de suscripción: precio, renovación, cancelación, reembolso, retracto | Ley 1480 de 2011, arts. 5 num. 3 (quién es consumidor), 47 (retracto, ventas a distancia) y 50 (comercio electrónico) |
| C3 | Facturación electrónica y pasarela Wompi | Estatuto Tributario, arts. 615 y 616-1; Resolución DIAN 000165 de 2023 (⚠ verificar vigencia) |
| C4 | Autorización escrita para el descuento en el volante de AP | Ver pregunta L6 |
| C5 | Registro de la nueva marca (hacer la búsqueda de antecedentes antes de escoger nombre) | Decisión 486 de 2000, arts. 134 y siguientes |
| C6 | RNBD: probablemente **no obligatorio** al inicio (aplica a sociedades con activos de más de 100.000 UVT). Revisar cuando crezca. | Decreto 090 de 2018 (modifica el Decreto 1074 de 2015, art. 2.2.2.26.1.2, ⚠ verificar) |
| C7 | Contrato de transmisión con AP si algún día AP ve detalle por paciente | Decreto 1377, art. 25 |

---

## 2. Vacíos y riesgos de los textos actuales (en orden de gravedad)

1. **No hay responsable identificado** (`privacidad.html` §1, `terminos.html` §1 y §8). Sin nombre, identificación ni
   correo la política no cumple y nadie puede ejercer sus derechos. [EXIGE] Decreto 1377, art. 13.
2. **Se dice «transferencia» cuando es «transmisión»** (`privacidad.html` §4). Render, Supabase y Anthropic procesan
   por cuenta de la app: eso es transmisión a encargados, que se ampara con contrato de transmisión, no con la
   autorización del titular. Y la autorización del anestesiólogo **no puede autorizar la salida de datos de sus
   pacientes**: ellos no aceptaron nada. [EXIGE] Ley 1581, art. 26 y Decreto 1377, arts. 24 y 25. Sobre EE. UU.:
   la SIC lo incluyó entre los países con nivel adecuado (Circular Externa 005 de 2017, ⚠ verificar vigencia y
   condiciones).
3. **No hay contrato de transmisión anestesiólogo → app** para los datos de pacientes. La política dice que «la app
   los trata por tu cuenta» (bien dicho), pero falta el contrato con el contenido mínimo: tratar solo según
   instrucciones, seguridad, confidencialidad. [EXIGE] Decreto 1377, art. 25.
4. **«Mejorar esa lectura»** (`privacidad.html` §3) es ambiguo: puede leerse como uso de órdenes de pacientes para
   entrenar o ajustar la IA. Hay que decir exactamente qué se hace (por ejemplo, contar qué campos se corrigen,
   sin guardar copias aparte) o quitarlo. [EXIGE] Ley 1581, art. 4 lit. b y c (finalidad y libertad).
5. **Acceso del administrador y de AP no se menciona.** La política dice que «cada anestesiólogo ve solo sus
   datos», pero el administrador puede descargar la base completa. Si el administrador es de AP, es una
   comunicación de datos de salud a un tercero. [EXIGE] Ley 1581, art. 4 lit. f; Ley 23 de 1981, art. 37.
6. **Datos sensibles sin el aviso de facultatividad** ni casilla específica. [EXIGE] Ley 1581, art. 6 lit. a;
   Decreto 1377, art. 6.
7. **Faltan el procedimiento de consultas y reclamos, el área responsable y las fechas de vigencia.** Los plazos ya
   están bien (10 y 15 días hábiles), pero faltan las prórrogas (5 y 8 días hábiles). [EXIGE] Ley 1581, arts. 14
   y 15; Decreto 1377, art. 13.
8. **Conservación indefinida** («mientras la cuenta esté activa y lo que exijan las normas»): no dice qué normas ni
   cuánto tiempo, ni qué pasa con las fotos de órdenes y las copias. [EXIGE] Decreto 1377, art. 11.
9. **Finanzas personales y extractos bancarios**: se mencionan como «finanzas personales que registres», pero no
   está claro que se suben extractos, que la IA los lee ni que salen del país. [EXIGE] Ley 1581, art. 12.
10. **Términos sin las cláusulas básicas**: ley aplicable y jurisdicción, límite de responsabilidad (y sus topes
    legales), qué pasa con los datos al cerrar la cuenta y cómo exportarlos, propiedad intelectual de la app,
    condiciones del piloto. [BP]; el límite de responsabilidad debe revisarse con el Código Civil, art. 1616, y,
    si fueran consumidores, con la Ley 1480, art. 43 (cláusulas abusivas).
11. **Calculadoras clínicas**: el descargo de la cláusula 5 está bien escrito, pero no reemplaza la revisión
    regulatoria si el uso previsto es calcular dosis para un paciente. [OPINIÓN] riesgo medio. Decreto 4725 de
    2005.
12. **El aviso de borrador dice «antes de abrir a anestesiólogos fuera de AP»**: da a entender que con AP basta el
    borrador. [OPINIÓN] para el piloto con datos reales ya hace falta la versión revisada.
13. **Sin aviso a los pacientes.** No hay forma práctica de avisarles desde la app; hay que definir con el abogado
    si basta la autorización que dan en la clínica o si el anestesiólogo debe informarles de otra forma. Ver L1.

---

## 3. Preguntas priorizadas

### Para el abogado

**Antes del piloto (urgentes)**

- **L1. Base legal para los datos de pacientes.** ¿Con qué base puede el anestesiólogo tratar (y transmitir a la app
  y a proveedores en EE. UU.) los datos de salud de sus pacientes para cobrar honorarios? ¿Basta la relación
  médico-paciente y la autorización que se da en la clínica, o hace falta otra? (Ley 1581, arts. 6 y 10; Ley 23
  de 1981, arts. 37 y 38.)
- **L2. Roles.** ¿Confirma que el anestesiólogo es responsable de los datos de sus pacientes y la app es encargada,
  y que la app es responsable de los datos del propio anestesiólogo? ¿AP qué papel tiene? (Ley 1581, art. 3
  lit. d y e.)
- **L3. Contrato de transmisión en línea.** ¿Puede ir como cláusula aceptada con casilla, o debe ser un documento
  aparte? ¿Qué contenido mínimo? (Decreto 1377, art. 25; Ley 527 de 1999.)
- **L4. Proveedores en EE. UU.** ¿Es transmisión (con contrato) y no transferencia? ¿Sigue vigente la Circular
  005 de 2017 con EE. UU. como país adecuado? ¿Bastan los DPA estándar de Render, Supabase y Anthropic?
- **L5. Responsable mientras no exista la SAS.** ¿Arrancamos a nombre de José como persona natural? ¿Cómo se
  traspasa la base a la SAS después? (Ley 1581, art. 26 y circulación de bases.)
- **L6. Administrador y AP.** Si el administrador es empleado de AP, ¿qué documento hace falta? ¿Recomienda que el
  administrador no sea de AP?
- **L7. Uso del nombre «AP».** ¿Basta una carta de AP para el piloto? ¿Riesgo con el nombre definitivo?
- **L8. ¿Las órdenes y datos que guarda la app hacen parte de la historia clínica?** Si sí, ¿qué obligaciones de
  custodia y conservación aplican? (Resolución 1995 de 1999; Ley 2015 de 2020.)

**Antes de cobrar**

- **L9. Descuento en el volante.** ¿Qué forma debe tener la autorización del anestesiólogo para que AP le descuente
  la suscripción? ¿Aplica la Ley 1527 de 2012 (libranza) o basta una autorización bajo el contrato sindical
  (Código Sustantivo del Trabajo, art. 482 y siguientes; Decreto 1072 de 2015)? ⚠ verificar.
- **L10. ¿El anestesiólogo es consumidor?** ¿Aplican retracto y reglas de renovación automática? (Ley 1480, arts. 5
  num. 3 y 47.)
- **L11. Calculadoras clínicas.** ¿Con qué uso previsto quedan fuera de dispositivo médico? ¿Hace falta concepto o
  consulta al INVIMA? (Decreto 4725 de 2005.)
- **L12. Límite de responsabilidad** razonable para errores de lectura con IA o de liquidación.
- **L13. RNBD y reporte de incidentes** si no estamos obligados a registrar: ¿cómo se reporta un incidente a la SIC?
  (Decreto 090 de 2018; Circular Única SIC.)

### Para el contador

1. **C1. Tipo de sociedad y régimen**: SAS en régimen ordinario o Régimen Simple de Tributación. (Ley 1258 de
   2008; Estatuto Tributario, arts. 903 y siguientes.)
2. **C2. IVA de la suscripción**: ¿está excluida como servicio de computación en la nube o es gravada al 19 %?
   (Estatuto Tributario, art. 476, numeral de cloud computing, ⚠ verificar numeral y requisitos vigentes.) ¿Desde
   cuándo seríamos responsables de IVA? (Estatuto Tributario, art. 437, parágrafo 3, umbral de 3.500 UVT.)
3. **C3. Pagos al exterior** (Render, Supabase, Anthropic): retención en la fuente e IVA por servicios del exterior.
   (Estatuto Tributario, arts. 408 y 437-2, ⚠ verificar.)
4. **C4. Facturación electrónica**: desde cuándo, con qué proveedor, factura a cada anestesiólogo o a AP según el
   modelo, y cómo funciona si se descuenta en el volante. (Estatuto Tributario, arts. 615 y 616-1; Resolución
   DIAN 000165 de 2023, ⚠ verificar.)
5. **C5. Descuento en el volante**: ¿AP actúa como recaudador por cuenta de la SAS? ¿Implica retenciones o
   ingresos para terceros en la contabilidad de AP?
6. **C6. Wompi**: tratamiento de comisiones y retenciones que aplica la pasarela.
7. **C7. Piloto gratis**: ¿hay que facturar o registrar algo por un servicio gratuito de 2 meses?

---

## Datos que necesito de José

- ¿A nombre de quién arranca el piloto (persona natural o SAS)? Correo y teléfono de contacto para la política.
- ¿Quién es el administrador? ¿Trabaja para AP?
- Proveedor de correo y región del proyecto de Supabase.
- ¿AP autorizó por escrito el uso del nombre?
- ¿Se van a mostrar las calculadoras clínicas en el piloto?
