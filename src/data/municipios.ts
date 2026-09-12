import type { Categoria, Local, Poi } from '@/lib/heat';
import { bboxDeCentro } from '@/lib/heat';

/**
 * De dónde salen los datos del mapa.
 *
 * Hay tres piezas y conviene no confundirlas:
 *
 * - El **catálogo** son los 8.132 municipios de España, del INE. Alimenta los
 *   desplegables y existe aunque no haya ni un punto cargado.
 * - El **índice** dice qué municipios tienen datos de verdad, y con qué centro,
 *   zoom y radio abrirlos. Lo genera `scripts/exportar_espana.py` desde
 *   Supabase, y el centro sale de la mediana de los puntos del municipio, no
 *   de una lista escrita a mano.
 * - Los **ficheros de provincia** (`/datos/p08.json`) llevan los puntos.
 *
 * **Por provincia y no por municipio.** Un corte municipal tiene que salirse
 * del término —una notaría al otro lado del límite es competencia real—, así
 * que se toma por caja alrededor del centro. Con mil municipios esas cajas se
 * solapan tanto en el área metropolitana que el mismo punto acabaría copiado
 * en decenas de ficheros. Por provincia cada punto aparece una vez, y moverse
 * entre municipios de la misma provincia no cuesta ninguna descarga.
 *
 * **Y no una consulta directa a Supabase**, porque la clave publicable viaja
 * en el bundle de JavaScript: dar lectura al rol anónimo sobre `pois` dejaría
 * descargarse el censo entero —el activo que se vende— de una petición. Ver la
 * sección de privilegios de `infra/schema.sql`.
 */

export interface Municipio {
  codIne: string;
  nombre: string;
  provincia: string;
  centro: [number, number]; // [lon, lat]
  zoom: number;
  /** Radio en metros del área que se carga y se analiza. Sale de la dispersión
   *  real de los puntos del municipio: 2,5 km en un pueblo, 12 km en Madrid. */
  radio: number;
}

/**
 * Registros que están en la base de datos pero no han podido entrar al mapa.
 * Se declaran en la interfaz en vez de descartarse en silencio: una notaría
 * que falta en la capa de competencia hace que el mapa recomiende el portal de
 * al lado de una notaría existente, y eso, delante de un cliente, se paga caro.
 */
export interface Incidencia {
  categoria: string;
  nombre: string;
  direccion: string;
  motivo: string;
  codIne?: string | null;
}

export interface Corte {
  municipio: Municipio;
  pois: Poi[];
  locales: Local[];
  incidencias: Incidencia[];
}

export interface FichaMunicipio {
  nombre: string;
  provincia: string;
  codProvincia: string;
  centro: [number, number];
  zoom: number;
  radio: number;
  conteos: Partial<Record<Categoria, number>>;
  demanda: number;
  competencia: number;
}

export interface Indice {
  municipios: Record<string, FichaMunicipio>;
  provincias: Record<string, { nombre: string; puntos: number; kb: number }>;
}

export interface Provincia {
  cod: string;
  nombre: string;
  municipios: [string, string][]; // [codIne, nombre]
}

export interface ComunidadAutonoma {
  cod: string;
  nombre: string;
  provincias: Provincia[];
}

export interface Catalogo {
  fuente: string;
  ccaa: ComunidadAutonoma[];
}

export const PROCEDENCIA =
  'Notarías: Consejo General del Notariado. Oficinas bancarias: Banco de España. ' +
  'Inmobiliarias, despachos y gestorías: Overture Maps. Locales: Idealista.';

export const MUNICIPIO_POR_DEFECTO = '08187'; // Sabadell

// `BASE_URL` y no una barra suelta: si algún día esto se sirve bajo una
// subcarpeta, una ruta absoluta pediría los datos a la raíz del dominio.
const BASE = `${import.meta.env.BASE_URL}datos/`;

async function traeJson<T>(ruta: string): Promise<T> {
  const r = await fetch(ruta);
  if (!r.ok) throw new Error(`${ruta}: el servidor respondió ${r.status}`);
  return (await r.json()) as T;
}

