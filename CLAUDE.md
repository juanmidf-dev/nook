# Nook — contexto del proyecto

Herramienta que dice a un notario **dónde abrir su próxima notaría**: un mapa de
calor de demanda insatisfecha que cruza la demanda de la zona (oficinas
bancarias, inmobiliarias, despachos de abogados) con la competencia ya
instalada (notarías existentes), más los locales en alquiler disponibles.

Negocio: 500 € el informe de lanzamiento, 999 € a partir del décimo cliente,
199 € el listado de puntos de demanda para notarios ya establecidos.
Juanma (CEO) no viene de perfil técnico; el CTO es Juan Pérez Llorente.
**Todo el código, los comentarios y la interfaz están en español.**

---

## Lo que hay que entender antes de tocar nada

### 1. El modelo no resta demanda menos competencia

Es el error que traía el documento de producto original (notarías −3, resto +1)
y que se corrigió. Con pesos en bruto el resultado **no es demanda insatisfecha,
es densidad comercial**: en una ciudad hay del orden de diez veces más oficinas
bancarias que notarías, la demanda domina la resta y el máximo cae justo encima
del casco antiguo, que es exactamente donde ya están todas las notarías.

Lo correcto, y lo que está implementado: **normalizar demanda y competencia por
separado a 0–1 dentro del municipio** y solo después combinarlas con
`pesoCompetencia` (0,7 por defecto). Así ese parámetro significa algo
interpretable: cuánto se descuenta por estar en zona saturada.

Si alguien "simplifica" esto volviendo a la resta directa, el producto deja de
hacer lo que promete la propuesta comercial.

### 2. Cero registros nunca significa "no hay datos"

Significa que la fuente cambió y el parser ya no encaja. El pipeline **aborta**
en ese caso en vez de escribir un vacío: un upsert vacío no rompe nada visible,
pero deja el mapa sin esa capa hasta que alguien se da cuenta semanas después.

### 3. Un dato que falta se declara, no se descarta

De los volcados de Sabadell, 20 registros de 130 no entran al mapa y la
interfaz los muestra en el panel izquierdo con su motivo. El caso grave es una
notaría sin coordenadas: **una notaría ausente de la capa de competencia hace
que el mapa recomiende el portal de al lado de una notaría ya abierta.** Nunca
se inventan coordenadas para tapar un hueco.

### 4. El color está reservado para el score

Rampa secuencial azul de un solo tono (`src/lib/colores.ts`). Las categorías se
distinguen **por forma**: cuadrado = banco, triángulo = inmobiliaria, rombo =
abogados, anillo rojo = notaría, cruz = local en alquiler. No es estética: la
terna de colores que se planteó para las tres categorías de demanda daba una
separación ΔE de 1,6 en deuteranopía, indistinguible para cerca del 6 % de los
hombres. El acento dorado vive solo en el cromo de la interfaz, nunca sobre el
mapa.

### 5. El motor de calor está duplicado a propósito

- `src/lib/heat.ts` — corre en el navegador para que los sliders recalculen en
  vivo (~24 ms por municipio). Sin esto, arrastrar un slider haría una ida y
  vuelta al servidor y la herramienta sería inservible.
- `pipelines/nook/heat.py` — el mismo modelo, para precálculo por lotes e
  informes en PDF.

**Las dos implementaciones tienen que dar el mismo número.** Falta un test que
lo compruebe con datos reales; es una tarea pendiente que merece la pena.

---

## Estructura

```
src/lib/heat.ts              motor de calor: rejilla H3, kernel gaussiano, scoring
src/lib/colores.ts           rampa del score y formas por categoría
src/data/sabadell.json       corte estático de datos reales de Sabadell
src/data/sabadell.ts         carga y tipado de ese corte
src/components/nook/         mapa (Mapbox GL) y paneles
src/pages/Index.tsx          composición y estado
scripts/convertir_raw.py     Excel -> JSON, reproducible
infra/schema.sql             esquema PostGIS para Supabase
pipelines/                   ingesta: extractores, geocodificación, escritura
.github/workflows/           ci, reconocimiento, ingesta
_obsoleto/                   restos del MVP de Lovable; no se usa
```

## Comandos

```bash
npm install && npm run dev          # frontend (necesita .env, ver abajo)
npx tsc --noEmit -p tsconfig.app.json
npm run build

cd pipelines
pip install -r requirements.txt
python -m pytest tests -q           # 38 tests, ninguno toca la red
python cli.py bancos --prueba --entrada datos/entrada/bde
```

