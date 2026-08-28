# Pipeline de ingesta

Extrae notarías, oficinas bancarias, inmobiliarias y despachos de abogados, los
geocodifica y los escribe en Supabase.

## Por qué esto corre en GitHub Actions y no en tu portátil

Ni el entorno de desarrollo ni el equipo local tienen salida hacia
`notariado.org`, `app.bde.es`, Overpass o el INE. Está comprobado en ambos. Los
runners de GitHub sí, así que Actions no es una preferencia de arquitectura: es
la única vía. De paso sale gratis, deja histórico versionado de cada ejecución,
tiene cron y **no requiere que nadie más tenga acceso al repositorio** — los
workflows se ejecutan con su propio token.

## Estado de cada fuente

| Fuente | Estado | Notas |
|---|---|---|
| **Banco de España** | Listo y probado | Trabaja sobre el CSV del Registro de Oficinas. Parser validado contra un fichero real de Sabadell: 48 oficinas, 0 errores. |
| **Overture Maps** | Listo, sin probar contra S3 | La consulta y la transformación están probadas contra un parquet local con el mismo esquema. Falta la primera ejecución real. |
| **Guía Notarial** | Pendiente del endpoint | Ver abajo. |
| **Idealista** | Sin empezar | Falta la solicitud de acceso a la API. |

## Lo primero que hay que ejecutar

```
Actions -> Reconocimiento de fuentes -> Run workflow
```

La Guía Notarial es una aplicación React: la lista de notarías no está en el
HTML, se la pide su JavaScript a un endpoint no documentado. El reconocimiento
baja los bundles, busca en ellos las rutas de API, las prueba y deja todo como
artefacto descargable.

Con ese artefacto se rellena `ENDPOINT` en `nook/fuentes/notarias.py` —o se
pone el valor en el secreto `NOOK_ENDPOINT_NOTARIAS`, que tiene prioridad y
permite probar candidatos sin abrir un pull request por cada intento.

**No se ha dejado un endpoint inventado que parezca plausible.** Un extractor
que falla en silencio y devuelve cero notarías es peor que uno que no existe:
el mapa se queda sin capa de competencia y empieza a recomendar el portal de al
lado de una notaría que ya está abierta.

## Ejecutar la ingesta

```
Actions -> Ingesta de datos -> Run workflow
   fuente: bancos | overture | notarias
   modo:   prueba | real
```

`prueba` deja el resultado como artefacto NDJSON y **no toca Supabase**. Es el
valor por defecto, y el botón nunca escribe en la base de datos por descuido:
solo lo hacen las ejecuciones programadas o un `real` explícito. Estos
extractores no se pueden ensayar en local, así que la primera vez que uno ve
datos reales es dentro de un runner; conviene mirar el artefacto antes de dejar
que escriba.

La ejecución programada es el día 3 de cada mes. Estos censos se mueven
despacio: una notaría no abre cada semana.

## Secretos del repositorio

| Secreto | Para qué |
|---|---|
| `SUPABASE_URL` | URL del proyecto, `https://xxxx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Service key. **Nunca la clave anónima**: el upsert necesita saltarse las políticas de fila. |
| `NOOK_ENDPOINT_NOTARIAS` | Opcional, para probar un endpoint sin tocar el código |

## Decisiones que conviene conocer antes de tocar nada

**Identificadores deterministas.** Ninguna de estas fuentes publica una clave
propia: el Banco de España da un listado sin identificador de oficina y la Guía
Notarial pagina. `id_estable()` construye un hash a partir de los campos que no
cambian. Sin él, la ejecución mensual insertaría el parque bancario entero otra
vez en vez de actualizarlo.

**Se aborta si salen cero registros.** Un extractor que devuelve nada casi
nunca significa "no hay datos": significa que la fuente cambió y el parser ya
no encaja. Un upsert vacío no rompe nada visiblemente, pero deja el mapa sin
esa capa hasta que alguien se da cuenta semanas después.

**La calidad de la geocodificación se guarda siempre.** Una notaría situada
solo a nivel de municipio no sirve para medir competencia a 600 metros. Se
almacena `geocode_calidad` para poder filtrar sin volver a geocodificar España
entera.

**Overture con versión fija, no `latest`.** Una ingesta mensual que cambia de
versión de dataset sin avisar mueve puntos de sitio, y luego no hay forma de
explicarle a un cliente por qué su mapa cambió de un mes a otro.

**Ritmo limitado y agente identificado.** Todas las fuentes son portales de
organismos públicos y colegios profesionales, no APIs comerciales. Un extractor
que tarda veinte minutos y no molesta a nadie es preferible a uno que tarda dos
y acaba con la IP de los runners bloqueada.

## Desarrollo

```bash
cd pipelines
pip install -r requirements.txt
python -m pytest tests -q
```

Los tests no tocan la red. El único que se salta en entornos sin salida a
internet es el que necesita la extensión espacial de DuckDB; en Actions se
ejecuta. Las comprobaciones de estructuras anidadas y filtros de Overture
tienen una versión sin geometría que corre en cualquier sitio.

Un aviso sobre los tests del Banco de España: los casos de direcciones no son
inventados, salen de un fichero real. El más importante es
`test_conserva_el_numero_de_portal`. La primera versión del limpiador borraba
el número final rellenado con ceros creyendo que era un código de oficina
repetido —lo es en `PLACA MAJOR, 32 0032`— y con eso dejaba `CR DE TERRASSA
0335` convertido en "Carretera de Terrassa", sin portal. Media provincia
geocodificada al centro de la calle.