let indice: Indice | null = null;
let pidiendoIndice: Promise<Indice> | null = null;

/** El índice pesa unos pocos cientos de KB y lo necesita todo, así que se pide una vez. */
export function cargaIndice(): Promise<Indice> {
  if (indice) return Promise.resolve(indice);
  // Sin esto, el selector y el mapa piden el índice a la vez al arrancar y se
  // descarga dos veces.
  pidiendoIndice ??= traeJson<Indice>(`${BASE}indice.json`).then((i) => {
    indice = i;
    return i;
  });
  return pidiendoIndice;
}

export function tieneDatos(codIne: string): boolean {
  return Boolean(indice?.municipios[codIne]);
}

export function ficha(codIne: string): FichaMunicipio | undefined {
  return indice?.municipios[codIne];
}

interface DatosProvincia {
  cod: string;
  nombre: string;
  pois: Poi[];
  locales: Local[];
  incidencias: Incidencia[];
}

const provincias = new Map<string, Promise<DatosProvincia>>();

function cargaProvincia(cod: string): Promise<DatosProvincia> {
  let p = provincias.get(cod);
  if (!p) {
    p = traeJson<DatosProvincia>(`${BASE}p${cod}.json`).catch((e) => {
      // Si falla, se quita de la caché: si no, un corte de red al arrancar
      // dejaría esa provincia rota para el resto de la sesión.
      provincias.delete(cod);
      throw e;
    });
    provincias.set(cod, p);
  }
  return p;
}

const cortes = new Map<string, Corte>();

export async function cargaCorte(codIne: string): Promise<Corte> {
  const enCache = cortes.get(codIne);
  if (enCache) return enCache;

  const idx = await cargaIndice();
  const f = idx.municipios[codIne];
  if (!f) throw new Error(`el municipio ${codIne} no tiene datos cargados`);

  const datos = await cargaProvincia(f.codProvincia);

  // La caja se toma alrededor del centro del municipio y se sale de él a
  // propósito: los puntos del pueblo de al lado son competencia y demanda
  // reales, y recortarlos en el límite administrativo daría un borde artificial
  // justo donde el modelo tiene que decidir.
  const b = bboxDeCentro(f.centro, f.radio);
  const dentro = (p: { lat: number; lon: number }) =>
    p.lat >= b.minLat && p.lat <= b.maxLat && p.lon >= b.minLon && p.lon <= b.maxLon;

  const corte: Corte = {
    municipio: {
      codIne,
      nombre: f.nombre,
      provincia: f.provincia,
      centro: f.centro,
      zoom: f.zoom,
      radio: f.radio,
    },
    pois: datos.pois.filter(dentro),
    locales: (datos.locales ?? []).filter(dentro),
    // Las incidencias sí van por municipio y no por caja: son registros sin
    // coordenada, así que no tienen sitio en el mapa que los sitúe.
    incidencias: (datos.incidencias ?? []).filter((i) => i.codIne === codIne),
  };
  cortes.set(codIne, corte);
  return corte;
}

let catalogo: Catalogo | null = null;

/** El catálogo son 206 KB, así que se pide una sola vez y se guarda. */
export async function cargaCatalogo(): Promise<Catalogo> {
  if (!catalogo) {
    // Por `unknown`: TypeScript infiere los pares [código, nombre] del JSON
    // como string[][] y no como la tupla de dos, que es lo que declara el
    // tipo. La forma la garantiza scripts/catalogo_municipios.py.
    const modulo = (await import('./municipios.json')) as unknown as { default: Catalogo };
    catalogo = modulo.default;
  }
  return catalogo;
}

/** Dónde está un municipio dentro del árbol, para posicionar los desplegables. */
export function ubica(
  cat: Catalogo,
  codIne: string,
): { ccaa: string; provincia: string } | null {
  for (const c of cat.ccaa) {
    for (const p of c.provincias) {
      if (p.municipios.some(([cod]) => cod === codIne)) {
        return { ccaa: c.cod, provincia: p.cod };
      }
    }
  }
  return null;
}
