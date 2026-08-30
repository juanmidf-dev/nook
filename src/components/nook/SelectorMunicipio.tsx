import { useEffect, useMemo, useState } from 'react';

import {
  cargaCatalogo,
  tieneCorte,
  ubica,
  type Catalogo,
} from '@/data/municipios';

/**
 * Comunidad -> provincia -> municipio.
 *
 * Tres desplegables encadenados y no un buscador de texto: el notario piensa
 * en «quiero mirar el Vallès», no en el nombre exacto de un municipio, y
 * escribiendo se tropieza con los nombres bilingües —Alicante/Alacant,
 * Araba/Álava— y con los que empiezan por artículo.
 *
 * Los municipios sin corte exportado se ofrecen igualmente, marcados. Enseñar
 * solo los tres que tienen dato daría a entender que no existen los demás.
 */
export default function SelectorMunicipio({
  codIne,
  onCodIne,
}: {
  codIne: string;
  onCodIne: (codIne: string) => void;
}) {
  const [cat, setCat] = useState<Catalogo | null>(null);
  const [ccaa, setCcaa] = useState<string | null>(null);
  const [provincia, setProvincia] = useState<string | null>(null);

  useEffect(() => {
    let vigente = true;
    cargaCatalogo().then((c) => {
      if (!vigente) return;
      setCat(c);
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

  const clase =
    'w-full cursor-pointer rounded-md border border-white/15 bg-white/[0.06] px-2.5 py-1.5 ' +
    'text-[12.5px] text-tinta outline-none transition-colors hover:bg-white/[0.1] ' +
    'focus-visible:ring-2 focus-visible:ring-acento disabled:cursor-not-allowed disabled:opacity-40';

  if (!cat) {
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
        {municipios.map(([cod, nombre]) => (
          /* Los municipios sin corte se listan pero no se pueden elegir. Se
             listan para que se vea que existen; no se eligen porque la
             pantalla de error sustituía al panel entero y dejaba al usuario
             sin forma de volver a seleccionar sin recargar. */
          <option key={cod} value={cod} disabled={!tieneCorte(cod)}>
            {tieneCorte(cod) ? nombre : `${nombre} — sin datos`}
          </option>
        ))}
      </select>

      <p className="text-[11px] leading-snug text-tinta-tenue">
        {municipios.length > 0 && (
          <>
            {municipios.filter(([c]) => tieneCorte(c)).length} de {municipios.length} municipios
            con datos cargados en esta provincia.{' '}
          </>
        )}
        Las capas de demanda solo cubren Cataluña y Madrid.
      </p>
    </div>
  );
}
