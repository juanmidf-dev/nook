import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
 import { CATEGORIAS, CATEGORIAS_DEMANDA, ETIQUETAS, type Categoria, type Config } from '@/lib/heat';
import { INCIDENCIAS, type Municipio } from '@/data/sabadell';
import Marca from '@/components/nook/Marca';
import Leyenda from '@/components/nook/Leyenda';

interface Props {
  municipio: Municipio;
  cfg: Config;
  onCfg: (c: Config) => void;
  capas: Record<Categoria, boolean>;
  onCapas: (c: Record<Categoria, boolean>) => void;
  mostrarCalor: boolean;
  onMostrarCalor: (v: boolean) => void;
  mostrarLocales: boolean;
  onMostrarLocales: (v: boolean) => void;
  nLocales: number;
  conteos: Record<Categoria, number>;
  msCalculo: number | null;
}

function Campo({
  etiqueta,
  valor,
  children,
  ayuda,
}: {
  etiqueta: string;
  valor: string;
  children: React.ReactNode;
  ayuda?: string;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="etiqueta-campo">{etiqueta}</span>
        <span className="cifra text-xs font-medium text-tinta-suave">{valor}</span>
      </div>
      {children}
      {ayuda && <p className="text-[11px] leading-snug text-tinta-tenue">{ayuda}</p>}
    </div>
  );
}

