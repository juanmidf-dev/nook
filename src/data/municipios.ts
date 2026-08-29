import type { Local, Poi } from '@/lib/heat';
import type { Incidencia, Municipio } from './sabadell';

/**
 * Los municipios que tienen corte exportado desde Supabase.
 *
 * Cada uno se carga **bajo demanda**, no de una vez al arrancar. No es
 * prematuro: el corte de Barcelona es un orden de magnitud mayor que el de
 * Sabadell, y meterlos todos en el mismo bundle haría que abrir el mapa de un
 * municipio pequeño costara descargar los grandes. Con `import()` cada uno es
 * un fragmento aparte que solo viaja si se selecciona.
 *
 * Añadir un municipio son dos pasos: darlo de alta en `MUNICIPIOS` de
 * `scripts/exportar_municipio.py`, lanzar el workflow «Exportar corte para el
 * mapa», y añadirlo aquí.
 */

export interface Corte {
  municipio: Municipio;
  pois: Poi[];
  locales: Local[];
  incidencias: Incidencia[];
}

export interface EntradaMunicipio {
  clave: string;
  nombre: string;
  provincia: string;
}

export const MUNICIPIOS: EntradaMunicipio[] = [
  { clave: 'sabadell', nombre: 'Sabadell', provincia: 'Barcelona' },
  { clave: 'barcelona', nombre: 'Barcelona', provincia: 'Barcelona' },
  { clave: 'madrid', nombre: 'Madrid', provincia: 'Madrid' },
];

export const MUNICIPIO_POR_DEFECTO = 'sabadell';

// Enumerados a mano y no con `import.meta.glob`: así el compilador avisa si se
// referencia un corte que no existe, en vez de fallar al pulsar el selector.
const CARGADORES: Record<string, () => Promise<{ default: unknown }>> = {
  sabadell: () => import('./sabadell.json'),
  barcelona: () => import('./barcelona.json'),
  madrid: () => import('./madrid.json'),
};

const cache = new Map<string, Corte>();

export async function cargaCorte(clave: string): Promise<Corte> {
  const enCache = cache.get(clave);
  if (enCache) return enCache;

  const cargador = CARGADORES[clave];
  if (!cargador) throw new Error(`no hay corte para "${clave}"`);

  const modulo = await cargador();
  const datos = modulo.default as {
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
  cache.set(clave, corte);
  return corte;
}
