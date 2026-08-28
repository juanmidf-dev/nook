import { useMemo, useState } from 'react';
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
import { LOCALES, MUNICIPIO, POIS, PROCEDENCIA } from '@/data/sabadell';

const TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN as string | undefined) ?? '';

export default function Index() {
  const [cfg, setCfg] = useState<Config>(CONFIG_POR_DEFECTO);
  const [capas, setCapas] = useState<Record<Categoria, boolean>>({
    notaria: true,
    banco: true,
    inmobiliaria: true,
    abogados: true,
  });
  const [mostrarCalor, setMostrarCalor] = useState(true);
  const [mostrarLocales, setMostrarLocales] = useState(true);
  const [seleccion, setSeleccion] = useState<Celda | null>(null);
  const [radioM, setRadioM] = useState(750);

  // La caja de análisis sale del centro del municipio, no de la extensión de
  // los puntos: así una coordenada mal geocodificada no puede estirar la
  // rejilla ni alterar la normalización del score.
  const celdasIds = useMemo(
    () => celdasDeBBox(bboxDeCentro(MUNICIPIO.centro, 6000), cfg.resolucion),
    [cfg.resolucion],
  );

  const { celdas, ms } = useMemo(() => {
    const t0 = performance.now();
    const r = calcular(celdasIds, POIS, cfg);
    return { celdas: r, ms: performance.now() - t0 };
  }, [celdasIds, cfg]);

  const mejores = useMemo(() => mejoresDiversas(celdas, 8, 700), [celdas]);

  const conteos = useMemo(() => {
    const c = Object.fromEntries(CATEGORIAS.map((k) => [k, 0])) as Record<Categoria, number>;
    for (const p of POIS) c[p.categoria]++;
    return c;
  }, []);

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

  return (
    <div className="relative h-full w-full overflow-hidden bg-lienzo">
      <MapaCalor
        token={TOKEN}
        municipio={MUNICIPIO}
        celdas={celdas}
        pois={POIS}
        locales={LOCALES}
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
          municipio={MUNICIPIO}
          cfg={cfg}
          onCfg={setCfg}
          capas={capas}
          onCapas={setCapas}
          mostrarCalor={mostrarCalor}
          onMostrarCalor={setMostrarCalor}
          mostrarLocales={mostrarLocales}
          onMostrarLocales={setMostrarLocales}
          nLocales={LOCALES.length}
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
          pois={POIS}
          locales={LOCALES}
          radioM={radioM}
          onRadio={setRadioM}
          onSeleccion={setSeleccion}
          nombreZona={MUNICIPIO.nombre}
        />
      </div>
    </div>
  );
}
