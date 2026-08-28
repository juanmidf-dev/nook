/**
 * Motor de calor de Nook.
 *
 * Convierte una nube de puntos (notarías = competencia; bancos, inmobiliarias
 * y despachos = demanda) en un score por celda hexagonal H3.
 *
 * Corre en el navegador a propósito: con los sliders de ponderación el notario
 * necesita ver el mapa recalcularse mientras arrastra, y una ida y vuelta al
 * servidor por cada movimiento del slider haría la herramienta inservible.
 * Para un municipio (unos pocos miles de celdas y de puntos) el cálculo
 * completo baja de los 200 ms. El mismo modelo existe en Python para el
 * precálculo por lotes y los informes en PDF; las dos implementaciones tienen
 * que dar el mismo número.
 */

import { cellToBoundary, cellToLatLng, polygonToCells } from 'h3-js';

export type Categoria = 'notaria' | 'banco' | 'inmobiliaria' | 'abogados';

export type CategoriaDemanda = Exclude<Categoria, 'notaria'>;

export const CATEGORIAS: Categoria[] = ['notaria', 'banco', 'inmobiliaria', 'abogados'];
export const CATEGORIAS_DEMANDA: CategoriaDemanda[] = ['banco', 'inmobiliaria', 'abogados'];

/** Etiquetas cortas para columnas estrechas, donde la larga se trunca. */
export const ETIQUETAS_CORTAS: Record<Categoria, string> = {
  notaria: 'Notarías',
  banco: 'Bancos',
  inmobiliaria: 'Inmobiliarias',
  abogados: 'Abogados',
};

export const ETIQUETAS: Record<Categoria, string> = {
  notaria: 'Notarías',
  banco: 'Oficinas bancarias',
  inmobiliaria: 'Inmobiliarias',
  abogados: 'Despachos de abogados',
};

export interface Poi {
  id: string;
  nombre: string;
  categoria: Categoria;
  lat: number;
  lon: number;
  direccion?: string;
  telefono?: string;
  email?: string;
  web?: string;
}

/**
 * Solo se ponderan las categorías de demanda. Las notarías no llevan peso
 * propio: la capa de competencia se normaliza a 0-1 por sí sola, así que
 * multiplicarla por una constante antes de normalizar no cambiaría nada. Lo
 * que sí cambia el mapa es `pesoCompetencia`, que actúa después.
 */
export type Pesos = Record<CategoriaDemanda, number>;

/**
 * Un local en alquiler. No entra en el cálculo del score: no es demanda ni
 * competencia, es la oferta que permite materializar una ubicación buena.
 * Se cruza con el mapa después, para responder a "esta zona puntúa alto,
 * ¿hay algo disponible aquí?".
 */
export interface Local {
  id: string;
  nombre: string;
  direccion?: string;
  fuente?: string;
  url?: string;
  precioMes?: number;
  superficieM2?: number;
  lat: number;
  lon: number;
}

export interface Config {
  resolucion: number;
  /** Sigma del kernel gaussiano, en metros. */
  bandwidthM: number;
  pesos: Pesos;
  /**
   * Cuánto castiga la competencia una vez demanda y competencia están en la
   * misma escala 0-1. 0 = ignorar las notarías existentes; 1 = una zona
   * saturada anula por completo su demanda.
   */
  pesoCompetencia: number;
}

export const CONFIG_POR_DEFECTO: Config = {
  resolucion: 9,
  bandwidthM: 600,
  pesos: { banco: 1, inmobiliaria: 1, abogados: 1 },
  pesoCompetencia: 0.7,
};

export interface Celda {
  h3: string;
  lat: number;
  lon: number;
  score: number;
  demanda: number;
  competencia: number;
  /** Aportación bruta de cada categoría, para explicar el resultado. */
  detalle: Partial<Record<Categoria, number>>;
}

/** Más allá de 3 sigma la aportación es < 1,2 % del peso. */
const CORTE_SIGMAS = 3;

/* ------------------------------------------------------------------ *
 * Proyección local
 * ------------------------------------------------------------------ */

/**
 * A escala de ciudad (< 50 km) una equirectangular centrada en la propia
 * ciudad tiene un error inferior al 0,1 %, muy por debajo de la incertidumbre
 * de la geocodificación. Evita cargar proj4 entero en el bundle.
 */
function proyector(latRef: number) {
  const mPorGradoLat = 111132.95;
  const mPorGradoLon = 111320 * Math.cos((latRef * Math.PI) / 180);
  return (lat: number, lon: number): [number, number] => [lon * mPorGradoLon, lat * mPorGradoLat];
}

/* ------------------------------------------------------------------ *
 * Rejilla
 * ------------------------------------------------------------------ */

export type BBox = { minLat: number; minLon: number; maxLat: number; maxLon: number };

