import datos from './sabadell.json';
import type { Local, Poi } from '@/lib/heat';

/**
 * Datos reales de Sabadell, exportados desde Supabase.
 *
 * Los genera `scripts/exportar_municipio.py` desde la base de datos, y los
 * refresca el workflow «Exportar corte para el mapa».
 *
 * Es un fichero y no una consulta desde el navegador a propósito: la clave
 * publicable de Supabase viaja en el bundle de JavaScript, así que conceder
 * lectura sobre `pois` al rol anónimo permitiría descargarse el censo de
 * competencia y los puntos de demanda —el activo que se vende— con una sola
 * petición. Ver la sección de privilegios de `infra/schema.sql`.
 *
 * Los sliders siguen recalculando en vivo en el navegador, que es lo que hace
 * la herramienta usable; lo único que se pierde es que los datos son tan
 * frescos como la última exportación, y la ingesta es mensual.
 */

export interface Municipio {
  codIne: string;
  nombre: string;
  provincia: string;
  centro: [number, number]; // [lon, lat]
  zoom: number;
}

export const MUNICIPIO: Municipio = datos.municipio as Municipio;

export const POIS: Poi[] = datos.pois as Poi[];
export const LOCALES: Local[] = datos.locales as Local[];

/**
 * Registros que venían en los Excel pero no han podido entrar al mapa. Se
 * declaran en la interfaz en vez de descartarse en silencio: una notaría que
 * falta en la capa de competencia hace que el mapa recomiende el portal de al
 * lado de una notaría existente, y eso, delante de un cliente, se paga caro.
 */
export interface Incidencia {
  categoria: string;
  nombre: string;
  direccion: string;
  motivo: string;
}

export const INCIDENCIAS: Incidencia[] = (datos.incidencias ?? []) as Incidencia[];

export const PROCEDENCIA =
  'Notarías: Consejo General del Notariado. Oficinas bancarias: Banco de España. ' +
  'Inmobiliarias, despachos y gestorías: Overture Maps. Locales: Idealista.';
