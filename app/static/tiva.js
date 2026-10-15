/* Simulador de TIVA / TCI: modelos farmacocinéticos de tres compartimentos con compartimento de efecto.
   Solo cálculos en el teléfono (sin servidor ni IA). Es una guía: la app no controla la bomba.

   Parámetros tomados de las publicaciones originales:
   - Marsh (Br J Anaesth 1991; 67:41-48). ke0 0,26/min (Diprifusor) o 1,2/min (Marsh modificado, Struys 2000).
   - Schnider (Anesthesiology 1998; 88:1170-82 y 1999; 90:1502-16). Masa magra de James.
   - Eleveld propofol (Br J Anaesth 2018; 120:942-959), de neonatos a ancianos. Parámetros arteriales.
   - Paedfusor (Absalom, Br J Anaesth 2003; 91:507-13), 1 a 16 años. Sin ke0 publicado: solo objetivo plasmático.
   - Minto remifentanilo (Anesthesiology 1997; 86:10-23). Masa magra de James.
   - Eleveld remifentanilo (Anesthesiology 2017; 126:1005-18), todas las edades.
   Unidades: volúmenes en L, aclaramientos en L/min, constantes en /min. Propofol en mg y µg/mL;
   remifentanilo en µg y ng/mL (µg/L). */
