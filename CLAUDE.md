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
abogados, círculo = gestoría, anillo rojo = notaría, cruz = local en alquiler. No es estética: la
terna de colores que se planteó para las tres categorías de demanda daba una
separación ΔE de 1,6 en deuteranopía, indistinguible para cerca del 6 % de los
hombres. El acento dorado vive solo en el cromo de la interfaz, nunca sobre el
mapa.

### 5. El motor de calor está duplicado a propósito, y ahora se comprueba

- `src/lib/heat.ts` — corre en el navegador para que los sliders recalculen en
  vivo (159 ms para los 4.444 puntos de Madrid). Sin esto, arrastrar un slider
  haría una ida y vuelta al servidor y la herramienta sería inservible.
- `pipelines/nook/heat.py` — el mismo modelo, para precálculo por lotes e
  informes en PDF.

**Las dos implementaciones tienen que dar el mismo número**, y desde el
29/08/2026 hay un test que lo verifica: `pipelines/tests/test_heat.py` compara
contra la salida real de `heat.ts`, que genera
`scripts/exportar_heat_ts.mjs`. Cinco configuraciones distintas, tolerancia de
0,01 puntos de score, y además el orden del ranking.

Cuando se escribió, **no coincidían**: hasta 1,6 puntos de score. La causa era
la proyección —`heat.ts` usaba una equirectangular local y `heat.py` una UTM de
pyproj, y encima la zona 30N, válida hasta el meridiano 0, con Barcelona a
2,1° **este**—. Ahora `heat.py` usa la misma fórmula escrita a mano, así que la
equivalencia no depende de que dos librerías coincidan. `pyproj` ya no es
dependencia.

Si tocas cualquiera de los dos motores, regenera el fixture:
`node scripts/exportar_heat_ts.mjs`. CI falla si no está al día, porque si no
el test seguiría pasando contra la versión antigua y la comprobación dejaría
de comprobar nada.

La versión de `h3` en `requirements.txt` va emparejada con la de `h3-js` en
`package.json` por el mismo motivo.

### 6. En Supabase, `geom` la rellena un trigger y `cod_ine` no tiene FK

Los extractores escriben por PostgREST y solo pueden mandar `lat` y `lon`
planos: la API REST no construye un `geography`. Sin el trigger
`geom_desde_latlon`, la columna `geom` se queda a NULL, y como los índices
espaciales y `puntos_de_demanda()` cuelgan de ella, **la tabla se llena, todo
parece correcto y las consultas por distancia devuelven vacío**. El entregable
de 199 € sale en blanco sin que nada dé error.

`pois.cod_ine` y `locales.cod_ine` no tienen clave ajena a `municipios` a
propósito. Esa tabla se carga del INE y todavía no hay nada que la puebla,
mientras que el Banco de España sí publica el código INE de cada oficina: con
la FK puesta, la primera ingesta real rechaza el lote entero de 500 registros.
Descartar el `cod_ine` para que encajara sería tirar un dato bueno. Cuando
`municipios` esté cargada se recupera la integridad con `not valid` y luego
`validate constraint`, sin bloquear la tabla; está escrito en `schema.sql`.

### 7. CartoCiudad habla JSONP y quiere la dirección corta

Dos detalles que costaron el 97 % de la capa de competencia en la primera
ingesta real, y ninguno de los dos daba error.

El único endpoint de geocodificación del IGN es `findJsonp`, y responde
`callback([...])` con `content-type: application/x-javascript`. `r.json()` no
puede con eso: por eso existe `Cliente.jsonp`.

Y la consulta tiene que ser **`vía, portal, municipio`** y nada más. Con la
planta, el local, el edificio, la palabra "número" o la provincia dentro,
CartoCiudad devuelve **lista vacía**, que es indistinguible de "esta dirección
no existe". Medido sobre 30 direcciones reales del censo: 0 de 30 con el texto
completo, 28 de 30 —todas a nivel de portal— reducido. De ahí
`geocode.para_cartociudad`. Nominatim, en cambio, sí agradece el contexto
completo, así que cada uno recibe su propia consulta.

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
infra/verificar_ingesta.sql  comprobaciones posteriores a una ingesta real
pipelines/                   ingesta: extractores, geocodificación, escritura
pipelines/datos/bde/         CSV del Banco de España, descargado a mano
pipelines/datos/referencia/  taxonomía de Overture, para validar categorías
.github/workflows/           ci, reconocimiento, ingesta, mantener-supabase
```

## Comandos

```bash
npm install && npm run dev          # frontend (necesita .env, ver abajo)
npx tsc --noEmit -p tsconfig.app.json
npm run build

