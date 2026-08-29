# Registro de oficinas del Banco de España

**Deja aquí el CSV descargado.** Cualquier fichero `*.csv` de esta carpeta se
lee al ejecutar `python cli.py bancos`. Si hay varios se leen todos, así que se
puede descargar por provincias y dejarlos juntos.

## Por qué esto se hace a mano

Las otras fuentes de Nook se ingieren solas. Esta no, por dos razones que no se
arreglan con más código:

1. **El runner de GitHub no alcanza `app.bde.es`.** Comprobado con
   `reconocimiento.yml` el 28/08/2026: sale `inalcanzable` desde Actions y
   `HTTP 200` desde un equipo normal. Es lo habitual en sedes de la
   administración española, que filtran rangos de IP de nube. Así que ninguna
   automatización en Actions puede funcionar, por bien que esté escrita.

2. **No hay endpoint de descarga.** La consulta es pública y no pide
   certificado, pero corre sobre IAS, el framework conversacional del Banco de
   España: el cliente abre una sesión con estado y va enviando operaciones
   contra un despachador. No existe una URL que devuelva el CSV. Emular el
   protocolo sería frágil, se rompería en silencio con cualquier cambio suyo, y
   **seguiría necesitando una máquina con salida**, así que ni siquiera
   compraría la ingesta desatendida.

El registro se mueve despacio —las oficinas cierran en plazos de meses—, así
que refrescarlo cada tres o seis meses es suficiente.

## Cómo descargarlo

1. Abre el registro:
   <https://app.bde.es/exbwciu/GestorDePeticiones?IdOperacion=beexbwciu_Home>
2. Deja los filtros de entidad y provincia vacíos para traerte el censo
   nacional. La fecha de referencia, la de hoy.
3. Marca oficinas **en España** (no las del extranjero: no son demanda notarial
   española).
4. Exporta en **CSV**, no en Excel ni PDF. El parser espera el CSV.
5. Guarda el fichero en esta misma carpeta y haz commit.

## Lo que el parser espera

Sale de mirar un fichero real; nada de esto está documentado por la fuente.

- Codificación **latin-1**, no UTF-8.
- Separador `;` rodeado de espacios, y una columna vacía al final de cada línea
  porque todas terminan en `;`.
- Valores con relleno de espacios a la derecha (`"CATALUÑA           "`).
- El código INE del municipio va partido en dos columnas —provincia y
  municipio— que hay que concatenar con relleno de ceros.
- Las direcciones traen el tipo de vía abreviado en dos letras y a veces el
  número de oficina repetido al final (`"PLACA MAJOR, 32 0032"`).

Si el Banco de España cambia el formato, la ingesta **aborta sin escribir** en
vez de guardar un censo vacío. Eso es deliberado: ver el punto 2 de
`CLAUDE.md`.

## Comprobar que el fichero vale, antes de commitear

```bash
cd pipelines
python cli.py bancos --prueba
```

Debe decir cuántas oficinas ha interpretado. Si dice 0, el parser no encaja con
lo que se ha descargado y hay que mirarlo antes de seguir: cero registros nunca
significa "no hay datos".
