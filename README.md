# Nook

Herramienta visual para que un notario decida dónde abrir su próxima notaría:
un mapa de calor de **demanda insatisfecha** que cruza la demanda de la zona
(oficinas bancarias, inmobiliarias, despachos de abogados) con la competencia
ya instalada (notarías existentes), más el listado de puntos de demanda
alrededor de cualquier ubicación.

## Arranque

```bash
npm install
cp .env.example .env      # y pega dentro tu token público de Mapbox
npm run dev
```

El token de Mapbox se lee de `VITE_MAPBOX_TOKEN`. **Restríngelo por dominio**
desde `account.mapbox.com/access-tokens` antes de publicar: un token público
sin restricción de URL lo puede usar cualquiera que abra el inspector, y la
factura la pagas tú.

## Cómo funciona el mapa de calor

Rejilla hexagonal H3. Para cada celda y cada punto a distancia `d`:

```
aportación = peso × exp( −d² / 2σ² )
```

`σ` (el "radio de influencia") es la distancia a la que un punto deja de
influir: a 1σ conserva el 61 % de su peso, a 2σ el 14 %, a 3σ el 1 %. Se usa un
kernel gaussiano en vez de contar puntos dentro de un radio porque este último
produce bordes duros — dos celdas contiguas pueden diferir en un punto entero
solo porque un banco cae justo a un lado de la circunferencia.

**Demanda y competencia se normalizan por separado antes de combinarse.** Este
es el punto que hay que entender del modelo. Restarlas en bruto, con los pesos
del documento original (notarías −3, resto +1), no produce un mapa de demanda
insatisfecha sino un mapa de densidad comercial: como hay del orden de diez
veces más oficinas bancarias que notarías, la demanda domina la resta y el
máximo cae justo encima del casco antiguo, que es exactamente donde ya están
todas las notarías. Con las dos capas en escala 0–1, el parámetro
`pesoCompetencia` (el slider "penalización por competencia") significa algo
interpretable: cuánto se descuenta por estar en zona saturada.

El motor está en `src/lib/heat.ts` y corre **en el navegador**, a propósito:
con los sliders el notario necesita ver el mapa recalcularse mientras arrastra.
Un municipio completo tarda unos 20 ms. Existe la misma implementación en
Python (`infra/`, repositorio de datos) para el precálculo por lotes y los
informes; las dos tienen que dar el mismo número.

## Color

El color está reservado para el score, con una rampa secuencial azul de un solo
tono. Las categorías de puntos se distinguen por **forma**, no por color:
cuadrado = oficina bancaria, triángulo = inmobiliaria, rombo = despacho de
abogados, anillo rojo = notaría existente. La razón es medible — la terna de
colores que se planteó para las tres categorías de demanda da una separación
ΔE de 1,6 en deuteranopía, es decir, indistinguible para cerca del 6 % de los
hombres. Con formas distintas el mapa se lee con cualquier visión y el canal de
color queda libre para lo único que varía de forma continua.

## Estado de los datos

La aplicación carga un corte estático de **Sabadell** (`src/data/sabadell.json`),
generado desde los Excel de `Raw data/xlsx` con `scripts/convertir_raw.py`.
Para regenerarlo tras actualizar los volcados:

```bash
python scripts/convertir_raw.py "ruta/a/Raw data/xlsx"
```

**Calidad de los volcados actuales.** De 130 registros, 20 quedan fuera del mapa
y la aplicación los declara en el panel izquierdo en vez de descartarlos en
silencio:

- 1 notaría sin coordenadas (Enrique Ruiz de Bustillo Pont). Es la incidencia
  grave: una notaría ausente de la capa de competencia hace que el mapa
  recomiende el portal de al lado de una notaría existente. Necesita
  geocodificarse.
- 18 inmobiliarias y 1 oficina bancaria fuera del término municipal — agencias
  de Barcelona, Terrassa, Manresa y Sitges que el propio Excel anota como
  "(cerca)". Dejarlas dentro no solo metía ruido: estiraba la rejilla de
  análisis a 55 km y hacía que un punto aislado en mitad del campo puntuara 100.

No hay volcado de despachos de abogados. La capa aparece como "sin datos" en vez
de con un 0, que se leería como "no hay ninguno en Sabadell".

El siguiente paso es sustituir `src/data/sabadell.ts` por la consulta a Supabase,
alimentada por la ingesta nacional (Consejo General del Notariado, Banco de
España, Overture Maps) ejecutada como GitHub Actions.

## Estructura

```
src/lib/heat.ts              motor de calor (rejilla, kernel, scoring, consultas)
src/lib/colores.ts           rampa del score y formas por categoría
src/data/sabadell.json       corte estático de datos de Sabadell
src/data/sabadell.ts         carga y tipado de ese corte
scripts/convertir_raw.py     Excel -> JSON, reproducible
infra/schema.sql             esquema PostGIS para Supabase
pipelines/heat.py            el mismo motor en Python, para lotes e informes
src/components/nook/         mapa y paneles
src/pages/Index.tsx          composición y estado de la aplicación
```
