import datos from './sabadell.json';
import type { Local, Poi } from '@/lib/heat';

/**
 * Datos reales de Sabadell.
 *
 * Origen: los volcados que ya tenía el proyecto (notarías del Consejo General
 * del Notariado, oficinas bancarias del Banco de España, agencias
 * inmobiliarias, y locales en alquiler de Idealista), convertidos desde los
 * Excel de `Raw data/xlsx`. Es un corte estático: hasta que el pipeline de
 * ingesta escriba en Supabase, estos datos no se refrescan solos.
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
  'Datos de Sabadell: Consejo General del Notariado, Banco de España e Idealista. Corte estático.';
