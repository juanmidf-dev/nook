import { useEffect, useMemo, useState } from 'react';
import { Database } from 'lucide-react';

import MapaCalor from '@/components/nook/MapaCalor';
import PanelControl from '@/components/nook/PanelControl';
import PanelResultado from '@/components/nook/PanelResultado';
import Marca from '@/components/nook/Marca';
import {
  CATEGORIAS,
  CONFIG_POR_DEFECTO,
  bboxDeCentro,
  calcular,
  celdasDeBBox,
  mejoresDiversas,
  type Categoria,
  type Celda,
  type Config,
} from '@/lib/heat';
import { PROCEDENCIA } from '@/data/sabadell';
import { MUNICIPIO_POR_DEFECTO, cargaCorte, type Corte } from '@/data/municipios';

const TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN as string | undefined) ?? '';

export default function Index() {
  const [codIne, setCodIne] = useState(MUNICIPIO_POR_DEFECTO);
  const [corte, setCorte] = useState<Corte | null>(null);
  const [errorCarga, setErrorCarga] = useState<string | null>(null);
  const [cfg, setCfg] = useState<Config>(CONFIG_POR_DEFECTO);
  const [capas, setCapas] = useState<Record<Categoria, boolean>>({
    notaria: true,
    banco: true,
    inmobiliaria: true,
    abogados: true,
    gestoria: true,
  });
  const [mostrarCalor, setMostrarCalor] = useState(true);
  const [mostrarLocales, setMostrarLocales] = useState(true);
  const [seleccion, setSeleccion] = useState<Celda | null>(null);
  const [radioM, setRadioM] = useState(750);

  useEffect(() => {
    let vigente = true;
    setErrorCarga(null);
    cargaCorte(codIne)
      .then((c) => {
        // Si el usuario ha cambiado de municipio mientras se cargaba este,
        // pintar ahora el anterior dejaría el mapa contradiciendo al selector.
        if (!vigente) return;
        setCorte(c);
        setSeleccion(null);
      })
      .catch((e: unknown) => vigente && setErrorCarga(String(e)));
    return () => {
      vigente = false;
    };
  }, [codIne]);

  const pois = corte?.pois ?? [];
  const locales = corte?.locales ?? [];
  const municipio = corte?.municipio ?? null;

  // La caja de análisis sale del centro del municipio, no de la extensión de
  // los puntos: así una coordenada mal geocodificada no puede estirar la
  // rejilla ni alterar la normalización del score.
  const celdasIds = useMemo(
    () => (municipio ? celdasDeBBox(bboxDeCentro(municipio.centro, 6000), cfg.resolucion) : []),
    [municipio, cfg.resolucion],
  );

  const { celdas, ms } = useMemo(() => {
    const t0 = performance.now();
    const r = calcular(celdasIds, pois, cfg);
    return { celdas: r, ms: performance.now() - t0 };
  }, [celdasIds, pois, cfg]);

  const mejores = useMemo(() => mejoresDiversas(celdas, 8, 700), [celdas]);

  const conteos = useMemo(() => {
    const c = Object.fromEntries(CATEGORIAS.map((k) => [k, 0])) as Record<Categoria, number>;
    for (const p of pois) c[p.categoria]++;
    return c;
  }, [pois]);

  if (!TOKEN) {
    return (
      <div className="flex h-full items-center justify-center bg-lienzo p-6">
        <div className="panel-flotante max-w-md space-y-4 p-7">
          <Marca />
          <h1 className="text-lg font-semibold text-tinta">Falta el token de Mapbox</h1>
          <p className="text-sm leading-relaxed text-tinta-suave">
            Crea un archivo <code className="rounded bg-white/10 px-1">.env</code> en la raíz del
            proyecto con la variable{' '}
            <code className="rounded bg-white/10 px-1">VITE_MAPBOX_TOKEN</code> y reinicia el
            servidor de desarrollo. El archivo{' '}
            <code className="rounded bg-white/10 px-1">.env.example</code> tiene la plantilla.
          </p>
        </div>
      </div>
    );
  }

  if (errorCarga) {
    return (
      <div className="flex h-full items-center justify-center bg-lienzo p-6">
        <div className="panel-flotante max-w-md space-y-4 p-7">
          <Marca />
          <h1 className="text-lg font-semibold text-tinta">No se pudo cargar el municipio</h1>
          <p className="text-sm leading-relaxed text-tinta-suave">
            El municipio <code className="rounded bg-white/10 px-1">{codIne}</code> todavía no
            tiene datos exportados. Se generan con el workflow «Exportar corte para el mapa»,
            y solo hay ingesta de Cataluña y Madrid.
          </p>
          {/* Sin esto, quien llegue aquí se queda sin panel y sin forma de
              elegir otro municipio salvo recargando la página. */}
          <button
            type="button"
            onClick={() => setCodIne(MUNICIPIO_POR_DEFECTO)}
            className="rounded-md bg-[hsl(var(--acento))] px-3 py-1.5 font-display text-[12px] font-semibold uppercase tracking-[0.05em] text-[hsl(var(--acento-tinta))] transition-opacity hover:opacity-90"
          >
            Volver a Sabadell
          </button>
        </div>
      </div>
    );
  }

  if (!municipio) {
    return (
      <div className="flex h-full items-center justify-center bg-lienzo">
        <span className="text-sm text-tinta-tenue">Cargando datos del municipio…</span>
      </div>
    );
  }

  return (
    <div className="relative h-full w-full overflow-hidden bg-lienzo">
      <MapaCalor
        token={TOKEN}
        municipio={municipio}
        celdas={celdas}
        pois={pois}
        locales={locales}
        capas={capas}
        mostrarCalor={mostrarCalor}
        mostrarLocales={mostrarLocales}
        seleccion={seleccion}
        onSeleccion={setSeleccion}
      />

      {/* Capa de cromo: no captura el ratón salvo en los propios paneles, para
          que arrastrar el mapa siga funcionando entre ellos. */}
      <div className="pointer-events-none absolute inset-0 flex items-start justify-between gap-4 p-4">
        <PanelControl
          municipio={municipio}
          codIne={codIne}
          onCodIne={setCodIne}
          incidencias={corte?.incidencias ?? []}
          cfg={cfg}
          onCfg={setCfg}
          capas={capas}
          onCapas={setCapas}
          mostrarCalor={mostrarCalor}
          onMostrarCalor={setMostrarCalor}
          mostrarLocales={mostrarLocales}
          onMostrarLocales={setMostrarLocales}
          nLocales={locales.length}
          conteos={conteos}
          msCalculo={ms}
        />

        <div className="pointer-events-auto mt-1 flex items-center gap-2 rounded-full border border-white/10 bg-black/40 px-3.5 py-1.5 backdrop-blur-md">
          <Database className="h-3.5 w-3.5 text-tinta-tenue" />
          <span className="text-[11.5px] text-tinta-suave">{PROCEDENCIA}</span>
        </div>

        <PanelResultado
          seleccion={seleccion}
          mejores={mejores}
          pois={pois}
          locales={locales}
          radioM={radioM}
          onRadio={setRadioM}
          onSeleccion={setSeleccion}
          nombreZona={municipio.nombre}
        />
      </div>
    </div>
  );
}