export function bboxDePuntos(pois: Poi[], margenM = 1500): BBox {
  const lats = pois.map((p) => p.lat);
  const lons = pois.map((p) => p.lon);
  const latRef = (Math.min(...lats) + Math.max(...lats)) / 2;
  const dLat = margenM / 111132.95;
  const dLon = margenM / (111320 * Math.cos((latRef * Math.PI) / 180));
  return {
    minLat: Math.min(...lats) - dLat,
    maxLat: Math.max(...lats) + dLat,
    minLon: Math.min(...lons) - dLon,
    maxLon: Math.max(...lons) + dLon,
  };
}

/**
 * Caja de análisis a partir del centro del municipio y un radio.
 *
 * Se prefiere esto a derivar la caja de la extensión de los puntos: una sola
 * coordenada mal geocodificada —y en datos reales siempre la hay— estira la
 * caja decenas de kilómetros, multiplica por treinta el número de celdas y
 * deja el mapa lleno de celdas vacías que, al normalizar, acaban puntuando
 * alto por comparación con un entorno igual de vacío.
 */
export function bboxDeCentro(centro: [number, number], radioM: number): BBox {
  const [lon, lat] = centro;
  const dLat = radioM / 111132.95;
  const dLon = radioM / (111320 * Math.cos((lat * Math.PI) / 180));
  return { minLat: lat - dLat, maxLat: lat + dLat, minLon: lon - dLon, maxLon: lon + dLon };
}

export function celdasDeBBox(b: BBox, resolucion: number): string[] {
  return polygonToCells(
    [
      [
        [b.minLat, b.minLon],
        [b.minLat, b.maxLon],
        [b.maxLat, b.maxLon],
        [b.maxLat, b.minLon],
      ],
    ],
    resolucion,
  );
}

/** Contorno de la celda como anillo GeoJSON [lon, lat]. */
export function contorno(h3Index: string): [number, number][] {
  return cellToBoundary(h3Index).map(([lat, lon]) => [lon, lat] as [number, number]);
}

/* ------------------------------------------------------------------ *
 * Cálculo
 * ------------------------------------------------------------------ */

export function calcular(celdas: string[], pois: Poi[], cfg: Config): Celda[] {
  if (celdas.length === 0) return [];

  const centros = celdas.map((c) => cellToLatLng(c));
  const latRef = centros[0][0];
  const proj = proyector(latRef);
  const xy = centros.map(([lat, lon]) => proj(lat, lon));

  const sigma = Math.max(cfg.bandwidthM, 1);
  const radio = CORTE_SIGMAS * sigma;
  const dosSigma2 = 2 * sigma * sigma;

  // Rejilla de cubos del tamaño del radio de corte: por cada punto solo se
  // miran las celdas de los 9 cubos vecinos en vez de las del municipio
  // entero. Sin esto, Madrid a resolución 9 son decenas de millones de
  // distancias por cada movimiento del slider.
  const cubos = new Map<string, number[]>();
  const clave = (x: number, y: number) => `${Math.floor(x / radio)}:${Math.floor(y / radio)}`;
  xy.forEach(([x, y], i) => {
    const k = clave(x, y);
    const lista = cubos.get(k);
    if (lista) lista.push(i);
    else cubos.set(k, [i]);
  });

  const aporte = new Map<Categoria, Float64Array>();
  for (const cat of CATEGORIAS) {
    const delTipo = pois.filter((p) => p.categoria === cat);
    if (delTipo.length === 0) continue;
    const acc = new Float64Array(celdas.length);

    for (const p of delTipo) {
      const [px, py] = proj(p.lat, p.lon);
      const cx = Math.floor(px / radio);
      const cy = Math.floor(py / radio);
      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          const lista = cubos.get(`${cx + dx}:${cy + dy}`);
          if (!lista) continue;
          for (const i of lista) {
            const ddx = xy[i][0] - px;
            const ddy = xy[i][1] - py;
            const d2 = ddx * ddx + ddy * ddy;
            if (d2 > radio * radio) continue;
            acc[i] += Math.exp(-d2 / dosSigma2);
          }
        }
      }
    }
    aporte.set(cat, acc);
  }

  const demanda = new Float64Array(celdas.length);
  const competencia = new Float64Array(celdas.length);
  for (const [cat, acc] of aporte) {
    if (cat === 'notaria') {
      for (let i = 0; i < acc.length; i++) competencia[i] += acc[i];
    } else {
      const peso = cfg.pesos[cat] ?? 0;
      for (let i = 0; i < acc.length; i++) demanda[i] += peso * acc[i];
    }
  }

  // La demanda y la competencia se normalizan por separado antes de
  // combinarse. Restarlas en bruto no funciona: en una ciudad hay del orden
  // de diez veces más oficinas bancarias que notarías, así que la demanda
  // domina la resta y el máximo acaba cayendo justo encima del casco
  // antiguo, que es exactamente donde ya están todas las notarías. Con las
  // dos capas en escala 0-1, `pesoCompetencia` significa algo interpretable:
  // cuánto se descuenta por estar en zona saturada.
  const demN = normalizar(demanda);
  const compN = normalizar(competencia);
  const bruto = new Float64Array(celdas.length);
  for (let i = 0; i < bruto.length; i++) bruto[i] = demN[i] - cfg.pesoCompetencia * compN[i];
  // Min-max sin recortar colas: las capas de entrada ya vienen recortadas y
  // aquí interesa conservar el orden exacto entre las mejores celdas. Si se
  // recorta otra vez, la docena de celdas punteras empata a 100 y el ranking
  // de ubicaciones deja de servir.
  const score = minmax(bruto);

  return celdas.map((h3Index, i) => ({
    h3: h3Index,
    lat: centros[i][0],
    lon: centros[i][1],
    score: score[i] * 100,
    demanda: demanda[i],
    competencia: competencia[i],
    detalle: Object.fromEntries(
      [...aporte.entries()].map(([cat, acc]) => [cat, acc[i]]),
    ) as Partial<Record<Categoria, number>>,
  }));
}

