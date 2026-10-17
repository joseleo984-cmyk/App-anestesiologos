/* Escáner de documentos: detecta la hoja en la foto, la endereza (perspectiva) y mejora el contraste para que
   la orden se lea como un escaneo. Todo en el teléfono, sin servidor. Trabaja sobre imágenes {data, width, height}
   (RGBA, como ImageData) para poder probarse fuera del navegador. */
(function (raiz) {
  "use strict";

  const luz = (d, i) => 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];

  // Copia reducida (promedio por bloques) para detectar rápido: lado mayor ≈ maximo.
  function reducir(img, maximo) {
    const f = Math.max(1, Math.floor(Math.max(img.width, img.height) / maximo));
    const w = Math.floor(img.width / f), h = Math.floor(img.height / f);
    const gris = new Uint8Array(w * h);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      let s = 0, n = 0;
      for (let dy = 0; dy < f; dy++) for (let dx = 0; dx < f; dx++) {
        s += luz(img.data, (((y * f + dy) * img.width) + (x * f + dx)) * 4); n++;
      }
      gris[y * w + x] = s / n;
    }
    return { gris, w, h, f };
  }

  function desenfocar(gris, w, h) {
    const o = new Uint8Array(gris.length);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      let s = 0, n = 0;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        const xx = x + dx, yy = y + dy;
        if (xx >= 0 && yy >= 0 && xx < w && yy < h) { s += gris[yy * w + xx]; n++; }
      }
      o[y * w + x] = s / n;
    }
    return o;
  }

  // Umbral de Otsu: separa lo claro (la hoja) de lo oscuro (la mesa).
  function umbralOtsu(gris) {
    const h = new Array(256).fill(0);
    for (const v of gris) h[v]++;
    const total = gris.length;
    let suma = 0;
    for (let i = 0; i < 256; i++) suma += i * h[i];
    let sumaB = 0, wB = 0, mejor = 0, umbral = 128;
    for (let t = 0; t < 256; t++) {
      wB += h[t];
      if (!wB) continue;
      const wF = total - wB;
      if (!wF) break;
      sumaB += t * h[t];
      const mB = sumaB / wB, mF = (suma - sumaB) / wF;
      const varianza = wB * wF * (mB - mF) * (mB - mF);
      if (varianza > mejor) { mejor = varianza; umbral = t; }
    }
    return umbral;
  }

  function areaCuadrilatero(p) {
    let a = 0;
    for (let i = 0; i < 4; i++) { const q = p[(i + 1) % 4]; a += p[i].x * q.y - q.x * p[i].y; }
    return Math.abs(a) / 2;
  }

  // Ordena 4 puntos: arriba-izquierda, arriba-derecha, abajo-derecha, abajo-izquierda.
  function ordenarEsquinas(pts) {
    const suma = pts.map((p) => p.x + p.y), dif = pts.map((p) => p.x - p.y);
    const idx = (a, f) => a.indexOf(f(...a));
    return [pts[idx(suma, Math.min)], pts[idx(dif, Math.max)], pts[idx(suma, Math.max)], pts[idx(dif, Math.min)]];
  }

  // Busca la hoja: la región clara más grande. Devuelve {esquinas, detectada}; si no la encuentra, un marco casi completo.
  function detectarHoja(img) {
    const { gris, w, h, f } = reducir(img, 320);
    const g = desenfocar(gris, w, h);
    const t = umbralOtsu(g);
    const etiqueta = new Int32Array(w * h);
    let mejor = null, id = 0;
    const pila = new Int32Array(w * h);
    for (let i0 = 0; i0 < w * h; i0++) {
      if (g[i0] <= t || etiqueta[i0]) continue;
      id++;
      let tope = 0, area = 0;
      pila[tope++] = i0; etiqueta[i0] = id;
      const ext = { tl: null, tr: null, br: null, bl: null }; // extremos por x+y y x−y
      let minS = Infinity, maxS = -Infinity, minD = Infinity, maxD = -Infinity;
      while (tope) {
        const i = pila[--tope], x = i % w, y = (i - x) / w;
        area++;
        const s = x + y, d = x - y;
        if (s < minS) { minS = s; ext.tl = { x, y }; }
        if (s > maxS) { maxS = s; ext.br = { x, y }; }
        if (d > maxD) { maxD = d; ext.tr = { x, y }; }
        if (d < minD) { minD = d; ext.bl = { x, y }; }
        if (x > 0 && g[i - 1] > t && !etiqueta[i - 1]) { etiqueta[i - 1] = id; pila[tope++] = i - 1; }
        if (x < w - 1 && g[i + 1] > t && !etiqueta[i + 1]) { etiqueta[i + 1] = id; pila[tope++] = i + 1; }
        if (y > 0 && g[i - w] > t && !etiqueta[i - w]) { etiqueta[i - w] = id; pila[tope++] = i - w; }
        if (y < h - 1 && g[i + w] > t && !etiqueta[i + w]) { etiqueta[i + w] = id; pila[tope++] = i + w; }
      }
      if (!mejor || area > mejor.area) mejor = { area, ext };
    }
    const marco = (m) => [{ x: img.width * m, y: img.height * m }, { x: img.width * (1 - m), y: img.height * m },
      { x: img.width * (1 - m), y: img.height * (1 - m) }, { x: img.width * m, y: img.height * (1 - m) }];
    if (mejor) {
      const esq = [mejor.ext.tl, mejor.ext.tr, mejor.ext.br, mejor.ext.bl].map((p) => ({ x: (p.x + 0.5) * f, y: (p.y + 0.5) * f }));
      const frac = areaCuadrilatero(esq) / (img.width * img.height);
      if (frac >= 0.15 && frac < 0.97) {
        // Un poco hacia adentro, para no incluir el borde ni la sombra de la hoja
        const c = { x: esq.reduce((s, p) => s + p.x, 0) / 4, y: esq.reduce((s, p) => s + p.y, 0) / 4 };
        const dentro = esq.map((p) => ({ x: p.x + (c.x - p.x) * 0.006, y: p.y + (c.y - p.y) * 0.006 }));
        return { esquinas: dentro, detectada: true };
      }
    }
    return { esquinas: marco(0.03), detectada: false };
  }

  // Resuelve el sistema lineal A·x = b (eliminación gaussiana con pivote).
  function resolver(A, b) {
    const n = b.length;
    for (let i = 0; i < n; i++) {
      let m = i;
      for (let r = i + 1; r < n; r++) if (Math.abs(A[r][i]) > Math.abs(A[m][i])) m = r;
      [A[i], A[m]] = [A[m], A[i]]; [b[i], b[m]] = [b[m], b[i]];
      for (let r = i + 1; r < n; r++) {
        const k = A[r][i] / A[i][i];
        for (let c = i; c < n; c++) A[r][c] -= k * A[i][c];
        b[r] -= k * b[i];
      }
    }
    const x = new Array(n).fill(0);
    for (let i = n - 1; i >= 0; i--) {
      let s = b[i];
      for (let c = i + 1; c < n; c++) s -= A[i][c] * x[c];
      x[i] = s / A[i][i];
    }
    return x;
  }

  // Homografía que lleva los puntos `de` a los puntos `a` (4 pares).
  function homografia(de, a) {
    const A = [], b = [];
    for (let i = 0; i < 4; i++) {
      const { x, y } = de[i], { x: u, y: v } = a[i];
      A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.push(u);
      A.push([0, 0, 0, x, y, 1, -v * x, -v * y]); b.push(v);
    }
    return resolver(A, b);
  }

  const distancia = (p, q) => Math.hypot(p.x - q.x, p.y - q.y);

  // Endereza la hoja: devuelve una imagen rectangular de lado mayor ≤ maxLado.
  function enderezar(img, esquinas, maxLado) {
    const [tl, tr, br, bl] = esquinas;
    let W = Math.max(distancia(tl, tr), distancia(bl, br)), H = Math.max(distancia(tl, bl), distancia(tr, br));
    const k = Math.min(1, (maxLado || 2000) / Math.max(W, H));
    W = Math.max(2, Math.round(W * k)); H = Math.max(2, Math.round(H * k));
    const m = homografia([{ x: 0, y: 0 }, { x: W, y: 0 }, { x: W, y: H }, { x: 0, y: H }], esquinas);
    const out = new Uint8ClampedArray(W * H * 4), s = img.data;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const d = m[6] * x + m[7] * y + 1;
      const sx = (m[0] * x + m[1] * y + m[2]) / d, sy = (m[3] * x + m[4] * y + m[5]) / d;
      const x0 = Math.min(Math.max(Math.floor(sx), 0), img.width - 2), y0 = Math.min(Math.max(Math.floor(sy), 0), img.height - 2);
      const fx = Math.min(Math.max(sx - x0, 0), 1), fy = Math.min(Math.max(sy - y0, 0), 1);
      const o = (y * W + x) * 4, i00 = (y0 * img.width + x0) * 4, i10 = i00 + 4, i01 = i00 + img.width * 4, i11 = i01 + 4;
      for (let c = 0; c < 3; c++) {
        out[o + c] = s[i00 + c] * (1 - fx) * (1 - fy) + s[i10 + c] * fx * (1 - fy) + s[i01 + c] * (1 - fx) * fy + s[i11 + c] * fx * fy;
      }
      out[o + 3] = 255;
    }
    return { data: out, width: W, height: H };
  }

  // Fondo de la hoja (su nivel de "papel") estimado por bloques, para quitar sombras y luz despareja.
  function fondo(img) {
    const b = Math.max(8, Math.round(Math.max(img.width, img.height) / 48));
    const gw = Math.ceil(img.width / b), gh = Math.ceil(img.height / b);
    let grid = new Float32Array(gw * gh);
    for (let gy = 0; gy < gh; gy++) for (let gx = 0; gx < gw; gx++) {
      const vals = [];
      for (let y = gy * b; y < Math.min(img.height, (gy + 1) * b); y += 2) for (let x = gx * b; x < Math.min(img.width, (gx + 1) * b); x += 2) {
        vals.push(luz(img.data, (y * img.width + x) * 4));
      }
      vals.sort((p, q) => p - q);
      grid[gy * gw + gx] = vals[Math.floor(vals.length * 0.9)] || 255; // el 90 %: el papel, no la tinta
    }
    for (let pasada = 0; pasada < 2; pasada++) {
      const n = new Float32Array(grid.length);
      for (let gy = 0; gy < gh; gy++) for (let gx = 0; gx < gw; gx++) {
        let s = 0, c = 0;
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
          const xx = gx + dx, yy = gy + dy;
          if (xx >= 0 && yy >= 0 && xx < gw && yy < gh) { s += grid[yy * gw + xx]; c++; }
        }
        n[gy * gw + gx] = s / c;
      }
      grid = n;
    }
    return (x, y) => {
      const fx = Math.min(Math.max(x / b - 0.5, 0), gw - 1), fy = Math.min(Math.max(y / b - 0.5, 0), gh - 1);
      const x0 = Math.min(Math.floor(fx), gw - 2 < 0 ? 0 : gw - 2), y0 = Math.min(Math.floor(fy), gh - 2 < 0 ? 0 : gh - 2);
      const ax = fx - x0, ay = fy - y0, x1 = Math.min(x0 + 1, gw - 1), y1 = Math.min(y0 + 1, gh - 1);
      return grid[y0 * gw + x0] * (1 - ax) * (1 - ay) + grid[y0 * gw + x1] * ax * (1 - ay)
        + grid[y1 * gw + x0] * (1 - ax) * ay + grid[y1 * gw + x1] * ax * ay;
    };
  }

  // Mejora de escáner. modo "escaner": blanco y negro limpio; "color": color con el fondo aclarado.
  function mejorar(img, modo) {
    const bg = fondo(img), d = img.data, n = img.width * img.height;
    const out = new Uint8ClampedArray(n * 4), norm = new Uint8Array(n), hist = new Array(256).fill(0);
    for (let y = 0; y < img.height; y++) for (let x = 0; x < img.width; x++) {
      const i = y * img.width + x, v = Math.min(255, luz(d, i * 4) / Math.max(bg(x, y), 1) * 255);
      norm[i] = v; hist[Math.round(v)]++;
    }
    let acum = 0, bajo = 0;
    for (let v = 0; v < 256; v++) { acum += hist[v]; if (acum >= n * 0.01) { bajo = v; break; } }
    const curva = (v) => { // estira entre el negro de la tinta y el blanco del papel, con una S suave
      const t = Math.min(Math.max((v - bajo) / (245 - bajo), 0), 1);
      return 255 * (t * t * (3 - 2 * t));
    };
    for (let y = 0; y < img.height; y++) for (let x = 0; x < img.width; x++) {
      const i = y * img.width + x, o = i * 4;
      if (modo === "color") {
        const k = Math.min(255 / Math.max(bg(x, y), 1), 3);
        for (let c = 0; c < 3; c++) out[o + c] = curva(d[o + c] * k);
      } else {
        const g = curva(norm[i]);
        out[o] = out[o + 1] = out[o + 2] = g;
      }
      out[o + 3] = 255;
    }
    return { data: out, width: img.width, height: img.height };
  }

  const api = { detectarHoja, ordenarEsquinas, homografia, enderezar, mejorar, areaCuadrilatero };
  raiz.Escaner = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
