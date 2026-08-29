import type { Categoria } from '@/lib/heat';

/**
 * Color del mapa.
 *
 * El score es una magnitud continua, así que se codifica con una rampa
 * secuencial de un solo tono (azul). **El extremo bajo tiene que ser el que se
 * funde con el fondo**, para que el mapa no quede cubierto por una sábana
 * uniforme y se distinga el relieve del dato.
 *
 * Sobre la cartografía clara actual eso significa que la rampa va de crema a
 * azul marino, es decir, al revés que cuando el mapa era oscuro. Si algún día
 * se vuelve a un mapa oscuro, hay que invertirla otra vez: no es una
 * preferencia estética, es la condición para que el extremo bajo desaparezca.
 *
 * Las categorías de puntos NO se codifican por color: se codifican por forma.
 * Se probó la terna azul / naranja / aguamarina y la separación cae a ΔE 1,6
 * en deuteranopía, es decir, indistinguible para una parte apreciable de los
 * usuarios. Con formas geométricas distintas y una sola tinta clara, el mapa
 * se lee igual de bien con cualquier visión, y además deja el canal de color
 * libre para lo único que de verdad varía de forma continua: el score.
 */

/**
 * Rampa secuencial azul, extremo bajo -> extremo alto.
 *
 * Arranca en el crema de la cartografía y llega al azul marino de la
 * propuesta comercial, `#002C77`. Un solo tono: la saturación y la
 * luminosidad hacen todo el trabajo, así que se lee igual con cualquier
 * visión del color.
 */
export const RAMPA_SCORE = ['#F2EFE2', '#B9CBE4', '#7B9BD0', '#3C63A8', '#002C77'] as const;

/** Color de la cartografía. El crema de la propuesta, algo rebajado. */
export const FONDO_MAPA = '#F7F4E9';

/**
 * Color de estado, reservado para la competencia. Siempre con forma +
 * etiqueta. Rojo oscuro y no claro: sobre fondo crema un rojo pálido no
 * alcanza el contraste mínimo, y las notarías son lo que no puede pasar
 * desapercibido.
 */
export const COLOR_COMPETENCIA = '#B3241F';

/**
 * Tinta de los marcadores de demanda y su halo sobre el mapa. Marino sobre
 * halo crema: el halo separa el marcador del hexágono que tenga debajo, sea
 * cual sea su color.
 */
export const TINTA_MARCADOR = '#002C77';
export const HALO_MARCADOR = '#FFFDF3';

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
