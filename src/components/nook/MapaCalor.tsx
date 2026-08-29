import { useEffect, useRef } from 'react';
import mapboxgl from 'mapbox-gl';
import 'mapbox-gl/dist/mapbox-gl.css';

import type { Celda, Categoria, Local, Poi } from '@/lib/heat';
import { contorno, ETIQUETAS } from '@/lib/heat';
import {
  COLOR_COMPETENCIA,
  FONDO_MAPA,
  FORMA_LOCAL,
  FORMA_POR_CATEGORIA,
  HALO_MARCADOR,
  TINTA_MARCADOR,
  paradasScore,
  type Forma,
} from '@/lib/colores';
import type { Municipio } from '@/data/sabadell';

interface Props {
  token: string;
  municipio: Municipio;
  celdas: Celda[];
  pois: Poi[];
  locales: Local[];
  capas: Record<Categoria, boolean>;
  mostrarLocales: boolean;
  mostrarCalor: boolean;
  seleccion: Celda | null;
  onSeleccion: (celda: Celda | null) => void;
}

const SRC_CELDAS = 'nook-celdas';
const SRC_DEMANDA = 'nook-demanda';
const SRC_NOTARIAS = 'nook-notarias';
const SRC_LOCALES = 'nook-locales';

/* ------------------------------------------------------------------ *
 * Iconos
 * ------------------------------------------------------------------ */

/**
 * Los marcadores se dibujan en canvas en vez de cargarse como sprite para no
 * añadir una petición de red por icono y para poder ajustar el halo al fondo
 * exacto del mapa. Formas geométricas simples porque a 13 px de lado son las
 * únicas que se distinguen de un vistazo.
 */
function crearIcono(forma: Forma, px = 30): ImageData | null {
  const canvas = document.createElement('canvas');
  canvas.width = px;
  canvas.height = px;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  const c = px / 2;
  const r = px * 0.3;
  ctx.beginPath();
  if (forma === 'cuadrado') {
    ctx.rect(c - r * 0.88, c - r * 0.88, r * 1.76, r * 1.76);
  } else if (forma === 'triangulo') {
    ctx.moveTo(c, c - r * 1.05);
    ctx.lineTo(c + r, c + r * 0.75);
    ctx.lineTo(c - r, c + r * 0.75);
    ctx.closePath();
  } else if (forma === 'rombo') {
    ctx.moveTo(c, c - r * 1.1);
    ctx.lineTo(c + r * 1.1, c);
    ctx.lineTo(c, c + r * 1.1);
    ctx.lineTo(c - r * 1.1, c);
    ctx.closePath();
  } else if (forma === 'circulo') {
    ctx.arc(c, c, r * 0.92, 0, Math.PI * 2);
  } else if (forma === 'cruz') {
    const g = r * 0.36;
    ctx.moveTo(c - g, c - r);
    ctx.lineTo(c + g, c - r);
    ctx.lineTo(c + g, c - g);
    ctx.lineTo(c + r, c - g);
    ctx.lineTo(c + r, c + g);
    ctx.lineTo(c + g, c + g);
    ctx.lineTo(c + g, c + r);
    ctx.lineTo(c - g, c + r);
    ctx.lineTo(c - g, c + g);
    ctx.lineTo(c - r, c + g);
    ctx.lineTo(c - r, c - g);
    ctx.lineTo(c - g, c - g);
    ctx.closePath();
  } else {
    ctx.arc(c, c, r * 0.9, 0, Math.PI * 2);
  }

  // Halo primero y relleno después: el relleno tapa la mitad interior del
  // trazo y queda un contorno oscuro limpio que separa el marcador del
  // hexágono de debajo, sea cual sea su color.
  ctx.lineJoin = 'round';
  ctx.lineWidth = px * 0.14;
  ctx.strokeStyle = HALO_MARCADOR;
  ctx.stroke();
  ctx.fillStyle = TINTA_MARCADOR;
  ctx.fill();

  return ctx.getImageData(0, 0, px, px);
}

/* ------------------------------------------------------------------ *
 * GeoJSON
 * ------------------------------------------------------------------ */

function geojsonCeldas(celdas: Celda[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: celdas.map((c) => ({
      type: 'Feature',
      id: undefined,
      geometry: { type: 'Polygon', coordinates: [[...contorno(c.h3), contorno(c.h3)[0]]] },
      properties: { h3: c.h3, score: c.score },
    })),
  };
}

