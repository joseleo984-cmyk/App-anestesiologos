/* Anestesia regional: guía rápida de bloqueos (volúmenes, anestésico local, adyuvantes) y dosis máximas.
   Contenido orientativo que debe validar AP; las imágenes y la técnica detallada se consultan en NYSORA
   (enlace) o en las imágenes propias que suba AP. Sin servidor ni IA. */
(function (raiz) {
  "use strict";

  // Dosis máximas de referencia en adultos (mg/kg y tope en mg). con_epi: con epinefrina.
  // Fuentes habituales: ficha técnica, NYSORA, ASRA (LAST 2020), ESRA/ASRA pediatría (2018).
  const ANESTESICOS = [
    { id: "lidocaina", nombre: "Lidocaína", mgkg: 4.5, tope: 300, mgkgEpi: 7, topeEpi: 500, conc: [1, 1.5, 2], duracion: "1–2 h (2–3 h con epinefrina)" },
    { id: "mepivacaina", nombre: "Mepivacaína", mgkg: 5, tope: 400, mgkgEpi: 7, topeEpi: 550, conc: [1, 1.5, 2], duracion: "2–3 h" },
    { id: "bupivacaina", nombre: "Bupivacaína", mgkg: 2.5, tope: 175, mgkgEpi: 3, topeEpi: 225, conc: [0.25, 0.375, 0.5], duracion: "8–16 h" },
    { id: "levobupivacaina", nombre: "Levobupivacaína", mgkg: 2.5, tope: 150, mgkgEpi: 3, topeEpi: 150, conc: [0.25, 0.375, 0.5], duracion: "8–16 h" },
    { id: "ropivacaina", nombre: "Ropivacaína", mgkg: 3, tope: 225, mgkgEpi: 3, topeEpi: 225, conc: [0.2, 0.375, 0.5, 0.75], duracion: "6–12 h" },
    { id: "cloroprocaina", nombre: "Cloroprocaína", mgkg: 11, tope: 800, mgkgEpi: 14, topeEpi: 1000, conc: [2, 3], duracion: "30–60 min" },
  ];

  const LARGA = "Ropivacaína 0,375–0,5 % o bupivacaína/levobupivacaína 0,25–0,5 %";
  const PLANO = "Ropivacaína 0,2–0,375 % o bupivacaína 0,25 % (volumen alto: vigila la dosis total)";
  const DEXA = "Dexametasona 4–8 mg (perineural o IV) prolonga la analgesia; la vía IV tiene efecto similar.";

  // region: superior, inferior, tronco, cabeza, pediatria
  const BLOQUEOS = [
    // ---------------------------------------------------------- miembro superior
    { id: "interescalenico", nombre: "Interescalénico", region: "superior", nysora: "interscalene brachial plexus block",
      indicaciones: "Hombro, clavícula distal, húmero proximal.",
      tecnica: "Sonda lineal en el cuello, raíces C5–C7 entre escalenos anterior y medio. Paciente semisentado.",
      volumen: "5–15 mL (10 mL suele bastar)", ninos: "0,2–0,3 mL/kg",
      anestesico: LARGA, evidencia: "Ropivacaína y bupivacaína son igual de eficaces; volúmenes de 5–10 mL dan la misma analgesia que 20 mL.",
      adyuvantes: DEXA,
      precauciones: "Paresia diafragmática ipsilateral casi constante (incluso con 5 mL): evitar en EPOC severo o paresia contralateral; considerar tronco superior o supraescapular + axilar. Síndrome de Horner y ronquera frecuentes." },
    { id: "supraclavicular", nombre: "Supraclavicular", region: "superior", nysora: "supraclavicular brachial plexus block",
      indicaciones: "Brazo, codo, antebrazo y mano.",
      tecnica: "Sonda lineal en la fosa supraclavicular; plexo lateral a la arteria subclavia, sobre la primera costilla.",
      volumen: "20–30 mL", ninos: "0,2–0,5 mL/kg",
      anestesico: `${LARGA}. Para cirugía corta: mepivacaína 1,5 % o lidocaína 1,5–2 %.`,
      evidencia: "Bloqueo rápido y denso ('raquídea del brazo'). La inyección en el ángulo arteria–primera costilla mejora el bloqueo del cubital.",
      adyuvantes: DEXA,
      precauciones: "Neumotórax (ver la pleura siempre); paresia frénica en ~30–50 %." },
    { id: "infraclavicular", nombre: "Infraclavicular", region: "superior", nysora: "infraclavicular brachial plexus block",
      indicaciones: "Codo, antebrazo y mano; ideal para catéter.",
      tecnica: "Sonda lineal parasagital bajo la coracoides; cordones alrededor de la arteria axilar (inyección posterior a la arteria).",
      volumen: "20–30 mL", ninos: "0,2–0,5 mL/kg",
      anestesico: LARGA, evidencia: "Una sola inyección posterior a la arteria es tan eficaz como varias.", adyuvantes: DEXA,
      precauciones: "Vasos profundos: difícil comprimir si hay punción arterial." },
    { id: "axilar", nombre: "Axilar", region: "superior", nysora: "axillary brachial plexus block",
      indicaciones: "Antebrazo y mano (codo hacia distal).",
      tecnica: "Sonda lineal en la axila; mediano, cubital y radial alrededor de la arteria y el musculocutáneo entre bíceps y coracobraquial.",
      volumen: "15–25 mL (5–7 mL por nervio)", ninos: "0,2–0,4 mL/kg",
      anestesico: "Cirugía corta: lidocaína 1,5–2 % o mepivacaína 1,5 %. Analgesia larga: ropivacaína 0,5 % o bupivacaína 0,5 %.",
      evidencia: "Inyectar cada nervio por separado acorta la latencia. No bloquea el hombro.", adyuvantes: DEXA,
      precauciones: "Sin riesgo de paresia frénica ni neumotórax: buena opción en pacientes respiratorios." },
    { id: "supraescapular", nombre: "Supraescapular", region: "superior", nysora: "suprascapular nerve block",
      indicaciones: "Analgesia de hombro con poco compromiso diafragmático (asociar a axilar).",
      tecnica: "Anterior (bajo el omohioideo) o posterior (fosa supraespinosa).",
      volumen: "5–10 mL", ninos: "0,1–0,2 mL/kg",
      anestesico: LARGA, evidencia: "Combinado con el nervio axilar se acerca a la analgesia del interescalénico con menos paresia frénica.",
      adyuvantes: DEXA, precauciones: "La vía anterior con volumen alto también puede afectar el frénico." },
    { id: "antebrazo", nombre: "Nervios del antebrazo (mediano, cubital, radial)", region: "superior", nysora: "forearm nerve blocks",
      indicaciones: "Rescate de bloqueo incompleto; cirugía de mano.",
      tecnica: "Sonda lineal en el antebrazo, seguir cada nervio.",
      volumen: "3–5 mL por nervio", ninos: "0,05–0,1 mL/kg por nervio",
      anestesico: "Lidocaína 1–2 % o ropivacaína 0,5 %.", evidencia: "Útil para completar un bloqueo proximal parcial.",
      adyuvantes: "", precauciones: "Evitar inyección intraneural (dolor o resistencia: retirar)." },

    // ---------------------------------------------------------- miembro inferior
    { id: "fascia_iliaca", nombre: "Fascia ilíaca suprainguinal", region: "inferior", nysora: "fascia iliaca block",
      indicaciones: "Fractura de cadera, artroplastia de cadera, cirugía de muslo.",
      tecnica: "Sonda lineal parasagital sobre el ligamento inguinal; inyectar bajo la fascia ilíaca en dirección cefálica.",
      volumen: "30–40 mL", ninos: "0,5–1 mL/kg (máx. 30 mL)",
      anestesico: PLANO, evidencia: "Es un bloqueo de volumen: la difusión importa más que la concentración. En fractura de cadera disminuye el dolor y el uso de opioides.",
      adyuvantes: DEXA, precauciones: "Debilidad del cuádriceps: riesgo de caída." },
    { id: "peng", nombre: "PENG (grupo de nervios pericapsulares)", region: "inferior", nysora: "PENG block",
      indicaciones: "Cadera (fractura, artroplastia) preservando la fuerza.",
      tecnica: "Sonda curva sobre la eminencia iliopúbica, inyección entre el psoas y la rama púbica.",
      volumen: "20 mL", ninos: "0,3–0,5 mL/kg",
      anestesico: "Ropivacaína 0,375–0,5 % o bupivacaína 0,25 %.",
      evidencia: "Analgesia de cadera con menos debilidad del cuádriceps que la fascia ilíaca o el femoral.",
      adyuvantes: DEXA, precauciones: "Volumen mayor de 20 mL aumenta la debilidad motora." },
    { id: "femoral", nombre: "Femoral", region: "inferior", nysora: "femoral nerve block",
      indicaciones: "Fémur, rodilla anterior, rótula.",
      tecnica: "Sonda lineal en el pliegue inguinal, lateral a la arteria femoral, bajo la fascia ilíaca.",
      volumen: "15–20 mL", ninos: "0,2–0,4 mL/kg",
      anestesico: LARGA, evidencia: "Analgesia eficaz de rodilla pero con debilidad del cuádriceps; en rodilla se prefiere el canal aductor.",
      adyuvantes: DEXA, precauciones: "Riesgo de caída por debilidad del cuádriceps." },
    { id: "canal_aductor", nombre: "Canal aductor (safeno)", region: "inferior", nysora: "adductor canal block",
      indicaciones: "Artroplastia y artroscopia de rodilla; safeno para tobillo medial.",
      tecnica: "Sonda lineal en el tercio medio del muslo, bajo el sartorio junto a la arteria femoral.",
      volumen: "10–20 mL", ninos: "0,1–0,3 mL/kg",
      anestesico: "Ropivacaína 0,2–0,5 % o bupivacaína 0,25 %.",
      evidencia: "Analgesia de rodilla similar al femoral con mejor fuerza del cuádriceps y movilización temprana.",
      adyuvantes: DEXA, precauciones: "Inyecciones muy proximales se comportan como femoral." },
    { id: "ipack", nombre: "IPACK", region: "inferior", nysora: "IPACK block",
      indicaciones: "Dolor posterior de rodilla (artroplastia), con canal aductor.",
      tecnica: "Sonda curva en el hueco poplíteo, entre la arteria poplítea y el fémur.",
      volumen: "15–20 mL", ninos: "0,2–0,3 mL/kg",
      anestesico: "Ropivacaína 0,2–0,375 % o bupivacaína 0,25 %.",
      evidencia: "Mejora el dolor posterior sin bloqueo motor del ciático; evidencia de beneficio moderada.",
      adyuvantes: DEXA, precauciones: "Cerca de vasos poplíteos." },
    { id: "ciatico_subgluteo", nombre: "Ciático subglúteo", region: "inferior", nysora: "subgluteal sciatic nerve block",
      indicaciones: "Muslo posterior, rodilla, pierna, pie.",
      tecnica: "Sonda curva entre trocánter mayor y tuberosidad isquiática.",
      volumen: "15–20 mL", ninos: "0,2–0,4 mL/kg",
      anestesico: LARGA, evidencia: "Bloqueo prolongado con bupivacaína/ropivacaína 0,5 %.", adyuvantes: DEXA,
      precauciones: "Pie caído transitorio: proteger el talón." },
    { id: "popliteo", nombre: "Ciático poplíteo", region: "inferior", nysora: "popliteal sciatic block",
      indicaciones: "Tobillo y pie, pierna (con safeno para la cara medial).",
      tecnica: "Sonda lineal en el hueco poplíteo, en la división del nervio (inyección dentro de la vaina común, subparaneural).",
      volumen: "15–30 mL", ninos: "0,3–0,5 mL/kg",
      anestesico: LARGA, evidencia: "La inyección subparaneural acorta la latencia y mejora la tasa de éxito.",
      adyuvantes: DEXA, precauciones: "Pierna insensible por muchas horas: cuidar el talón y el apoyo." },
    { id: "tobillo", nombre: "Bloqueo de tobillo", region: "inferior", nysora: "ankle block",
      indicaciones: "Cirugía del antepié y los dedos.",
      tecnica: "Tibial posterior, peroneo profundo, peroneo superficial, sural y safeno.",
      volumen: "3–5 mL por nervio (total 15–25 mL)", ninos: "0,1 mL/kg por nervio",
      anestesico: "Bupivacaína 0,5 % o ropivacaína 0,5–0,75 %; lidocaína 1–2 % para procedimientos cortos.",
      evidencia: "Eficaz y sin bloqueo motor proximal.", adyuvantes: "",
      precauciones: "Evitar epinefrina en pacientes con enfermedad vascular periférica." },
    { id: "cutaneo_lateral", nombre: "Cutáneo femoral lateral", region: "inferior", nysora: "lateral femoral cutaneous nerve block",
      indicaciones: "Toma de injerto de piel, incisión lateral de cadera.",
      tecnica: "Sonda lineal medial a la espina ilíaca anterosuperior, sobre el sartorio.",
      volumen: "5–10 mL", ninos: "0,1 mL/kg", anestesico: "Ropivacaína 0,375–0,5 % o bupivacaína 0,25 %.",
      evidencia: "Bloqueo sensitivo puro.", adyuvantes: "", precauciones: "" },

    // ---------------------------------------------------------- tronco y pared
    { id: "esp", nombre: "Erector de la espina (ESP)", region: "tronco", nysora: "erector spinae plane block",
      indicaciones: "Columna, tórax, mama, abdomen (según el nivel), fracturas costales.",
      tecnica: "Sonda lineal parasagital a 3 cm de la línea media, sobre la apófisis transversa, bajo el músculo erector.",
      volumen: "20–30 mL por lado", ninos: "0,3–0,5 mL/kg por lado",
      anestesico: PLANO, evidencia: "Bloqueo fácil y seguro; la eficacia es variable según la cirugía (mejor evidencia en columna y cirugía torácica).",
      adyuvantes: DEXA, precauciones: "Bilateral: calcula la dosis total máxima." },
    { id: "paravertebral", nombre: "Paravertebral torácico", region: "tronco", nysora: "thoracic paravertebral block",
      indicaciones: "Toracotomía, VATS, mastectomía, fracturas costales.",
      tecnica: "Sonda entre apófisis transversas; inyección entre el ligamento costotransverso superior y la pleura.",
      volumen: "15–20 mL en un nivel o 3–5 mL por nivel", ninos: "0,3–0,5 mL/kg",
      anestesico: LARGA, evidencia: "Analgesia comparable a la epidural torácica en toracotomía con menos hipotensión.",
      adyuvantes: DEXA, precauciones: "Neumotórax, punción vascular, difusión epidural." },
    { id: "pecs", nombre: "PECS I / PECS II", region: "tronco", nysora: "PECS block",
      indicaciones: "Cirugía de mama, marcapasos, tórax anterior.",
      tecnica: "PECS I entre pectoral mayor y menor; PECS II añade la inyección entre pectoral menor y serrato.",
      volumen: "PECS I: 10 mL; PECS II: 10 mL + 20 mL", ninos: "0,2 mL/kg (I) + 0,3 mL/kg (II)",
      anestesico: PLANO, evidencia: "En mastectomía reduce el dolor y los opioides (recomendado por PROSPECT).", adyuvantes: DEXA,
      precauciones: "No cubre la mama medial (asociar paraesternal)." },
    { id: "serrato", nombre: "Plano del serrato anterior", region: "tronco", nysora: "serratus anterior plane block",
      indicaciones: "Fracturas costales, toracoscopia, mama lateral.",
      tecnica: "Sonda en la línea axilar media a nivel de la 4.ª–5.ª costilla, sobre o bajo el serrato.",
      volumen: "20–30 mL", ninos: "0,3–0,5 mL/kg",
      anestesico: PLANO, evidencia: "Analgesia de pared lateral; útil en fracturas costales.", adyuvantes: DEXA, precauciones: "" },
    { id: "tap", nombre: "TAP (transverso del abdomen)", region: "tronco", nysora: "transversus abdominis plane block",
      indicaciones: "Cesárea (sin morfina intratecal), laparoscopia, hernia, cirugía abdominal baja.",
      tecnica: "Lateral (línea axilar media) para T10–T12 o subcostal para T6–T9; entre oblicuo interno y transverso.",
      volumen: "15–20 mL por lado", ninos: "0,2–0,5 mL/kg por lado",
      anestesico: PLANO, evidencia: "Solo analgesia somática (sin dolor visceral). En cesárea con morfina intratecal el beneficio adicional es pequeño.",
      adyuvantes: DEXA, precauciones: "Bilateral: calcula la dosis total máxima." },
    { id: "cuadrado_lumbar", nombre: "Cuadrado lumbar", region: "tronco", nysora: "quadratus lumborum block",
      indicaciones: "Cesárea, cirugía abdominal, cadera (QL anterior), nefrectomía.",
      tecnica: "Sonda curva en el flanco; abordajes lateral, posterior o anterior (transmuscular).",
      volumen: "20–30 mL por lado", ninos: "0,3–0,5 mL/kg por lado",
      anestesico: PLANO, evidencia: "Puede cubrir parte del dolor visceral (difusión paravertebral); evidencia heterogénea.",
      adyuvantes: DEXA, precauciones: "El abordaje anterior puede dar debilidad del cuádriceps." },
    { id: "vaina_rectos", nombre: "Vaina de los rectos", region: "tronco", nysora: "rectus sheath block",
      indicaciones: "Laparotomía media, hernia umbilical.",
      tecnica: "Sonda lineal lateral a la línea media, entre el recto y su hoja posterior.",
      volumen: "10–15 mL por lado", ninos: "0,1–0,2 mL/kg por lado",
      anestesico: PLANO, evidencia: "Analgesia de incisiones de línea media.", adyuvantes: DEXA, precauciones: "Vasos epigástricos." },
    { id: "ilioinguinal", nombre: "Ilioinguinal / iliohipogástrico", region: "tronco", nysora: "ilioinguinal iliohypogastric nerve block",
      indicaciones: "Herniorrafia inguinal, orquidopexia, Pfannenstiel.",
      tecnica: "Sonda medial a la espina ilíaca anterosuperior, entre oblicuo interno y transverso.",
      volumen: "10–15 mL", ninos: "0,1–0,2 mL/kg",
      anestesico: "Bupivacaína 0,25 % o ropivacaína 0,2–0,5 %.", evidencia: "Eficaz en hernia inguinal; en niños es comparable al caudal.",
      adyuvantes: "", precauciones: "Bloqueo femoral accidental (debilidad) por difusión." },
    { id: "paraesternal", nombre: "Paraesternal / transverso del tórax", region: "tronco", nysora: "parasternal block",
      indicaciones: "Esternotomía (cirugía cardiaca), mama medial.",
      tecnica: "Sonda parasagital junto al esternón, a nivel del 3.º–5.º espacio intercostal.",
      volumen: "15–20 mL por lado", ninos: "0,2–0,3 mL/kg por lado",
      anestesico: PLANO, evidencia: "Reduce el dolor y los opioides tras esternotomía.", adyuvantes: DEXA,
      precauciones: "Arteria mamaria interna; neumotórax." },

    // ---------------------------------------------------------- cabeza y cuello
    { id: "cervical_superficial", nombre: "Plexo cervical superficial", region: "cabeza", nysora: "superficial cervical plexus block",
      indicaciones: "Endarterectomía carotídea, tiroides, clavícula (con interescalénico).",
      tecnica: "Sonda lineal en el borde posterior del esternocleidomastoideo, a nivel de C4.",
      volumen: "10–15 mL", ninos: "0,1–0,2 mL/kg",
      anestesico: "Ropivacaína 0,375–0,5 % o bupivacaína 0,25 %.", evidencia: "Tan eficaz como el profundo con menos complicaciones.",
      adyuvantes: "", precauciones: "" },
    { id: "escalpe", nombre: "Bloqueo de escalpe", region: "cabeza", nysora: "scalp block",
      indicaciones: "Craneotomía (incluida la del paciente despierto), pines del cabezal.",
      tecnica: "Supraorbitario, supratroclear, auriculotemporal, cigomaticotemporal, occipital mayor y menor (bilateral).",
      volumen: "2–5 mL por nervio (total 20–30 mL)", ninos: "0,05 mL/kg por nervio",
      anestesico: "Bupivacaína 0,25–0,5 % o ropivacaína 0,5 %, con epinefrina.", evidencia: "Atenúa la respuesta a los pines y reduce opioides.",
      adyuvantes: "", precauciones: "Zona muy vascular: dosis total y epinefrina." },

    // ---------------------------------------------------------- pediatría
    { id: "caudal", nombre: "Caudal", region: "pediatria", nysora: "caudal block",
      indicaciones: "Cirugía infraumbilical en niños (hernia, circuncisión, hipospadias, ortopedia).",
      tecnica: "Hiato sacro entre los cuernos; ecografía para confirmar la difusión.",
      volumen: "Armitage: 0,5 mL/kg sacro · 1 mL/kg lumbar · 1,25 mL/kg torácico bajo", ninos: "Igual (máx. ~20–25 mL)",
      anestesico: "Bupivacaína/levobupivacaína 0,25 % o ropivacaína 0,2 %.",
      evidencia: "Técnica pediátrica más estudiada; la dexmedetomidina o la clonidina caudal prolongan la analgesia.",
      adyuvantes: "Clonidina 1–2 µg/kg o dexmedetomidina 1 µg/kg (evitar en neonatos por apnea).",
      precauciones: "Inyección intravascular o intraósea: dosis de prueba y observación del ECG." },
    { id: "peneano", nombre: "Bloqueo peneano", region: "pediatria", nysora: "penile block",
      indicaciones: "Circuncisión, hipospadias distal.",
      tecnica: "Espacio subpúbico a cada lado de la línea media, bajo la fascia de Scarpa.",
      volumen: "0,1 mL/kg por lado", ninos: "0,1 mL/kg por lado",
      anestesico: "Bupivacaína 0,25 % o ropivacaína 0,2 % SIN epinefrina.", evidencia: "Analgesia comparable al caudal en circuncisión.",
      adyuvantes: "", precauciones: "Nunca epinefrina (arterias terminales)." },
  ];

  const REGIONES = [["superior", "Miembro superior"], ["inferior", "Miembro inferior"], ["tronco", "Tórax y abdomen"],
    ["cabeza", "Cabeza y cuello"], ["pediatria", "Pediatría"]];

  /** Dosis máxima en mg y en mL para un anestésico, peso y concentración (%). Usa el peso magro si se da. */
  function dosisMaxima(id, peso, concPorcentaje, conEpinefrina = false) {
    const a = ANESTESICOS.find((x) => x.id === id);
    if (!a || !(peso > 0)) return null;
    const mgkg = conEpinefrina ? a.mgkgEpi : a.mgkg, tope = conEpinefrina ? a.topeEpi : a.tope;
    const mg = Math.min(mgkg * peso, tope);
    const mgPorMl = concPorcentaje > 0 ? concPorcentaje * 10 : null;
    return { mg, mgkg, porTope: mgkg * peso > tope, ml: mgPorMl ? mg / mgPorMl : null, mgPorMl };
  }

  /** Emulsión lipídica al 20 % para LAST (lista de chequeo ASRA 2020). */
  function rescateLipidico(peso) {
    if (!(peso > 0)) return null;
    if (peso > 70) return { bolo: "100 mL en 2–3 min", infusion: "200–250 mL en 15–20 min", maximo: Math.round(12 * peso) };
    const r = (v) => Math.round(v * 10) / 10;
    return { bolo: `${r(1.5 * peso)} mL (1,5 mL/kg) en 2–3 min`, infusion: `${r(0.25 * peso)} mL/min (0,25 mL/kg/min)`,
      maximo: Math.round(12 * peso) };
  }

  const api = { ANESTESICOS, BLOQUEOS, REGIONES, dosisMaxima, rescateLipidico };
  raiz.Regional = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