cd pipelines
pip install -r requirements.txt
python -m pytest tests -q           # 114 tests, ninguno toca la red
python cli.py bancos --prueba       # lee datos/bde/*.csv
python cli.py notarias --prueba
```

`.env` no está en el repositorio. Copia `.env.example` y pon
`VITE_MAPBOX_TOKEN`. **El token de Mapbox debe restringirse por dominio** en
`account.mapbox.com/access-tokens` antes de publicar: un token público sin
restricción lo usa cualquiera que abra el inspector.

---

## Estado actual

| Pieza | Estado |
|---|---|
*Actualizado el 29/08/2026.*

| Pieza | Estado |
|---|---|
| Frontend | Funciona, pero sigue leyendo `src/data/sabadell.json`, no Supabase |
| Motor de calor en TypeScript | Hecho y en uso |
| Motor de calor en Python | **No se ejecuta**: `h3`, `numpy`, `pyproj` y `scipy` no están en `requirements.txt`, nadie lo importa y no tiene tests |
| Supabase | **Desplegada y verificada.** Trigger de `geom` comprobado: 0 filas con lat/lon y sin geometría, desvío 0 m |
| Extractor Guía Notarial | **En producción.** 2.641 notarías escritas, 2.458 ubicadas |
| Extractor Banco de España | **En producción** para Cataluña y Madrid: 4.024 oficinas, 93,5 % geocodificadas. Faltan 15 comunidades |
| Extractor Overture Maps | Categorías corregidas contra la taxonomía real; **sin ejecutar nunca contra S3** |
| Geocodificación | 93 % del censo notarial a nivel de portal |
| Locales en alquiler | Sin fuente. Idealista sin solicitar |
| Abogados y gestorías | Dependen de Overture, que no se ha estrenado |

### La capa de gestorías está a medias, y se sabe cuánto

Medido el 29/08/2026 y anotado para no repetir el recorrido.

El registro oficial declara **7.664 despachos colegiados** en España, o sea 1
por cada 6.340 habitantes. La caja de prueba de Sabadell cubre unos 310.000
habitantes, así que tocarían unas 49; **Overture encontró 26**. Y la cobertura
real es peor que ese 53 %, porque nuestra categoría de Overture es más ancha
que la colegiación: incluye contables, asesores fiscales y consultores, o sea
el CNAE 6920 completo. Encuentra menos con una definición más amplia.

La causa es que la taxonomía de Overture es de origen anglosajón y la figura
del gestor administrativo no existe allí: los despachos españoles quedan sin
catalogar o como `professional_services` genérico.

**Fuentes descartadas, con su motivo:**

- `gestorias.es` — directorio **comercial privado**, no censo. Su `robots.txt`
  prohíbe `/buscar`, que es el único modo de enumerarlo, y no publica sitemap.
  Al margen de eso, extraer el catálogo de una empresa privada para revenderlo
  choca de frente con el derecho *sui generis* sobre bases de datos (arts.
  133-137 LPI). No se toca.
- `registro.consejogestores.org` — es el censo oficial y bueno, pero su
  `robots.txt` prohíbe toda URL con parámetros (`Disallow: /*?*`), que es
  justo la forma del buscador, y la página lleva **reCAPTCHA**. Es una
  declaración inequívoca de "esto se consulta a mano". No se automatiza.

**Vías abiertas**, por orden de preferencia: pedir el censo al Consejo General
(`consejo@consejogestores.net`; el registro es público por el art. 10 de la
Ley 17/2009); comprar un extracto licenciado por CNAE 6920 a Informa D&B o
similar; o convivir con la cobertura parcial **declarándola** en la interfaz,
como ya se hace con los abogados.

Son 7.664 registros: el mismo orden que las notarías, no el de las
inmobiliarias. Geocodificarlo entero son dos horas largas.

### Pendientes anotados con su razón

- ~~Gestorías y asesorías como capa de demanda.~~ Hecho el 29/08/2026. Quinto
  tipo de POI, con forma de círculo relleno en el mapa. Categorías reales de
  la taxonomía: `accountant`, `bookkeeper`, `tax_services`, `payroll_services`
  y `business_consulting`. `tax_office` queda fuera a propósito: cuelga de
  `public_service_and_government`, es la Agencia Tributaria.
- **Registros de la Propiedad y Mercantiles.** El enum `poi_tipo` ya incluye
  `registro` y nada lo puebla.
- **Población por sección censal.** Ver más abajo por qué la municipal no
  vale.

### Lo primero que hay que hacer

1. ~~Subir el repositorio a GitHub.~~ Hecho.
2. ~~Reconocimiento y cierre del extractor de notarías.~~ Hecho, en local:
   desde el equipo sí hay salida a notariado.org (ver más abajo).
3. Crear el proyecto de Supabase, aplicar `infra/schema.sql`, y añadir los
   secretos `SUPABASE_URL` y `SUPABASE_SERVICE_KEY`.
4. Ingesta en modo prueba, revisar el artefacto, y solo entonces en modo real.
5. Sustituir `src/data/sabadell.ts` por la consulta a Supabase.

### El endpoint de la Guía Notarial (confirmado el 28/08/2026)

    POST https://guianotarial.notariado.org/guianotarial/rest/buscar/notarios

Cuerpo: el formulario completo con todos los campos presentes aunque vayan
vacíos, y `codigoSituacionNotario: "AC"` para quedarse con los notarios en
activo. Sin autenticación —la aplicación tiene un `/tokenjwt`, pero este
buscador no lo pide—. Devuelve **el censo nacional en una sola petición y sin
paginar**: 2.641 notarios en la comprobación.

**Una petición, no 52.** El portal corta con 429 tras unas veinte peticiones
seguidas, incluso espaciadas dos segundos: enumerar provincias se queda a
medias y marca la IP del runner. Si hace falta filtrar por provincia, se
filtra sobre el resultado.

**La fuente sí publica clave propia**, al contrario de lo que se supuso antes
de verla: `codigoNotaria`. Se usa como `fuente_id` en vez del hash de nombre y
dirección, porque sobrevive a que un despacho cambie de domicilio —con el hash,
una notaría que se muda aparecía como un cierre más un alta nueva—.

El nombre viene invertido en un único campo `apellidos_nombre` ("Apellidos,
Nombre") y la dirección trae el código postal pegado al final sin separador.
Ambas cosas están cubiertas por `tests/test_notarias.py`, con registros reales.

`reconocimiento.yml` sigue siendo útil para las demás fuentes. Ojo: pedía la
Guía por `http://`, y así el HTML responde pero sus bundles dan 404, que es por
lo que el descubrimiento automático volvía vacío. Ya está corregido a `https`.

---

## Restricciones del entorno que condicionan el diseño

- **El Banco de España responde al equipo local y bloquea al runner.** Es al
  revés de lo que se supuso al principio, y condiciona toda la estrategia de
  esa fuente. Comprobado el 28/08/2026 con `reconocimiento.yml`:
  `app.bde.es/exbwciu/exbwciuias/xml/Arranque.html` sale `inalcanzable` desde
  Actions y **HTTP 200 desde el equipo**. Es lo normal en sedes de la
  administración española, que filtran rangos de IP de nube. Conclusión:
  **automatizar la descarga del registro de oficinas en Actions no es una
  opción**, por bien que esté hecho el formulario. O fichero descargado a mano
  y versionado, o un extractor que se ejecute en la máquina de alguien.
  La sede del Catastro (403) tampoco la alcanza el runner.
- **Desde Claude Code en el equipo local sí hay salida** a notariado.org, a
  api.github.com, a cartociudad.es y a app.bde.es. Por eso el reconocimiento y
  el cierre del extractor de notarías se hicieron aquí, sin esperar a un
  runner, y por eso se pudo depurar la geocodificación contra el servicio real
  (ver punto 7). Para todo lo que sí alcanza el runner, la ejecución de
  producción sigue siendo Actions: cron, histórico, y no depende de la máquina
  de nadie.
- **Google Places está descartado** para construir la base de datos: sus
  términos prohíben almacenar los resultados más de 30 días salvo el
  `place_id`, así que con Google no se puede construir el activo que se vende.
  Overture Maps sí permite almacenar y redistribuir. Google solo cabe como
  validación puntual en vivo.
- **Overture con versión fija, nunca `latest`.** Una ingesta mensual que cambia
  de versión de dataset sin avisar mueve puntos de sitio, y después no hay forma
  de explicarle a un cliente por qué su mapa cambió de un mes a otro.
  **Pero el pin caduca**: Overture borra de S3 las releases antiguas. El
  29/08/2026 solo quedaban dos publicadas y la que teníamos fijada, de un año
  antes, ya no existía; la ingesta murió con `IO Error: No files found`. Falla
  en alto y en cuatro segundos, que es lo aceptable, pero hay que revisar el
  pin cada pocos meses. Qué hay publicado ahora, sin credenciales:
  `https://overturemaps-us-west-2.s3.amazonaws.com/?list-type=2&prefix=release/&delimiter=/`

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