function geojsonPois(pois: Poi[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: pois.map((p) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
      properties: {
        nombre: p.nombre,
        categoria: p.categoria,
        etiqueta: ETIQUETAS[p.categoria],
        direccion: p.direccion ?? '',
        telefono: p.telefono ?? '',
        icono: FORMA_POR_CATEGORIA[p.categoria],
      },
    })),
  };
}

function geojsonLocales(locales: Local[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: locales.map((l) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [l.lon, l.lat] },
      properties: {
        nombre: l.nombre,
        etiqueta: l.fuente ? `Local en alquiler · ${l.fuente}` : 'Local en alquiler',
        direccion: l.direccion ?? '',
        icono: FORMA_LOCAL,
      },
    })),
  };
}

/* ------------------------------------------------------------------ *
 * Componente
 * ------------------------------------------------------------------ */

export default function MapaCalor({
  token,
  municipio,
  celdas,
  pois,
  locales,
  capas,
  mostrarLocales,
  mostrarCalor,
  seleccion,
  onSeleccion,
}: Props) {
  const contenedor = useRef<HTMLDivElement>(null);
  const mapa = useRef<mapboxgl.Map | null>(null);
  const listo = useRef(false);
  // El handler de click se recrea en cada render; guardarlo en una ref evita
  // tener que desmontar y volver a montar los listeners del mapa.
  const onSeleccionRef = useRef(onSeleccion);
  onSeleccionRef.current = onSeleccion;
  const celdasRef = useRef(celdas);
  celdasRef.current = celdas;

  useEffect(() => {
    if (!contenedor.current || !token || mapa.current) return;

    mapboxgl.accessToken = token;
    const m = new mapboxgl.Map({
      container: contenedor.current,
      style: 'mapbox://styles/mapbox/light-v11',
      center: municipio.centro,
      zoom: municipio.zoom,
      attributionControl: true,
    });
    mapa.current = m;
    m.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'bottom-right');
    m.addControl(new mapboxgl.ScaleControl({ unit: 'metric' }), 'bottom-right');

    m.on('load', () => {
      // El estilo claro de Mapbox trae fondo gris; se tiñe al crema de la
      // propuesta.
      //
      // Se buscan las capas por TIPO y no por nombre. La primera versión de
      // esto pedía la capa 'background' y, como en el estilo claro se llama
      // 'land', lanzaba en la primera línea y el catch se comía también la
      // segunda: el mapa se quedaba gris sin que nada lo dijera.
      try {
        for (const capa of m.getStyle().layers ?? []) {
          if (capa.type === 'background') {
            m.setPaintProperty(capa.id, 'background-color', FONDO_MAPA);
          }
        }
      } catch {
        /* el estilo no expone capas de fondo: se queda con el suyo */
      }

      for (const forma of ['cuadrado', 'triangulo', 'rombo', 'cruz', 'circulo'] as Forma[]) {
        const img = crearIcono(forma);
        if (img && !m.hasImage(forma)) {
          m.addImage(forma, { width: img.width, height: img.height, data: img.data }, { pixelRatio: 2 });
        }
      }

      m.addSource(SRC_CELDAS, { type: 'geojson', data: geojsonCeldas([]) });
      m.addSource(SRC_DEMANDA, { type: 'geojson', data: geojsonPois([]) });
      m.addSource(SRC_NOTARIAS, { type: 'geojson', data: geojsonPois([]) });
      m.addSource(SRC_LOCALES, { type: 'geojson', data: geojsonLocales([]) });

      const paradas = paradasScore().flat();

      m.addLayer({
        id: 'celdas-relleno',
        type: 'fill',
        source: SRC_CELDAS,
        paint: {
          'fill-color': ['interpolate', ['linear'], ['get', 'score'], ...paradas] as never,
          // Las celdas de score bajo se desvanecen en vez de pintarse de azul
          // oscuro: si todas se pintan, el municipio queda cubierto por una
          // sábana uniforme y no se distingue el relieve del dato.
          'fill-opacity': [
            'interpolate',
            ['linear'],
            ['get', 'score'],
            0, 0.05,
            35, 0.3,
            100, 0.72,
          ] as never,
        },
      });

      m.addLayer({
        id: 'celdas-seleccion',
        type: 'line',
        source: SRC_CELDAS,
        filter: ['==', ['get', 'h3'], ''],
        // Marino y no blanco: sobre cartografía clara un contorno blanco
        // desaparece justo en las celdas de score bajo, que son las más
        // claras y las que más cuesta señalar.
        paint: { 'line-color': '#002C77', 'line-width': 2.5 },
      });

      m.addLayer({
        id: 'notarias',
        type: 'circle',
        source: SRC_NOTARIAS,
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, 4, 17, 8] as never,
          'circle-color': 'rgba(0,0,0,0)',
          'circle-stroke-width': 2.5,
          'circle-stroke-color': COLOR_COMPETENCIA,
        },
      });

      m.addLayer({
        id: 'demanda',
        type: 'symbol',
        source: SRC_DEMANDA,
        layout: {
          'icon-image': ['get', 'icono'] as never,
          'icon-size': ['interpolate', ['linear'], ['zoom'], 11, 0.4, 17, 0.62] as never,
          'icon-allow-overlap': true,
        },
      });

      m.addLayer({
        id: 'locales',
        type: 'symbol',
        source: SRC_LOCALES,
        layout: {
          'icon-image': FORMA_LOCAL,
          'icon-size': ['interpolate', ['linear'], ['zoom'], 11, 0.45, 17, 0.72] as never,
          'icon-allow-overlap': true,
        },
      });

      const popup = new mapboxgl.Popup({ closeButton: false, offset: 12 });
      for (const capa of ['demanda', 'notarias', 'locales']) {
        m.on('mouseenter', capa, (e) => {
          m.getCanvas().style.cursor = 'pointer';
          const f = e.features?.[0];
          if (!f) return;
          const p = f.properties as Record<string, string>;
          popup
            .setLngLat((f.geometry as GeoJSON.Point).coordinates as [number, number])
            .setHTML(
              `<div class="space-y-0.5">
                 <div class="text-[11px] uppercase tracking-wider text-white/45">${p.etiqueta}</div>
                 <div class="text-sm font-medium">${p.nombre}</div>
                 ${p.direccion ? `<div class="text-xs text-white/60">${p.direccion}</div>` : ''}
               </div>`,
            )
            .addTo(m);
        });
        m.on('mouseleave', capa, () => {
          m.getCanvas().style.cursor = '';
          popup.remove();
        });
      }

      m.on('click', 'celdas-relleno', (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const h3 = (f.properties as { h3: string }).h3;
        const celda = celdasRef.current.find((c) => c.h3 === h3) ?? null;
        onSeleccionRef.current(celda);
      });

      listo.current = true;
      // Los datos pueden haber llegado antes de que el estilo terminara de
      // cargar; se vuelcan aquí para no perder el primer render.
      volcar(m);
    });

    return () => {
      m.remove();
      mapa.current = null;
      listo.current = false;
    };
    // Solo se reinicializa si cambia el token: el municipio se mueve con flyTo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  function volcar(m: mapboxgl.Map) {
    const sc = m.getSource(SRC_CELDAS) as mapboxgl.GeoJSONSource | undefined;
    sc?.setData(geojsonCeldas(mostrarCalor ? celdasRef.current : []));

    const visibles = pois.filter((p) => capas[p.categoria]);
    (m.getSource(SRC_DEMANDA) as mapboxgl.GeoJSONSource | undefined)?.setData(
      geojsonPois(visibles.filter((p) => p.categoria !== 'notaria')),
    );
    (m.getSource(SRC_NOTARIAS) as mapboxgl.GeoJSONSource | undefined)?.setData(
      geojsonPois(visibles.filter((p) => p.categoria === 'notaria')),
    );
    (m.getSource(SRC_LOCALES) as mapboxgl.GeoJSONSource | undefined)?.setData(
      geojsonLocales(mostrarLocales ? locales : []),
    );
  }

  useEffect(() => {
    const m = mapa.current;
    if (m && listo.current) volcar(m);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [celdas, pois, locales, capas, mostrarCalor, mostrarLocales]);

  useEffect(() => {
    const m = mapa.current;
    if (!m || !listo.current) return;
    m.setFilter('celdas-seleccion', ['==', ['get', 'h3'], seleccion?.h3 ?? '']);
  }, [seleccion]);

  useEffect(() => {
    const m = mapa.current;
    if (!m) return;
    m.flyTo({ center: municipio.centro, zoom: municipio.zoom, duration: 900 });
  }, [municipio]);

  return <div ref={contenedor} className="absolute inset-0" />;
}
