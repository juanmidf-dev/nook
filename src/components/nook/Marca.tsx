/**
 * La marca, en la línea de la portada de la propuesta comercial: NOOK en
 * condensada, negrita y mayúsculas, con el descriptivo debajo en cursiva.
 */
export default function Marca({ compacta = false }: { compacta?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
        {/* Un hexágono, que es la unidad de la rejilla, con un alfiler dentro. */}
        <path
          d="M13 1.6 23 7.3v11.4L13 24.4 3 18.7V7.3z"
          fill="none"
          stroke="hsl(var(--acento))"
          strokeWidth="1.4"
        />
        <circle cx="13" cy="11" r="3" fill="hsl(var(--acento))" />
        <path d="M13 14.2V19" stroke="hsl(var(--acento))" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
      <div className="leading-none">
        <div className="font-display text-[23px] font-bold uppercase tracking-[0.02em] text-tinta">
          Nook
        </div>
        {!compacta && (
          <div className="mt-1 font-sans text-[10.5px] italic text-tinta-suave">
            Descubre dónde abrir tu próxima notaría
          </div>
        )}
      </div>
    </div>
  );
}
