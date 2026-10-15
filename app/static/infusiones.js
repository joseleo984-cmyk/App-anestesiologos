/* Calculadora de infusiones de vasopresores, inotrópicos y vasodilatadores.
   Solo cálculos (sin servidor ni IA). Las diluciones y los rangos son orientativos y los debe validar AP:
   cada uno se puede ajustar en la pantalla. */
(function (raiz) {
  "use strict";

  // unidad de dosis → cómo se convierte a mL/h
  const UNIDADES = {
    "mcg/kg/min": { porKg: true, porMin: true, base: "mcg" },
    "mcg/min": { porKg: false, porMin: true, base: "mcg" },
    "mcg/kg/h": { porKg: true, porMin: false, base: "mcg" },
    "U/min": { porKg: false, porMin: true, base: "U" },
    "U/kg/min": { porKg: true, porMin: true, base: "U" },
  };

  // cantidad a diluir: mg, mcg o U → unidad base (mcg o U)
  const A_BASE = { mg: 1000, mcg: 1, U: 1 };

  // p: preparaciones [cantidad, unidad, volumen mL]. r: rango usual [mín, máx] y tope (por encima: alerta roja).
  // porPeso: con cuánto queda 1 mL/h en la preparación pediátrica por peso.
  const MEDICAMENTOS = [
    { id: "norepinefrina", nombre: "Norepinefrina", grupo: "Vasopresor",
      adulto: { unidad: "mcg/kg/min", r: [0.01, 0.5], tope: 2, p: [[4, "mg", 250], [8, "mg", 250], [4, "mg", 100], [16, "mg", 250]],
        pasos: [0.01, 0.02, 0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5] },
      nino: { unidad: "mcg/kg/min", r: [0.05, 1], tope: 2, p: [[1, "mg", 50], [4, "mg", 250]], porPeso: 0.1,
        pasos: [0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1] } },
    { id: "epinefrina", nombre: "Epinefrina (adrenalina)", grupo: "Vasopresor / inotrópico",
      adulto: { unidad: "mcg/kg/min", r: [0.01, 0.5], tope: 2, p: [[1, "mg", 100], [4, "mg", 250], [2, "mg", 250]],
        pasos: [0.01, 0.02, 0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5] },
      nino: { unidad: "mcg/kg/min", r: [0.01, 1], tope: 2, p: [[1, "mg", 50], [1, "mg", 100]], porPeso: 0.1,
        pasos: [0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1] } },
    { id: "fenilefrina", nombre: "Fenilefrina", grupo: "Vasopresor",
      adulto: { unidad: "mcg/min", r: [10, 200], tope: 400, p: [[10, "mg", 250], [20, "mg", 250], [10, "mg", 100]] },
      nino: { unidad: "mcg/kg/min", r: [0.1, 0.5], tope: 2, p: [[1, "mg", 50], [10, "mg", 250]], porPeso: 0.1 } },
    { id: "vasopresina", nombre: "Vasopresina", grupo: "Vasopresor",
      adulto: { unidad: "U/min", r: [0.01, 0.04], tope: 0.07, p: [[20, "U", 100], [40, "U", 100], [20, "U", 50]] },
      nino: { unidad: "U/kg/min", r: [0.0002, 0.002], tope: 0.003, p: [[20, "U", 100], [10, "U", 50]], porPeso: 0.0002 } },
    { id: "dopamina", nombre: "Dopamina", grupo: "Inotrópico / vasopresor",
      adulto: { unidad: "mcg/kg/min", r: [2, 20], tope: 30, p: [[400, "mg", 250], [200, "mg", 250], [800, "mg", 250]] },
      nino: { unidad: "mcg/kg/min", r: [2, 20], tope: 20, p: [[200, "mg", 50], [400, "mg", 250]], porPeso: 1 } },
    { id: "dobutamina", nombre: "Dobutamina", grupo: "Inotrópico",
      adulto: { unidad: "mcg/kg/min", r: [2, 20], tope: 40, p: [[250, "mg", 250], [500, "mg", 250], [1000, "mg", 250]] },
      nino: { unidad: "mcg/kg/min", r: [2, 20], tope: 20, p: [[250, "mg", 50], [250, "mg", 250]], porPeso: 1 } },
    { id: "milrinona", nombre: "Milrinona", grupo: "Inodilatador",
      adulto: { unidad: "mcg/kg/min", r: [0.125, 0.75], tope: 1, p: [[20, "mg", 100], [20, "mg", 200], [10, "mg", 50]] },
      nino: { unidad: "mcg/kg/min", r: [0.25, 0.75], tope: 1, p: [[10, "mg", 50], [20, "mg", 100]], porPeso: 0.1 } },
    { id: "levosimendan", nombre: "Levosimendán", grupo: "Inodilatador",
      adulto: { unidad: "mcg/kg/min", r: [0.05, 0.2], tope: 0.2, p: [[12.5, "mg", 250], [12.5, "mg", 500]] },
      nino: { unidad: "mcg/kg/min", r: [0.05, 0.2], tope: 0.2, p: [[12.5, "mg", 250], [12.5, "mg", 500]], porPeso: 0.1 } },
    { id: "nitroglicerina", nombre: "Nitroglicerina", grupo: "Vasodilatador",
      adulto: { unidad: "mcg/min", r: [5, 200], tope: 400, p: [[50, "mg", 250], [25, "mg", 250], [100, "mg", 250]] },
      nino: { unidad: "mcg/kg/min", r: [0.25, 5], tope: 10, p: [[50, "mg", 250], [10, "mg", 50]], porPeso: 1 } },
    { id: "nitroprusiato", nombre: "Nitroprusiato", grupo: "Vasodilatador",
      adulto: { unidad: "mcg/kg/min", r: [0.3, 5], tope: 10, p: [[50, "mg", 250], [50, "mg", 500]] },
      nino: { unidad: "mcg/kg/min", r: [0.3, 5], tope: 10, p: [[50, "mg", 250], [10, "mg", 50]], porPeso: 1 } },
    { id: "esmolol", nombre: "Esmolol", grupo: "Betabloqueador",
      adulto: { unidad: "mcg/kg/min", r: [50, 300], tope: 300, p: [[2500, "mg", 250], [100, "mg", 10]] },
      nino: { unidad: "mcg/kg/min", r: [50, 500], tope: 1000, p: [[2500, "mg", 250], [100, "mg", 10]], porPeso: 10 } },
    { id: "dexmedetomidina", nombre: "Dexmedetomidina", grupo: "Sedación",
      adulto: { unidad: "mcg/kg/h", r: [0.2, 1.4], tope: 1.5, p: [[200, "mcg", 50], [400, "mcg", 100], [200, "mcg", 100]] },
      nino: { unidad: "mcg/kg/h", r: [0.2, 1], tope: 1.5, p: [[200, "mcg", 50], [200, "mcg", 100]], porPeso: 0.1 } },
  ];

  const redondear = (v, cifras = 3) => {
    if (!isFinite(v) || v === 0) return v;
    const f = Math.pow(10, cifras - 1 - Math.floor(Math.log10(Math.abs(v))));
    return Math.round(v * f) / f;
  };

  /** Concentración en unidad base por mL (mcg/mL o U/mL). */
  function concentracion(cantidad, unidadCantidad, volumen) {
    if (!(cantidad > 0) || !(volumen > 0) || !A_BASE[unidadCantidad]) return null;
    return cantidad * A_BASE[unidadCantidad] / volumen;
  }

  function factor(unidad, peso) {
    const u = UNIDADES[unidad];
    if (!u) throw new Error("Unidad desconocida: " + unidad);
    if (u.porKg && !(peso > 0)) return null;
    return (u.porKg ? peso : 1) * (u.porMin ? 60 : 1);
  }

  /** Dosis → mL/h. */
  function mlPorHora(dosis, unidad, peso, conc) {
    const f = factor(unidad, peso);
    if (f === null || !(conc > 0) || !(dosis >= 0)) return null;
    return dosis * f / conc;
  }

  /** mL/h → dosis. */
  function dosisDesde(mlh, unidad, peso, conc) {
    const f = factor(unidad, peso);
    if (f === null || !(conc > 0) || !(mlh >= 0)) return null;
    return mlh * conc / f;
  }

  /** Pediatría: cuánto medicamento poner en `volumen` mL para que 1 mL/h = `dosisPorMl` (en la unidad de dosis).
      Devuelve la cantidad en mg (o mcg / U según la base). */
  function preparacionPorPeso(dosisPorMl, unidad, peso, volumen) {
    const f = factor(unidad, peso);
    if (f === null || !(volumen > 0) || !(dosisPorMl > 0)) return null;
    const base = dosisPorMl * f * volumen;  // mcg o U totales
    const u = UNIDADES[unidad].base;
    if (u === "U") return { cantidad: base, unidad: "U" };
    return base >= 1000 ? { cantidad: base / 1000, unidad: "mg" } : { cantidad: base, unidad: "mcg" };
  }

  /** Dónde cae la dosis: BAJA (bajo el rango usual), USUAL, ALTA (sobre el usual) o TOPE (sobre el máximo). */
  function nivel(dosis, cfg) {
    if (!(dosis >= 0)) return null;
    if (dosis > cfg.tope * 1.0001) return "TOPE";
    if (dosis > cfg.r[1] * 1.0001) return "ALTA";
    if (dosis < cfg.r[0] * 0.9999) return "BAJA";
    return "USUAL";
  }

  /** Dosis "redondas" para la tabla, dentro del rango usual (y un poco más, hasta el tope). */
  function pasosDeDosis(cfg, cuantos = 8) {
    if (cfg.pasos) return cfg.pasos.slice();
    const [a, b] = cfg.r, hasta = Math.min(cfg.tope, b);
    const crudo = (hasta - a) / (cuantos - 1);
    const mag = Math.pow(10, Math.floor(Math.log10(crudo)));
    const paso = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((p) => p >= crudo) || mag * 10;
    const valores = [a];
    for (let v = Math.ceil(a / paso + 1e-9) * paso; v <= hasta + 1e-9; v += paso) {
      if (Math.abs(v - valores[valores.length - 1]) > paso / 3) valores.push(redondear(v, 4));
    }
    if (valores[valores.length - 1] < hasta - 1e-9) valores.push(hasta);
    return valores;
  }

  const api = { MEDICAMENTOS, UNIDADES, concentracion, mlPorHora, dosisDesde, preparacionPorPeso, nivel, pasosDeDosis, redondear };
  raiz.Infusiones = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
