import { COLOR_COMPETENCIA, RAMPA_SCORE, TINTA_MARCADOR } from '@/lib/colores';
import { ETIQUETAS } from '@/lib/heat';

/**
 * La identidad de cada categoría es la forma, no el color, así que la leyenda
 * dibuja las formas de verdad — las mismas que se pintan sobre el mapa.
 */
function Forma({ tipo }: { tipo: 'cuadrado' | 'triangulo' | 'rombo' | 'anillo' | 'cruz' }) {
  const comun = { stroke: 'rgba(10,14,23,0.9)', strokeWidth: 2, strokeLinejoin: 'round' as const };
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" className="shrink-0">
      {tipo === 'cuadrado' && <rect x="3.5" y="3.5" width="9" height="9" fill={TINTA_MARCADOR} {...comun} />}
      {tipo === 'triangulo' && <path d="M8 2.6 13.4 12.4H2.6z" fill={TINTA_MARCADOR} {...comun} />}
      {tipo === 'rombo' && <path d="M8 2.2 13.8 8 8 13.8 2.2 8z" fill={TINTA_MARCADOR} {...comun} />}
      {tipo === 'cruz' && (
        <path
          d="M6.4 2.4h3.2v4h4v3.2h-4v4H6.4v-4h-4V6.4h4z"
          fill={TINTA_MARCADOR}
          {...comun}
        />
      )}
      {tipo === 'anillo' && (
        <circle cx="8" cy="8" r="4.6" fill="none" stroke={COLOR_COMPETENCIA} strokeWidth="2.2" />
      )}
    </svg>
  );
}

export default function Leyenda() {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <span className="etiqueta-campo">Potencial de ubicación</span>
        <div
          className="h-2 w-full rounded-full"
          style={{ backgroundImage: `linear-gradient(to right, ${RAMPA_SCORE.join(',')})` }}
        />
        <div className="flex justify-between text-[11px] text-tinta-tenue">
          <span>Bajo</span>
          <span>Alto</span>
        </div>
      </div>

      <div className="space-y-1.5">
        <span className="etiqueta-campo">Puntos</span>
        <ul className="space-y-1.5 pt-1">
          <li className="flex items-center gap-2.5 text-xs text-tinta-suave">
            <Forma tipo="cuadrado" /> {ETIQUETAS.banco}
          </li>
          <li className="flex items-center gap-2.5 text-xs text-tinta-suave">
            <Forma tipo="triangulo" /> {ETIQUETAS.inmobiliaria}
          </li>
          <li className="flex items-center gap-2.5 text-xs text-tinta-suave">
            <Forma tipo="rombo" /> {ETIQUETAS.abogados}
          </li>
          <li className="flex items-center gap-2.5 text-xs text-tinta-suave">
            <Forma tipo="anillo" /> {ETIQUETAS.notaria}
            <span className="text-tinta-tenue">· competencia</span>
          </li>
          <li className="flex items-center gap-2.5 text-xs text-tinta-suave">
            <Forma tipo="cruz" /> Locales en alquiler
          </li>
        </ul>
      </div>
    </div>
  );
}