export default function PanelControl({
  municipio,
  cfg,
  onCfg,
  capas,
  onCapas,
  mostrarCalor,
  onMostrarCalor,
  mostrarLocales,
  onMostrarLocales,
  nLocales,
  conteos,
  msCalculo,
}: Props) {
  return (
    <aside className="panel-flotante pointer-events-auto flex w-[330px] max-h-[calc(100vh-2rem)] flex-col overflow-hidden">
      <header className="border-b border-white/[0.07] px-5 py-4">
        <Marca />
      </header>

      <div className="lista-scroll flex-1 space-y-6 overflow-y-auto px-5 py-5">
        <div className="space-y-2">
          <span className="etiqueta-campo">Zona de análisis</span>
          <div className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2.5">
            <div className="text-sm text-tinta">{municipio.nombre}</div>
            <div className="text-[11px] text-tinta-tenue">
              {municipio.provincia} · INE {municipio.codIne}
            </div>
          </div>
          <p className="text-[11px] leading-snug text-tinta-tenue">
            El resto de municipios se activan cuando el pipeline de ingesta cargue los
            datos nacionales.
          </p>
        </div>

        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <span className="etiqueta-campo">Ponderación de la demanda</span>
          </div>
          {CATEGORIAS_DEMANDA.map((cat) => (
            <Campo key={cat} etiqueta={ETIQUETAS[cat]} valor={`×${cfg.pesos[cat].toFixed(1)}`}>
              <Slider
                value={[cfg.pesos[cat]]}
                min={0}
                max={3}
                step={0.1}
                onValueChange={([v]) => onCfg({ ...cfg, pesos: { ...cfg.pesos, [cat]: v } })}
              />
            </Campo>
          ))}
        </section>

        <section className="space-y-4 border-t border-white/[0.07] pt-5">
          <Campo
            etiqueta="Penalización por competencia"
            valor={cfg.pesoCompetencia.toFixed(2)}
            ayuda="0 ignora las notarías existentes. 1 anula por completo la demanda de una zona ya saturada."
          >
            <Slider
              value={[cfg.pesoCompetencia]}
              min={0}
              max={1}
              step={0.05}
              onValueChange={([v]) => onCfg({ ...cfg, pesoCompetencia: v })}
            />
          </Campo>

          <Campo
            etiqueta="Radio de influencia"
            valor={`${cfg.bandwidthM} m`}
            ayuda="Distancia a la que un punto deja de aportar demanda. A pie, 600 m es un trayecto de unos ocho minutos."
          >
            <Slider
              value={[cfg.bandwidthM]}
              min={200}
              max={1500}
              step={50}
              onValueChange={([v]) => onCfg({ ...cfg, bandwidthM: v })}
            />
          </Campo>

          <Campo
            etiqueta="Detalle de la rejilla"
            valor={cfg.resolucion === 8 ? 'Amplio' : cfg.resolucion === 9 ? 'Medio' : 'Fino'}
            ayuda="Tamaño de cada hexágono: 460 m, 175 m o 65 m de lado."
          >
            <Slider
              value={[cfg.resolucion]}
              min={8}
              max={10}
              step={1}
              onValueChange={([v]) => onCfg({ ...cfg, resolucion: v })}
            />
          </Campo>
        </section>

        <section className="space-y-3 border-t border-white/[0.07] pt-5">
          <span className="etiqueta-campo">Capas</span>

          <label className="flex cursor-pointer items-center justify-between gap-3 py-1">
            <span className="text-sm text-tinta-suave">Mapa de calor</span>
            <Switch checked={mostrarCalor} onCheckedChange={onMostrarCalor} />
          </label>

          <label className="flex cursor-pointer items-center justify-between gap-3 py-1">
            <span className="flex items-baseline gap-2 text-sm text-tinta-suave">
              Locales en alquiler
              <span className="cifra text-[11px] text-tinta-tenue">{nLocales}</span>
            </span>
            <Switch checked={mostrarLocales} onCheckedChange={onMostrarLocales} />
          </label>

          {CATEGORIAS.map((cat) => {
            const n = conteos[cat] ?? 0;
            // Los despachos de abogados aún no tienen volcado. Se muestra
            // "sin datos" en vez de un 0, que se leería como "no hay ninguno
            // en Sabadell" — que es falso y llevaría a conclusiones erróneas.
            return (
              <label
                key={cat}
                className={`flex items-center justify-between gap-3 py-1 ${
                  n === 0 ? 'cursor-default opacity-45' : 'cursor-pointer'
                }`}
              >
                <span className="flex items-baseline gap-2 text-sm text-tinta-suave">
                  {ETIQUETAS[cat]}
                  <span className="cifra text-[11px] text-tinta-tenue">
                    {n === 0 ? 'sin datos' : n}
                  </span>
                </span>
                <Switch
                  checked={capas[cat] && n > 0}
                  disabled={n === 0}
                  onCheckedChange={(v) => onCapas({ ...capas, [cat]: v })}
                />
              </label>
            );
          })}
        </section>

        {INCIDENCIAS.length > 0 && (
          <div className="rounded-lg border border-[hsl(var(--competencia))]/25 bg-[hsl(var(--competencia))]/[0.07] px-3 py-2.5">
            <div className="text-[11.5px] font-medium text-tinta-suave">
              {INCIDENCIAS.length === 1
                ? '1 registro descartado del volcado'
                : `${INCIDENCIAS.length} registros descartados del volcado`}
            </div>
            <details className="group">
              <summary className="cursor-pointer list-none pt-0.5 text-[11px] text-tinta-tenue underline decoration-dotted underline-offset-2">
                ver detalle
              </summary>
              <ul className="lista-scroll mt-1.5 max-h-40 space-y-1 overflow-y-auto pr-1">
                {INCIDENCIAS.map((inc, i) => (
                  <li key={i} className="text-[11px] leading-snug text-tinta-tenue">
                    <span className="text-tinta-suave">{inc.nombre}</span> — {inc.motivo}
                  </li>
                ))}
              </ul>
            </details>
          </div>
        )}

        <div className="border-t border-white/[0.07] pt-5">
          <Leyenda />
        </div>
      </div>

      {msCalculo !== null && (
        <footer className="border-t border-white/[0.07] px-5 py-2.5 text-[11px] text-tinta-tenue">
          Recalculado en <span className="cifra">{msCalculo.toFixed(0)} ms</span>
        </footer>
      )}
    </aside>
  );
}
