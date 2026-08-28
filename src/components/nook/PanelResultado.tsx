import { useMemo } from 'react';
import { Download, Key, MapPin, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import {
  CATEGORIAS_DEMANDA,
  ETIQUETAS,
  ETIQUETAS_CORTAS,
  localesCercanos,
  puntosCercanos,
  type Celda,
  type Local,
  type Poi,
} from '@/lib/heat';
import { RAMPA_SCORE } from '@/lib/colores';

interface Props {
  seleccion: Celda | null;
  mejores: Celda[];
  pois: Poi[];
  locales: Local[];
  radioM: number;
  onRadio: (m: number) => void;
  onSeleccion: (c: Celda | null) => void;
  nombreZona: string;
}

function colorDeScore(score: number): string {
  const i = Math.min(RAMPA_SCORE.length - 1, Math.floor((score / 100) * RAMPA_SCORE.length));
  return RAMPA_SCORE[Math.max(0, i)];
}

function csv(filas: string[][]): string {
  // Punto y coma como separador y BOM: es lo que Excel en español abre bien
  // de doble clic. Con coma, todo acaba en una sola columna y el notario
  // piensa que el archivo está roto.
  const escapar = (v: string) => (/[";\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  return '﻿' + filas.map((f) => f.map(escapar).join(';')).join('\r\n');
}

export default function PanelResultado({
  seleccion,
  mejores,
  pois,
  locales,
  radioM,
  onRadio,
  onSeleccion,
  nombreZona,
}: Props) {
  const cercanos = useMemo(
    () => (seleccion ? puntosCercanos(seleccion.lat, seleccion.lon, pois, radioM) : []),
    [seleccion, pois, radioM],
  );

  const porCategoria = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of cercanos) m.set(p.categoria, (m.get(p.categoria) ?? 0) + 1);
    return m;
  }, [cercanos]);

  const notariasCerca = useMemo(
    () =>
      seleccion ? puntosCercanos(seleccion.lat, seleccion.lon, pois, radioM, true).filter((p) => p.categoria === 'notaria') : [],
    [seleccion, pois, radioM],
  );

  const localesCerca = useMemo(
    () => (seleccion ? localesCercanos(seleccion.lat, seleccion.lon, locales, radioM) : []),
    [seleccion, locales, radioM],
  );

  function descargar() {
    if (!seleccion) return;
    const filas = [
      ['Categoria', 'Nombre', 'Direccion', 'Telefono', 'Email', 'Web', 'Distancia_m'],
      ...cercanos.map((p) => [
        ETIQUETAS[p.categoria],
        p.nombre,
        p.direccion ?? '',
        p.telefono ?? '',
        p.email ?? '',
        p.web ?? '',
        Math.round(p.distanciaM).toString(),
      ]),
    ];
    const blob = new Blob([csv(filas)], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `nook-puntos-demanda-${nombreZona.toLowerCase().replace(/\W+/g, '-')}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  if (!seleccion) {
    return (
      <aside className="panel-flotante pointer-events-auto flex w-[350px] max-h-[calc(100vh-2rem)] flex-col overflow-hidden">
        <header className="border-b border-white/[0.07] px-5 py-4">
          <h2 className="text-sm font-semibold text-tinta">Mejores ubicaciones</h2>
          <p className="mt-1 text-xs leading-relaxed text-tinta-tenue">
            Pulsa cualquier hexágono del mapa para ver su detalle y los puntos de demanda que tiene
            alrededor.
          </p>
        </header>
        <ol className="lista-scroll flex-1 overflow-y-auto p-3">
          {mejores.map((c, i) => (
            <li key={c.h3}>
              <button
                onClick={() => onSeleccion(c)}
                className="flex w-full items-center gap-3 rounded-lg px-2 py-2.5 text-left transition-colors hover:bg-white/[0.05]"
              >
                <span className="cifra w-5 text-xs text-tinta-tenue">{i + 1}</span>
                <span
                  className="h-8 w-1.5 shrink-0 rounded-full"
                  style={{ backgroundColor: colorDeScore(c.score) }}
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm text-tinta">
                    {c.lat.toFixed(4)}, {c.lon.toFixed(4)}
                  </span>
                  <span className="block text-[11px] text-tinta-tenue">
                    demanda {c.demanda.toFixed(1)} · competencia {c.competencia.toFixed(1)}
                  </span>
                </span>
                <span className="cifra text-lg font-semibold text-tinta">{c.score.toFixed(0)}</span>
              </button>
            </li>
          ))}
        </ol>
      </aside>
    );
  }

  return (
    <aside className="panel-flotante pointer-events-auto flex w-[350px] max-h-[calc(100vh-2rem)] flex-col overflow-hidden">
      <header className="flex items-start justify-between gap-3 border-b border-white/[0.07] px-5 py-4">
        <div>
          <div className="etiqueta-campo">Ubicación seleccionada</div>
          <div className="cifra mt-1 text-sm text-tinta-suave">
            {seleccion.lat.toFixed(5)}, {seleccion.lon.toFixed(5)}
          </div>
        </div>
        <button
          onClick={() => onSeleccion(null)}
          aria-label="Cerrar detalle"
          className="rounded-md p-1 text-tinta-tenue transition-colors hover:bg-white/10 hover:text-tinta"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      <div className="lista-scroll flex-1 overflow-y-auto">
        <div className="flex items-end gap-3 px-5 py-4">
          <div
            className="cifra font-display text-5xl leading-none"
            style={{ color: colorDeScore(seleccion.score) }}
          >
            {seleccion.score.toFixed(0)}
          </div>
          <div className="pb-1 text-xs leading-snug text-tinta-tenue">
            potencial sobre 100
            <br />
            dentro de {nombreZona}
          </div>
        </div>

        <div className="space-y-2.5 px-5 pb-5">
          <div className="etiqueta-campo pb-0.5">En un radio de {radioM} m</div>
          {CATEGORIAS_DEMANDA.map((cat) => {
            const n = porCategoria.get(cat) ?? 0;
            const max = Math.max(1, ...CATEGORIAS_DEMANDA.map((c) => porCategoria.get(c) ?? 0));
            return (
              <div key={cat} className="flex items-center gap-2.5">
                <span className="w-[92px] shrink-0 text-[11.5px] text-tinta-suave">
                  {ETIQUETAS_CORTAS[cat]}
                </span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
                  <span
                    className="block h-full rounded-full bg-[hsl(var(--acento))]"
                    style={{ width: `${(n / max) * 100}%` }}
                  />
                </span>
                <span className="cifra w-7 text-right text-xs text-tinta-suave">{n}</span>
              </div>
            );
          })}
          <div className="mt-3 flex items-center gap-2.5 border-t border-white/[0.07] pt-3">
            <span className="w-[92px] shrink-0 text-[11.5px] text-tinta-suave">
              {ETIQUETAS_CORTAS.notaria}
            </span>
            <span className="flex-1 text-[11px] text-tinta-tenue">competencia directa</span>
            <span className="cifra w-7 text-right text-sm font-semibold text-[hsl(var(--competencia))]">
              {notariasCerca.length}
            </span>
          </div>
        </div>

        <div className="space-y-2 border-t border-white/[0.07] px-5 py-4">
          <div className="flex items-baseline justify-between">
            <span className="etiqueta-campo">Radio de búsqueda</span>
            <span className="cifra text-xs text-tinta-suave">{radioM} m</span>
          </div>
          <Slider
            value={[radioM]}
            min={250}
            max={2000}
            step={50}
            onValueChange={([v]) => onRadio(v)}
          />
        </div>

        <div className="border-t border-white/[0.07] px-5 py-4">
          <div className="etiqueta-campo pb-2">
            Locales en alquiler · <span className="cifra">{localesCerca.length}</span>
          </div>
          {localesCerca.length === 0 ? (
            <p className="text-[11px] text-tinta-tenue">
              Ninguno disponible en este radio.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {localesCerca.slice(0, 6).map((l) => (
                <li key={l.id} className="flex items-start gap-2.5">
                  <Key className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[hsl(var(--acento))]" />
                  <span className="min-w-0 flex-1 truncate text-[12.5px] text-tinta-suave">
                    {l.direccion || l.nombre}
                  </span>
                  <span className="cifra shrink-0 text-[11px] text-tinta-tenue">
                    {Math.round(l.distanciaM)} m
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="border-t border-white/[0.07] px-5 py-3">
          <div className="flex items-center justify-between gap-2">
            <span className="etiqueta-campo">
              Puntos de demanda · <span className="cifra">{cercanos.length}</span>
            </span>
            <Button
              size="sm"
              variant="secondary"
              className="h-7 gap-1.5 px-2.5 text-xs"
              onClick={descargar}
              disabled={cercanos.length === 0}
            >
              <Download className="h-3.5 w-3.5" />
              CSV
            </Button>
          </div>
        </div>

        <ul className="px-3 pb-4">
          {cercanos.slice(0, 200).map((p) => (
            <li key={p.id} className="flex gap-3 rounded-lg px-2 py-2 hover:bg-white/[0.04]">
              <MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0 text-tinta-tenue" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] text-tinta">{p.nombre}</div>
                <div className="truncate text-[11px] text-tinta-tenue">
                  {ETIQUETAS[p.categoria]}
                  {p.direccion ? ` · ${p.direccion}` : ''}
                </div>
              </div>
              <div className="cifra shrink-0 text-[11px] text-tinta-tenue">
                {Math.round(p.distanciaM)} m
              </div>
            </li>
          ))}
          {cercanos.length === 0 && (
            <li className="px-2 py-6 text-center text-xs text-tinta-tenue">
              No hay puntos de demanda en este radio.
            </li>
          )}
        </ul>
      </div>
    </aside>
  );
}
