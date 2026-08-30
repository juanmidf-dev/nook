import type { Local, Poi } from '@/lib/heat';
import type { Incidencia, Municipio } from './sabadell';

/**
 * Catálogo de municipios y cortes de datos disponibles.
 *
 * Son dos cosas distintas y conviene no confundirlas:
 *
 * - El **catálogo** son los 8.132 municipios de España, del INE. Sirve para
 *   que los desplegables ofrezcan cualquier municipio, exista o no dato.
 * - Los **cortes** son los municipios que ya se han exportado desde Supabase
 *   con `scripts/exportar_municipio.py`. Hoy son tres.
 *
 * Que el desplegable ofrezca municipios sin corte es deliberado: enseñar solo
 * tres opciones daría a entender que España tiene tres municipios. Se ofrecen
 * todos y se marca cuáles tienen dato, que es la misma regla que se aplica a
 * los registros que no entran al mapa: se declaran, no se esconden.
 */

export interface Corte {
  municipio: Municipio;
  pois: Poi[];
  locales: Local[];
  incidencias: Incidencia[];
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

/**
 * Cortes exportados, por código INE.
 *
 * Se enumeran a mano en vez de con `import.meta.glob` para que el compilador
 * avise si se referencia uno que no existe, en lugar de fallar al pulsar el
 * desplegable. Cada uno se carga bajo demanda: el corte de Madrid son 1,2 MB
 * y el de Sabadell 90 KB, así que meterlos juntos en el bundle haría que
 * abrir un municipio pequeño costara descargar los grandes.
 */
const CORTES: Record<string, () => Promise<{ default: unknown }>> = {
  '08187': () => import('./sabadell.json'),
  '08019': () => import('./barcelona.json'),
  '28079': () => import('./madrid.json'),
};

export const CODIGOS_CON_CORTE = new Set(Object.keys(CORTES));

export const MUNICIPIO_POR_DEFECTO = '08187'; // Sabadell

export function tieneCorte(codIne: string): boolean {
  return CODIGOS_CON_CORTE.has(codIne);
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

const cache = new Map<string, Corte>();

export async function cargaCorte(codIne: string): Promise<Corte> {
  const enCache = cache.get(codIne);
  if (enCache) return enCache;

  const cargador = CORTES[codIne];
  if (!cargador) throw new Error(`sin corte exportado para el municipio ${codIne}`);

  const datos = (await cargador()).default as {
    municipio: Municipio;
    pois: Poi[];
    locales?: Local[];
    incidencias?: Incidencia[];
  };

  const corte: Corte = {
    municipio: datos.municipio,
    pois: datos.pois,
    locales: datos.locales ?? [],
    incidencias: datos.incidencias ?? [],
  };
  cache.set(codIne, corte);
  return corte;
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