`.env` no está en el repositorio. Copia `.env.example` y pon
`VITE_MAPBOX_TOKEN`. **El token de Mapbox debe restringirse por dominio** en
`account.mapbox.com/access-tokens` antes de publicar: un token público sin
restricción lo usa cualquiera que abra el inspector.

---

## Estado actual

| Pieza | Estado |
|---|---|
| Frontend Nook v2 | Funcionando con datos reales de Sabadell |
| Motor de calor (TS y Python) | Hecho y verificado |
| Esquema PostGIS | Escrito, sin desplegar |
| Extractor Banco de España | **Listo y probado** contra un fichero real |
| Extractor Overture Maps | Listo; consulta y transformación probadas contra parquet local, sin ejecutar aún contra S3 |
| Extractor Guía Notarial | **Pendiente del endpoint** — ver abajo |
| Supabase | No existe todavía |
| Idealista | Sin solicitar la API |

### Lo primero que hay que hacer en Claude Code

1. **Subir el repositorio a GitHub.** Era el bloqueante en la sesión anterior.
2. Ejecutar `Actions → Reconocimiento de fuentes → Run workflow`.
3. Con su artefacto, cerrar el extractor de notarías (ver siguiente sección).
4. Crear el proyecto de Supabase, aplicar `infra/schema.sql`, y añadir los
   secretos `SUPABASE_URL` y `SUPABASE_SERVICE_KEY`.
5. Ingesta en modo prueba, revisar el artefacto, y solo entonces en modo real.

### El endpoint de la Guía Notarial

`guianotarial.notariado.org` es una aplicación React: la lista de notarías no
está en el HTML, se la pide su JavaScript a un endpoint no documentado. En la
sesión anterior no se pudo inspeccionar porque ni el entorno de Claude ni el
equipo local tienen salida hacia ese dominio.

`reconocimiento.yml` existe para eso: baja los bundles, busca en ellos las rutas
de API, las prueba y deja todo como artefacto. Con eso se rellena `ENDPOINT` en
`pipelines/nook/fuentes/notarias.py` o el secreto `NOOK_ENDPOINT_NOTARIAS`.

**No se dejó un endpoint inventado que pareciera plausible**, y conviene no
dejarlo: un extractor que falla en silencio es peor que uno que no existe.

---

## Restricciones del entorno que condicionan el diseño

- **Ni el entorno de desarrollo ni el equipo local alcanzan** notariado.org,
  app.bde.es, Overpass ni el INE. Por eso los extractores corren en GitHub
  Actions: no es una preferencia de arquitectura, es la única vía. Si en Claude
  Code sí hay salida, se puede probar en local, pero la ejecución de producción
  sigue siendo Actions (cron, histórico, y no depende de la máquina de nadie).
- **Google Places está descartado** para construir la base de datos: sus
  términos prohíben almacenar los resultados más de 30 días salvo el
  `place_id`, así que con Google no se puede construir el activo que se vende.
  Overture Maps sí permite almacenar y redistribuir. Google solo cabe como
  validación puntual en vivo.
- **Overture con versión fija, nunca `latest`.** Una ingesta mensual que cambia
  de versión de dataset sin avisar mueve puntos de sitio, y después no hay forma
  de explicarle a un cliente por qué su mapa cambió de un mes a otro.

## Convenciones

- Español en todo: nombres de funciones, comentarios, mensajes de log, interfaz.
- Los comentarios explican **por qué**, no qué. Si un comentario se limita a
  repetir el código, sobra.
- Identificadores deterministas (`id_estable`) en todos los extractores: ninguna
  de estas fuentes publica clave propia, y sin id estable la ejecución mensual
  duplica en vez de actualizar.
- Modo prueba por defecto en la ingesta. El botón "Run workflow" no escribe en
  la base de datos salvo que se pida `real` explícitamente.
- Ritmo limitado y agente identificado en todo lo que sale a la red: las fuentes
  son portales de organismos públicos y colegios profesionales, no APIs
  comerciales.

## Riesgo abierto, no técnico

La extracción de la Guía Notarial es de un directorio profesional público, pero
para uso comercial conviene revisar las condiciones del Consejo General del
Notariado, e idealmente buscar un acuerdo. Mejor abordarlo antes de tener
clientes que después.