(function (raiz) {
  "use strict";

  // ------------------------------------------------------------------ pacientes
  function imc(p) { return p.peso / Math.pow(p.talla / 100, 2); }
  /** Masa magra de James (Schnider, Minto). No es válida en obesidad: cae a partir de cierto peso. */
  function masaMagraJames(p) {
    const r = p.peso / p.talla;
    return p.sexo === "M" ? 1.1 * p.peso - 128 * r * r : 1.07 * p.peso - 148 * r * r;
  }
  /** Peso al que la masa magra de James deja de aumentar (de ahí en adelante el modelo da valores absurdos). */
  function pesoMaximoJames(p) {
    return p.sexo === "M" ? 1.1 * p.talla * p.talla / 256 : 1.07 * p.talla * p.talla / 296;
  }
  /** Masa libre de grasa de Al-Sallami (Eleveld). */
  function masaLibreGrasaAlSallami(edad, peso, imcValor, masculino) {
    return masculino
      ? (0.88 + (1 - 0.88) / (1 + Math.pow(edad / 13.4, -12.7))) * (9270 * peso) / (6680 + 216 * imcValor)
      : (1.11 + (1 - 1.11) / (1 + Math.pow(edad / 7.1, -1.1))) * (9270 * peso) / (8780 + 244 * imcValor);
  }
  const sigmoide = (x, e50, l) => Math.pow(x, l) / (Math.pow(x, l) + Math.pow(e50, l));

  // ------------------------------------------------------------------ modelos
  function desdeConstantes(v1, k10, k12, k13, k21, k31, ke0) {
    return { v1, v2: v1 * k12 / k21, v3: v1 * k13 / k31, k10, k12, k13, k21, k31, ke0 };
  }
  function desdeAclaramientos(v1, v2, v3, cl, q2, q3, ke0) {
    return { v1, v2, v3, cl, q2, q3, k10: cl / v1, k12: q2 / v1, k13: q3 / v1, k21: q2 / v2, k31: q3 / v3, ke0 };
  }

  const MODELOS = {
    marsh: {
      farmaco: "propofol", nombre: "Marsh", detalle: "Adultos · peso total · ke0 0,26 (Diprifusor)",
      edad: [16, 100], requiere: ["peso"],
      calcular: (p) => desdeConstantes(0.228 * p.peso, 0.119, 0.112, 0.042, 0.055, 0.0033, 0.26),
    },
    marsh_mod: {
      farmaco: "propofol", nombre: "Marsh modificado", detalle: "Adultos · peso total · ke0 1,2 (Struys)",
      edad: [16, 100], requiere: ["peso"],
      calcular: (p) => desdeConstantes(0.228 * p.peso, 0.119, 0.112, 0.042, 0.055, 0.0033, 1.2),
    },
    schnider: {
      farmaco: "propofol", nombre: "Schnider", detalle: "Adultos · edad, sexo, peso y talla · ke0 0,456",
      edad: [16, 100], requiere: ["edad", "peso", "talla", "sexo"], james: true,
      calcular: (p) => {
        const lbm = masaMagraJames(p);
        return desdeAclaramientos(4.27, 18.9 - 0.391 * (p.edad - 53), 238,
          1.89 + 0.0456 * (p.peso - 77) - 0.0681 * (lbm - 59) + 0.0264 * (p.talla - 177),
          1.29 - 0.024 * (p.edad - 53), 0.836, 0.456);
      },
    },
    eleveld_propofol: {
      farmaco: "propofol", nombre: "Eleveld", detalle: "Adultos y niños (desde neonatos) · con o sin opioide",
      edad: [0, 88], requiere: ["edad", "peso", "talla", "sexo"], bis: true,
      calcular: (p) => {
        const t = [6.28, 25.5, 273, 1.79, 1.75, 1.11, 0.191, 42.3, 9.06, -0.0156, -0.00286, 33.6, -0.0138, 68.3, 2.10, 1.30, 1.42, 0.68];
        const edad = p.edad, peso = p.peso, m = p.sexo === "M";
        const pma = edad + 40 / 52;  // edad posmenstrual en años (a término)
        const ref = { edad: 35, peso: 70, talla: 170 };
        const imcRef = ref.peso / Math.pow(ref.talla / 100, 2);
        const env = (x) => Math.exp(x * (edad - ref.edad));
        const opi = (x) => p.opioide ? Math.exp(x * edad) : 1;
        const central = (x) => sigmoide(x, t[11], 1);
        const madCL = sigmoide(pma * 52, t[7], t[8]) / sigmoide((ref.edad + 40 / 52) * 52, t[7], t[8]);
        const madQ3 = sigmoide(edad * 52 + 40, t[13], 1), madQ3ref = sigmoide(ref.edad * 52 + 40, t[13], 1);
        const ffm = masaLibreGrasaAlSallami(edad, peso, imc(p), m);
        const ffmRef = masaLibreGrasaAlSallami(ref.edad, ref.peso, imcRef, true);
        const v1 = t[0] * central(peso) / central(ref.peso);
        const v2 = t[1] * peso / ref.peso * env(t[9]);
        const v3 = t[2] * ffm / ffmRef * opi(t[12]);
        const cl = (m ? t[3] : t[14]) * Math.pow(peso / ref.peso, 0.75) * madCL * opi(t[10]);
        const q2 = t[4] * Math.pow(v2 / t[1], 0.75) * (1 + t[15] * (1 - madQ3));
        const q3 = t[5] * Math.pow(v3 / t[2], 0.75) * madQ3 / madQ3ref;
        const ke0 = 0.146 * Math.pow(peso / 70, -0.25);
        const r = desdeAclaramientos(v1, v2, v3, cl, q2, q3, ke0);
        // BIS (modelo de Eleveld): C50 según la edad
        r.bis = { c50: 3.08 * Math.exp(-0.00635 * (edad - 35)), e0: 93, gamma: 1.47, gamma2: 1.89 };
        return r;
      },
    },
    paedfusor: {
      farmaco: "propofol", nombre: "Paedfusor", detalle: "Niños de 1 a 16 años · solo objetivo plasmático",
      edad: [1, 16], requiere: ["edad", "peso"], soloPlasma: true,
      calcular: (p) => {
        // de 1 a 12 años V1 0,458 L/kg y k10 0,1527·peso^-0,3; de 13 a 16 se acerca a Marsh
        const tabla = { 13: [0.4, 0.0678], 14: [0.342, 0.0792], 15: [0.284, 0.0954], 16: [0.229, 0.119] };
        const e = Math.floor(p.edad);
        const [v1kg, k10] = e >= 13 ? tabla[Math.min(e, 16)] : [0.4584, 0.1527 * Math.pow(p.peso, -0.3)];
        return desdeConstantes(v1kg * p.peso, k10, 0.114, 0.0419, 0.055, 0.0033, 0);
      },
    },
    minto: {
      farmaco: "remifentanilo", nombre: "Minto", detalle: "Adultos · edad, sexo, peso y talla",
      edad: [16, 100], requiere: ["edad", "peso", "talla", "sexo"], james: true,
      calcular: (p) => {
        const lbm = masaMagraJames(p), e = p.edad - 40, l = lbm - 55;
        return desdeAclaramientos(5.1 - 0.0201 * e + 0.072 * l, 9.82 - 0.0811 * e + 0.108 * l, 5.42,
          2.6 - 0.0162 * e + 0.0191 * l, 2.05 - 0.0301 * e, 0.076 - 0.00113 * e, 0.595 - 0.007 * e);
      },
    },
    eleveld_remi: {
      farmaco: "remifentanilo", nombre: "Eleveld", detalle: "Adultos y niños",
      edad: [0, 90], requiere: ["edad", "peso", "talla", "sexo"],
      calcular: (p) => {
        const edad = p.edad, peso = p.peso, m = p.sexo === "M";
        const ref = { edad: 35, peso: 70, talla: 170 };
        const imcRef = ref.peso / Math.pow(ref.talla / 100, 2);
        const env = (x) => Math.exp(x * (edad - ref.edad));
        const tam = masaLibreGrasaAlSallami(edad, peso, imc(p), m) / masaLibreGrasaAlSallami(ref.edad, ref.peso, imcRef, true);
        const kmat = sigmoide(peso, 2.88, 2) / sigmoide(ref.peso, 2.88, 2);
        const ksexo = m ? 1 : 1 + 0.470 * sigmoide(edad, 12, 6) * (1 - sigmoide(edad, 45, 6));
        const v1 = 5.81 * tam * env(-0.00554);
        const v2 = 8.82 * tam * env(-0.00327) * ksexo;
        const v3 = 5.03 * tam * env(-0.0315) * Math.exp(-0.0260 * (peso - 70));
        const cl = 2.58 * Math.pow(tam, 0.75) * kmat * ksexo * env(-0.00327);
        const q2 = 1.72 * Math.pow(v2 / 8.82, 0.75) * env(-0.00554) * ksexo;
        const q3 = 0.124 * Math.pow(v3 / 5.03, 0.75) * env(-0.00554);
        return desdeAclaramientos(v1, v2, v3, cl, q2, q3, 1.09 * env(-0.0289));
      },
    },
  };

  const FARMACOS = {
    propofol: { nombre: "Propofol", cantidad: "mg", conc: "µg/mL", jeringa: [10, 20], objetivo: 3, despertar: 1.2,
      rangoObjetivo: [0.5, 8], modelos: ["eleveld_propofol", "schnider", "marsh", "marsh_mod", "paedfusor"] },
    remifentanilo: { nombre: "Remifentanilo", cantidad: "µg", conc: "ng/mL", jeringa: [50, 20, 25, 100], objetivo: 3, despertar: 1,
      rangoObjetivo: [0.5, 15], modelos: ["eleveld_remi", "minto"] },
  };

  /** Problemas del paciente para el modelo: lo que falta y lo que está fuera de lo estudiado. */
  function validar(modeloId, p) {
    const mod = MODELOS[modeloId], errores = [], avisos = [];
    const nombres = { edad: "la edad", peso: "el peso", talla: "la talla", sexo: "el sexo" };
    for (const c of mod.requiere) if (!(c === "sexo" ? p.sexo === "M" || p.sexo === "F" : p[c] > 0)) errores.push(`Falta ${nombres[c]}.`);
    if (errores.length) return { errores, avisos };
    if (p.edad < mod.edad[0] || p.edad > mod.edad[1])
      avisos.push(`${mod.nombre} se estudió entre ${mod.edad[0]} y ${mod.edad[1]} años.`);
    if (mod.james && p.peso >= pesoMaximoJames(p) * 0.95)
      errores.push(`Con este peso y talla la masa magra de James no es válida (obesidad): ${mod.nombre} da resultados erróneos. Usa Eleveld.`);
    else if (mod.james && imc(p) > 35) avisos.push(`IMC ${imc(p).toFixed(0)}: ${mod.nombre} es poco confiable en obesidad. Considera Eleveld.`);
    if ((modeloId === "marsh" || modeloId === "marsh_mod") && p.talla > 0 && imc(p) > 35)
      avisos.push("Marsh usa el peso total: en obesidad sobrestima las dosis.");
    if (modeloId.startsWith("eleveld") && (p.peso < 0.68 || p.peso > 160)) avisos.push("Eleveld se estudió entre 0,68 y 160 kg.");
    if (p.edad < 1 && modeloId.startsWith("eleveld")) avisos.push("En neonatos y lactantes la variabilidad es muy alta: titula según la clínica.");
    return { errores, avisos };
  }

  // ------------------------------------------------------------------ simulación exacta (matriz exponencial)
  // estado: [A1, A2, A3, Ce]; entrada: velocidad en (mg o µg)/min al compartimento central
  function matrizSistema(k) {
    return [
      [-(k.k10 + k.k12 + k.k13), k.k21, k.k31, 0],
      [k.k12, -k.k21, 0, 0],
      [k.k13, 0, -k.k31, 0],
      [k.ke0 / k.v1, 0, 0, -k.ke0],
    ];
  }
  function mult(a, b) {
    const n = a.length, m = b[0].length, r = Array.from({ length: n }, () => new Array(m).fill(0));
    for (let i = 0; i < n; i++) for (let k = 0; k < b.length; k++) { const v = a[i][k]; if (v) for (let j = 0; j < m; j++) r[i][j] += v * b[k][j]; }
    return r;
  }
  /** exp(M·h) por escalado y cuadrados con serie de Taylor. */
  function expm(M, h) {
    const n = M.length;
    let norma = 0;
    for (const f of M) norma = Math.max(norma, f.reduce((s, v) => s + Math.abs(v), 0));
    const s = Math.max(0, Math.ceil(Math.log2(Math.max(norma * h, 1e-12) / 0.25)));
    const A = M.map((f) => f.map((v) => v * h / Math.pow(2, s)));
    let R = A.map((f, i) => f.map((_, j) => (i === j ? 1 : 0))), T = R.map((f) => f.slice());
    for (let k = 1; k <= 18; k++) {
      T = mult(T, A).map((f) => f.map((v) => v / k));
      R = R.map((f, i) => f.map((v, j) => v + T[i][j]));
    }
    for (let i = 0; i < s; i++) R = mult(R, R);
    return R;
  }
  /** Paso exacto de h minutos: x' = Φx + Γ·velocidad (velocidad constante durante el paso). */
  function paso(k, h) {
    const M = matrizSistema(k), n = 4;
    const aum = Array.from({ length: n + 1 }, (_, i) => Array.from({ length: n + 1 }, (_, j) => (i < n && j < n ? M[i][j] : 0)));
    aum[0][n] = 1;  // la entrada entra al compartimento central
    const E = expm(aum, h);
    return { phi: E.slice(0, n).map((f) => f.slice(0, n)), gamma: E.slice(0, n).map((f) => f[n]) };
  }
  function avanzar(x, P, velocidad) {
    const r = [0, 0, 0, 0];
    for (let i = 0; i < 4; i++) {
      let s = P.gamma[i] * velocidad;
      for (let j = 0; j < 4; j++) s += P.phi[i][j] * x[j];
      r[i] = s;
    }
    return r;
  }
  const cp = (x, k) => x[0] / k.v1;

  /** BIS predicho (Eleveld) para una concentración en el sitio efecto. */
  function bisPredicho(ce, bis) {
    if (!bis || !(ce >= 0)) return null;
    const g = ce <= bis.c50 ? bis.gamma : bis.gamma2;
    return bis.e0 - bis.e0 * Math.pow(ce, g) / (Math.pow(bis.c50, g) + Math.pow(ce, g));
  }

  /**
   * Plan de TCI: velocidades para llevar la concentración plasmática o en sitio efecto al objetivo.
   * opciones: { objetivos: [{min, valor}], modo: "efecto"|"plasma", duracion (min), concJeringa (por mL),
   *             velocidadMax (mL/h), despues (min a simular tras detener) }
   * Devuelve la serie cada 10 s: { t, cp, ce, velocidad (por min), mlh, acumulado }.
   */
  function planTCI(k, opciones) {
    const dt = 10 / 60, PASO = paso(k, dt), FINO = paso(k, 5 / 60);
    const modo = k.ke0 > 0 ? opciones.modo : "plasma";
    const rmax = (opciones.velocidadMax || 1200) / 60 * opciones.concJeringa;   // cantidad/min
    const objetivo = (t) => { let v = 0; for (const o of opciones.objetivos) if (t >= o.min - 1e-9) v = o.valor; return v; };
    // respuesta a 1 unidad/min durante dt y luego nada, muestreada cada 5 s durante el horizonte
    const H = Math.ceil(20 * 60 / 5);
    const unit = [];
    {
      let x = avanzar([0, 0, 0, 0], PASO, 1);
      for (let i = 0; i < H; i++) { unit.push(x); x = avanzar(x, FINO, 0); }
    }
    const pico = (libre, r) => { let m = -Infinity; for (let i = 0; i < H; i++) m = Math.max(m, libre[i][3] + r * unit[i][3]); return m; };
    const serie = [];
    let x = [0, 0, 0, 0], acumulado = 0;
    const pasos = Math.round(opciones.duracion / dt), extra = Math.round((opciones.despues || 0) / dt);
    for (let n = 0; n < pasos + extra; n++) {
      const t = n * dt, meta = n < pasos ? objetivo(t) : 0;
      let r = 0;
      if (meta > 0) {
        if (modo === "plasma") {
          const libre = avanzar(x, PASO, 0);
          r = (meta - libre[0] / k.v1) / (PASO.gamma[0] / k.v1);
        } else {
          const libre = [];
          let y = avanzar(x, PASO, 0);
          for (let i = 0; i < H; i++) { libre.push(y); y = avanzar(y, FINO, 0); }
          if (pico(libre, 0) >= meta) r = 0;
          else if (pico(libre, rmax) <= meta) r = rmax;
          else {
            let a = 0, b = rmax;
            for (let i = 0; i < 40; i++) { const c = (a + b) / 2; if (pico(libre, c) > meta) b = c; else a = c; }
            r = (a + b) / 2;
          }
        }
        r = Math.min(Math.max(r, 0), rmax);
      }
      serie.push({ t, cp: cp(x, k), ce: x[3], velocidad: r, mlh: r / opciones.concJeringa * 60, acumulado, objetivo: meta });
      x = avanzar(x, PASO, r);
      acumulado += r * dt;
    }
    serie.push({ t: (pasos + extra) * dt, cp: cp(x, k), ce: x[3], velocidad: 0, mlh: 0, acumulado, objetivo: 0 });
    return serie;
  }

  /**
   * Simulación de una pauta manual: [{min, bolo (cantidad), mlh}] con la concentración de la jeringa.
   * Cada evento aplica un bolo (opcional) y deja la bomba a mlh desde ese minuto.
   */
  function simularManual(k, eventos, concJeringa, duracion) {
    const dt = 10 / 60, PASO = paso(k, dt);
    const ordenados = [...eventos].sort((a, b) => a.min - b.min);
    const serie = [];
    let x = [0, 0, 0, 0], acumulado = 0, mlh = 0, e = 0;
    const pasos = Math.round(duracion / dt);
    for (let n = 0; n <= pasos; n++) {
      const t = n * dt;
      while (e < ordenados.length && ordenados[e].min <= t + 1e-9) {
        const ev = ordenados[e++];
        if (ev.bolo > 0) { x = x.slice(); x[0] += ev.bolo; acumulado += ev.bolo; }
        if (ev.mlh != null) mlh = ev.mlh;
      }
      const r = mlh / 60 * concJeringa;
      serie.push({ t, cp: cp(x, k), ce: x[3], velocidad: r, mlh, acumulado, objetivo: 0 });
      if (n < pasos) { x = avanzar(x, PASO, r); acumulado += r * dt; }
    }
    return serie;
  }

  /** Resumen para la bomba: bolo inicial y velocidades promedio por tramo. */
  function tramos(serie, duracion) {
    // cada minuto los primeros 10, cada 5 hasta los 30 y luego cada 15 (como se reprograma una bomba a mano)
    const cortes = [];
    for (let m = 0; m < Math.min(10, duracion); m += 1) cortes.push([m, m + 1]);
    for (let m = 10; m < Math.min(30, duracion); m += 5) cortes.push([m, Math.min(m + 5, duracion)]);
    for (let m = 30; m < duracion; m += 15) cortes.push([m, Math.min(m + 15, duracion)]);
    return cortes.map(([a, b]) => {
      const dentro = serie.filter((s) => s.t >= a - 1e-9 && s.t < b - 1e-9);
      const cantidad = dentro.reduce((s, x) => s + x.velocidad * (10 / 60), 0);
      return { desde: a, hasta: b, cantidad, velocidadMedia: cantidad / (b - a) };
    });
  }

  /** Minutos desde que se detiene la infusión hasta que la concentración en sitio efecto baja de `umbral`. */
  function tiempoHasta(serie, desdeMin, umbral, campo = "ce") {
    for (const s of serie) if (s.t >= desdeMin - 1e-9 && s[campo] <= umbral) return s.t - desdeMin;
    return null;
  }

  /**
   * Cifras de la simulación que un anestesiólogo compara con otra fuente (SimTIVA, una bomba TCI…)
   * para la bitácora de validación. o = { modo, sitio, objetivo, duracion, umbral, cantidad, conc, soloPlasma }.
   * Devuelve [{ clave, etiqueta, unidad, app }]; app es null si la simulación no llega a ese punto.
   */
  function puntosComparacion(serie, o) {
    const en = (min) => serie.find((s) => s.t >= min - 1e-9);
    const puntos = [];
    const agregar = (clave, etiqueta, unidad, app) => puntos.push({ clave, etiqueta, unidad, app: app == null || !isFinite(app) ? null : app });
    const minutos = [5, 15, 60].filter((m) => m < o.duracion);
    if (o.modo === "tci") {
      const campo = o.sitio === "efecto" ? "ce" : "cp";
      const llega = serie.find((s) => s[campo] >= o.objetivo * 0.97);
      agregar("bolo", "Bolo de inducción (1.er minuto)", o.cantidad, tramos(serie, o.duracion)[0].cantidad);
      agregar("t_objetivo", `Llega al objetivo (${campo === "ce" ? "Ce" : "Cp"})`, "min", llega ? llega.t : null);
      for (const m of minutos) agregar(`mlh_${m}`, `Velocidad a los ${m} min`, "mL/h", (en(m) || {}).mlh);
    } else {
      const campo = o.soloPlasma ? "cp" : "ce";
      for (const m of minutos) agregar(`${campo}_${m}`, `${campo === "ce" ? "Ce" : "Cp"} a los ${m} min`, o.conc, (en(m) || {})[campo]);
    }
    agregar("total", `Total en ${o.duracion} min`, o.cantidad, (en(o.duracion) || serie[serie.length - 1]).acumulado);
    agregar("despertar", `Despertar (${o.soloPlasma ? "Cp" : "Ce"} < ${String(o.umbral).replace(".", ",")})`, "min",
      tiempoHasta(serie, o.duracion, o.umbral, o.soloPlasma ? "cp" : "ce"));
    return puntos;
  }

  /** Diferencia de la app frente a la referencia, en % de la referencia (null si no se puede calcular). */
  function diferenciaPct(app, referencia) {
    if (app == null || referencia == null || !isFinite(app) || !isFinite(referencia)) return null;
    if (referencia === 0) return app === 0 ? 0 : null;
    return (app - referencia) / Math.abs(referencia) * 100;
  }

  const api = { MODELOS, FARMACOS, validar, masaMagraJames, pesoMaximoJames, masaLibreGrasaAlSallami, imc,
    paso, avanzar, planTCI, simularManual, tramos, tiempoHasta, bisPredicho, puntosComparacion, diferenciaPct };
  raiz.Tiva = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
