import { useEffect, useMemo, useState } from 'react';

import {
  cargaCatalogo,
  cargaIndice,
  ubica,
  type Catalogo,
  type Indice,
} from '@/data/municipios';

/**
 * Comunidad -> provincia -> municipio.
 *
 * Tres desplegables encadenados y no un buscador de texto: el notario piensa
 * en «quiero mirar el Vallès», no en el nombre exacto de un municipio, y
 * escribiendo se tropieza con los nombres bilingües —Alicante/Alacant,
 * Araba/Álava— y con los que empiezan por artículo.
 *
 * Los municipios sin datos se ofrecen igualmente, marcados y sin poder
 * elegirse. Enseñar solo los que tienen dato daría a entender que los demás no
 * existen, y la cobertura real es la información que hay que dar, no esconder.
 */
export default function SelectorMunicipio({
  codIne,
  onCodIne,
}: {
  codIne: string;
  onCodIne: (codIne: string) => void;
}) {
  const [cat, setCat] = useState<Catalogo | null>(null);
  const [idx, setIdx] = useState<Indice | null>(null);
  const [ccaa, setCcaa] = useState<string | null>(null);
  const [provincia, setProvincia] = useState<string | null>(null);

  useEffect(() => {
    let vigente = true;
    Promise.all([cargaCatalogo(), cargaIndice()]).then(([c, i]) => {
      if (!vigente) return;
      setCat(c);
      setIdx(i);
      // Los desplegables arrancan situados sobre el municipio activo, no en
      // blanco: si no, al abrirlos parece que no hay nada seleccionado.
      const donde = ubica(c, codIne);
      if (donde) {
        setCcaa(donde.ccaa);
        setProvincia(donde.provincia);
      }
    });
    return () => {
      vigente = false;
    };
    // Solo al montar: después manda lo que elija el usuario.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const provincias = useMemo(
    () => cat?.ccaa.find((c) => c.cod === ccaa)?.provincias ?? [],
    [cat, ccaa],
  );
  const municipios = useMemo(
    () => provincias.find((p) => p.cod === provincia)?.municipios ?? [],
    [provincias, provincia],
  );

  /**
   * Qué se le puede decir al usuario de cada municipio antes de que lo elija.
   *
   * Distinguir «sin datos» de «solo competencia» importa: un municipio con
   * notarías y sin capa de demanda **abre igual**, pero el mapa sale plano, y
   * sin avisar parecería que allí no hay ninguna oportunidad. Que sea un hueco
   * nuestro de cobertura y no un hallazgo del modelo tiene que verse antes de
   * mirar el mapa, no después.
   */
  const etiqueta = useMemo(() => {
    return (cod: string, nombre: string): { texto: string; elegible: boolean } => {
      const f = idx?.municipios[cod];
      if (!f) return { texto: `${nombre} — sin datos`, elegible: false };
      if (!f.demanda) return { texto: `${nombre} — sin capa de demanda`, elegible: true };
      if (!f.competencia) return { texto: `${nombre} — sin notarías`, elegible: true };
      return { texto: nombre, elegible: true };
    };
  }, [idx]);

  const cobertura = useMemo(() => {
    if (!idx) return null;
    let conDatos = 0;
    let completos = 0;
    for (const [cod] of municipios) {
      const f = idx.municipios[cod];
      if (!f) continue;
      conDatos++;
      if (f.demanda && f.competencia) completos++;
    }
    return { conDatos, completos, total: municipios.length };
  }, [idx, municipios]);

  const clase =
    'w-full cursor-pointer rounded-md border border-white/15 bg-white/[0.06] px-2.5 py-1.5 ' +
    'text-[12.5px] text-tinta outline-none transition-colors hover:bg-white/[0.1] ' +
    'focus-visible:ring-2 focus-visible:ring-acento disabled:cursor-not-allowed disabled:opacity-40';

  if (!cat || !idx) {
    return <div className="text-[11px] text-tinta-tenue">Cargando municipios…</div>;
  }

  return (
    <div className="space-y-1.5">
      <select
        aria-label="Comunidad autónoma"
        className={clase}
        value={ccaa ?? ''}
        onChange={(e) => {
          setCcaa(e.target.value || null);
          setProvincia(null);
        }}
      >
        <option value="">Comunidad autónoma…</option>
        {cat.ccaa.map((c) => (
          <option key={c.cod} value={c.cod} className="bg-panel-alto text-tinta">
            {c.nombre}
          </option>
        ))}
      </select>

      <select
        aria-label="Provincia"
        className={clase}
        value={provincia ?? ''}
        disabled={!ccaa}
        onChange={(e) => setProvincia(e.target.value || null)}
      >
        <option value="">Provincia…</option>
        {provincias.map((p) => (
          <option key={p.cod} value={p.cod} className="bg-panel-alto text-tinta">
            {p.nombre}
            {idx.provincias[p.cod] ? ` · ${idx.provincias[p.cod].puntos} puntos` : ' · sin datos'}
          </option>
        ))}
      </select>

      <select
        aria-label="Municipio"
        /* La tarjeta clara marca cuál de los tres es el que manda, igual que
           los bloques destacados de la propuesta comercial. */
        className="tarjeta-crema w-full cursor-pointer font-display text-sm font-semibold uppercase tracking-[0.03em] outline-none transition-opacity hover:opacity-90 focus-visible:ring-2 focus-visible:ring-acento disabled:cursor-not-allowed disabled:opacity-50"
        value={codIne}
        disabled={!provincia}
        onChange={(e) => onCodIne(e.target.value)}
      >
        {!municipios.some(([cod]) => cod === codIne) && (
          <option value={codIne}>Municipio…</option>
        )}
        {municipios.map(([cod, nombre]) => {
          const { texto, elegible } = etiqueta(cod, nombre);
          return (
            <option key={cod} value={cod} disabled={!elegible}>
              {texto}
            </option>
          );
        })}
      </select>

      {cobertura && cobertura.total > 0 && (
        <p className="text-[11px] leading-snug text-tinta-tenue">
          {cobertura.conDatos} de {cobertura.total} municipios con datos en esta provincia,{' '}
          {cobertura.completos} con las dos capas.
          {cobertura.completos < cobertura.conDatos && (
            <> En el resto falta la capa de demanda, que aún no cubre toda España.</>
          )}
        </p>
      )}
    </div>
  );
}
