# Estado y pendientes

Este fichero era la guía para pasar el ZIP a GitHub. Eso ya está hecho, así que
queda solo lo que sigue pendiente. El contexto del proyecto —el modelo, las
decisiones y por qué— está en `CLAUDE.md`.

## Arrancar el frontend

```powershell
npm install
npm run dev
```

**Node no está instalado en este equipo.** Hay que instalarlo (`winget install
OpenJS.NodeJS.LTS`) para poder levantar el frontend en local; mientras tanto,
el workflow de CI sí compila y comprueba tipos en cada push.

El pipeline de Python sí corre en local, salvo los tests de Overture: `duckdb
1.1.3` no publica rueda para Python 3.14 e intenta compilarse. CI usa 3.12 y
pasa entero.

```powershell
cd pipelines
python -m pytest tests -q
```

## Pendiente de código

1. Crear el proyecto de Supabase y aplicar `infra/schema.sql`.
2. Añadir los secretos `SUPABASE_URL` y `SUPABASE_SERVICE_KEY` al repositorio.
3. Ingesta en **modo prueba**, revisar el artefacto NDJSON, y solo entonces
   ejecutarla en modo real.
4. Sustituir `src/data/sabadell.ts` por la consulta a Supabase.
5. El test que falta: comprobar que `src/lib/heat.ts` y `pipelines/nook/heat.py`
   dan el mismo número con datos reales. Están duplicados a propósito y ahora
   mismo nada garantiza que no se separen.

## Pendiente que no depende del código

- **Restringir el token de Mapbox por dominio** en
  `account.mapbox.com/access-tokens`. Un token público sin restricción lo usa
  cualquiera que abra el inspector, y la factura la pagas tú. Con el
  repositorio ya publicado, esto sube de prioridad.
- **Solicitar acceso a la API de Idealista** en
  `developers.idealista.com/access-request`. Tarda, así que cuanto antes mejor.
- **Conseguir un volcado de despachos de abogados**, que no existe. Mientras
  tanto la capa aparece como "sin datos" en la interfaz.
- **Revisar las condiciones del Consejo General del Notariado** antes de vender.
  Ahora que el extractor de notarías funciona y baja el censo nacional, esto
  deja de ser teórico.

### Resuelto: la notaría "que faltaba"

Estaba anotado geocodificar a Enrique Ruiz de Bustillo Pont, en Sant Antoni Mª
Claret 1 de Sabadell, como la incidencia grave del volcado estático. **No es un
hueco de geocodificación: es un registro caducado.** En el censo en vivo esa
notaría no existe y en esa misma dirección está Lluis Colomé Serra. El volcado
de Sabadell arrastra el dato viejo; se corrige solo en cuanto la capa de
competencia venga de la Guía Notarial en lugar del corte estático.
