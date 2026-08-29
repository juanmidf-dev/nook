import type { Categoria } from '@/lib/heat';

/**
 * Color del mapa.
 *
 * El score es una magnitud continua, así que se codifica con una rampa
 * secuencial de un solo tono (azul), de oscuro a claro. Sobre cartografía
 * oscura el extremo bajo tiene que ser el que se funde con el fondo, de ahí
 * que la rampa vaya al revés que en un gráfico sobre fondo blanco.
 *
 * Las categorías de puntos NO se codifican por color: se codifican por forma.
 * Se probó la terna azul / naranja / aguamarina y la separación cae a ΔE 1,6
 * en deuteranopía, es decir, indistinguible para una parte apreciable de los
 * usuarios. Con formas geométricas distintas y una sola tinta clara, el mapa
 * se lee igual de bien con cualquier visión, y además deja el canal de color
 * libre para lo único que de verdad varía de forma continua: el score.
 */

/** Rampa secuencial azul, extremo bajo -> extremo alto. */
export const RAMPA_SCORE = ['#0d366b', '#184f95', '#256abf', '#3987e5', '#86b6ef'] as const;

/** Color de estado, reservado para la competencia. Siempre con forma + etiqueta. */
export const COLOR_COMPETENCIA = '#f08a8a';

/** Tinta de los marcadores de demanda y su halo sobre el mapa. */
export const TINTA_MARCADOR = '#eef3fb';
export const HALO_MARCADOR = '#0a0e17';

export type Forma = 'cuadrado' | 'triangulo' | 'rombo' | 'anillo' | 'cruz' | 'circulo';

/**
 * Los locales en alquiler llevan una cruz: es la forma más distinta de las
 * tres geométricas de demanda, y a tamaño pequeño no se confunde con ninguna.
 */
export const FORMA_LOCAL: Forma = 'cruz';

export const FORMA_POR_CATEGORIA: Record<Categoria, Forma> = {
  banco: 'cuadrado',
  inmobiliaria: 'triangulo',
  abogados: 'rombo',
  notaria: 'anillo',
  // Círculo relleno para las gestorías. Es la quinta forma geométrica que
  // sigue leyéndose a 13 px, y no se confunde con el anillo de la notaría:
  // aquélla es hueca y roja, ésta es maciza y de la tinta de demanda. Dos
  // canales de diferencia, no uno.
  gestoria: 'circulo',
};

/** Paradas de la rampa en score 0-100, para la expresión de Mapbox y la leyenda. */
export function paradasScore(): [number, string][] {
  const n = RAMPA_SCORE.length;
  return RAMPA_SCORE.map((hex, i) => [(i / (n - 1)) * 100, hex] as [number, string]);
}