/**
 * Lleva un vector a 0-1 recortando por los percentiles 2 y 98. Sin el recorte
 * un único centro urbano muy denso aplasta el resto del mapa contra el 0 y el
 * heatmap se ve plano fuera del centro; recortando las colas se conserva el
 * contraste en las zonas intermedias, que son justo donde el notario decide.
 */
function normalizar(v: Float64Array): Float64Array {
  const out = new Float64Array(v.length);
  if (v.length === 0) return out;
  const orden = Float64Array.from(v).sort();
  const lo = percentil(orden, 2);
  const hi = percentil(orden, 98);
  // Sin rango no hay señal. Devolver 0,5 repartiría media penalización por
  // igual a todo el mapa cuando, por ejemplo, un municipio no tiene ninguna
  // notaría — que es justo el caso que más le interesa a un notario nuevo.
  if (hi - lo < 1e-9) return out;
  for (let i = 0; i < v.length; i++) out[i] = Math.min(1, Math.max(0, (v[i] - lo) / (hi - lo)));
  return out;
}

function minmax(v: Float64Array): Float64Array {
  const out = new Float64Array(v.length);
  if (v.length === 0) return out;
  let lo = Infinity;
  let hi = -Infinity;
  for (const x of v) {
    if (x < lo) lo = x;
    if (x > hi) hi = x;
  }
  if (hi - lo < 1e-9) return out.fill(0.5);
  for (let i = 0; i < v.length; i++) out[i] = (v[i] - lo) / (hi - lo);
  return out;
}

function percentil(ordenado: Float64Array, p: number): number {
  const idx = ((ordenado.length - 1) * p) / 100;
  const bajo = Math.floor(idx);
  const alto = Math.ceil(idx);
  if (bajo === alto) return ordenado[bajo];
  return ordenado[bajo] + (ordenado[alto] - ordenado[bajo]) * (idx - bajo);
}

/* ------------------------------------------------------------------ *
 * Consultas de apoyo
 * ------------------------------------------------------------------ */

/**
 * Mejores celdas con separación mínima entre ellas.
 *
 * Ordenar por score y cortar los doce primeros devuelve doce hexágonos
 * contiguos de la misma manzana: sobre el papel es el ranking correcto, pero
 * como lista de opciones para el notario es una sola opción repetida doce
 * veces. Se aplica supresión de no-máximos: se coge la mejor, se descartan
 * todas las que estén a menos de `separacionM`, y se repite. El resultado son
 * ubicaciones realmente distintas entre las que elegir.
 */
export function mejoresDiversas(celdas: Celda[], n = 8, separacionM = 700): Celda[] {
  const orden = [...celdas].sort((a, b) => b.score - a.score);
  const elegidas: Celda[] = [];
  for (const c of orden) {
    if (elegidas.length >= n) break;
    if (elegidas.every((e) => distanciaM(e.lat, e.lon, c.lat, c.lon) >= separacionM)) {
      elegidas.push(c);
    }
  }
  return elegidas;
}

export function distanciaM(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const R = 6371000;
  const dLat = ((bLat - aLat) * Math.PI) / 180;
  const dLon = ((bLon - aLon) * Math.PI) / 180;
  const la1 = (aLat * Math.PI) / 180;
  const la2 = (bLat * Math.PI) / 180;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

export interface PuntoCercano extends Poi {
  distanciaM: number;
}

export interface LocalCercano extends Local {
  distanciaM: number;
}

export function localesCercanos(
  lat: number,
  lon: number,
  locales: Local[],
  radioM: number,
): LocalCercano[] {
  return locales
    .map((l) => ({ ...l, distanciaM: distanciaM(lat, lon, l.lat, l.lon) }))
    .filter((l) => l.distanciaM <= radioM)
    .sort((a, b) => a.distanciaM - b.distanciaM);
}

/** El listado que se vende como entregable de 199 €. */
export function puntosCercanos(
  lat: number,
  lon: number,
  pois: Poi[],
  radioM: number,
  incluirNotarias = false,
): PuntoCercano[] {
  return pois
    .filter((p) => incluirNotarias || p.categoria !== 'notaria')
    .map((p) => ({ ...p, distanciaM: distanciaM(lat, lon, p.lat, p.lon) }))
    .filter((p) => p.distanciaM <= radioM)
    .sort((a, b) => a.distanciaM - b.distanciaM);
}
