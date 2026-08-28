# Cómo pasar esto a GitHub y seguir en Claude Code

Esta carpeta no es un repositorio git todavía: es el ZIP descomprimido. Estos
son los pasos, en orden.

## 1. Antes de nada, comprueba que arranca

```powershell
cd C:\Users\Usuario\Documents\Claude\Projects\sabadell-eats-heatmap-main
npm install
npm run dev
```

Debería abrirse Sabadell con el mapa oscuro y los hexágonos. Si sale la pantalla
de "Falta el token de Mapbox", es que `.env` no está donde debe; se creó
automáticamente, pero compruébalo.

## 2. Borra lo que ya no sirve

La carpeta `_obsoleto/` tiene los ficheros del MVP de Lovable que ya no se usan
y el ZIP de la entrega. No los borré yo porque el puente con tu ordenador no
tiene permiso de borrado. Bórrala tú antes de subir nada:

```powershell
Remove-Item -Recurse -Force _obsoleto
```

## 3. Sube el repositorio

**Si quieres reutilizar el repo que ya tienes** (`sabadell-eats-heatmap`):

```powershell
git init
git add .
git commit -m "Nook v2: motor de calor, datos reales de Sabadell y pipeline de ingesta"
git branch -M main
git remote add origin https://github.com/juanmidf-dev/sabadell-eats-heatmap.git
git push -u origin main --force
```

El `--force` es necesario porque estás reemplazando el contenido del MVP. Si
prefieres conservar el historial anterior, clona el repo en otra carpeta, copia
estos ficheros encima y haz un commit normal.

**Nota sobre el nombre:** `sabadell-eats-heatmap` viene de la plantilla de
Lovable con la que arrancó el MVP y ya no describe el proyecto. Merece la pena
renombrarlo a `nook` en Settings → General → Repository name. Si lo haces,
actualiza el `remote` con `git remote set-url origin ...`.

**Ojo con Lovable:** si el proyecto sigue sincronizado con Lovable, este push
cambiará también lo que ves allí. Es lo esperado, pero que no te pille por
sorpresa.

## 4. Comprueba que `.env` NO se ha subido

```powershell
git ls-files | Select-String "\.env$"
```

No debe devolver nada. `.gitignore` ya lo excluye, pero merece la pena mirarlo:
ese fichero lleva tu token de Mapbox.

## 5. Abre Claude Code en la carpeta

```powershell
cd C:\Users\Usuario\Documents\Claude\Projects\sabadell-eats-heatmap-main
claude
```

Claude Code lee `CLAUDE.md` automáticamente al arrancar, así que llega con todo
el contexto: el modelo, las decisiones tomadas y por qué, el estado de cada
extractor y lo que queda pendiente. No hace falta que le expliques nada.

**Por qué en Code sí funciona GitHub:** Claude Code se ejecuta en tu ordenador y
usa tus propias credenciales de git, las mismas que el `git push` del paso 3.
No hay que darle acceso a nada ni pasarle ningún token — el problema que
tuvimos en la sesión anterior desaparece solo. Si además instalas el CLI de
GitHub (`winget install GitHub.cli` y luego `gh auth login`), podrá crear ramas
y abrir pull requests directamente.

Aparte de eso, `/install-github-app` dentro de Claude Code instala la app de
GitHub para que Claude revise pull requests y responda en el repositorio. Es
opcional y no hace falta para trabajar.

## 6. Lo primero que le puedes pedir

> Ejecuta el workflow de reconocimiento y, con el artefacto, cierra el extractor
> de la Guía Notarial.

Ese es el bloqueante real: sin el endpoint de las notarías no hay capa de
competencia, y sin capa de competencia el mapa no vale para lo que se vende.

Después, por orden:

1. Crear el proyecto de Supabase y aplicar `infra/schema.sql`.
2. Añadir los secretos `SUPABASE_URL` y `SUPABASE_SERVICE_KEY` al repositorio.
3. Ingesta en **modo prueba**, revisar el artefacto NDJSON, y solo entonces
   ejecutar en modo real.
4. Sustituir `src/data/sabadell.ts` por la consulta a Supabase.

## Cosas que siguen pendientes y no dependen del código

- **Restringir el token de Mapbox por dominio** en
  `account.mapbox.com/access-tokens`. Un token público sin restricción lo usa
  cualquiera que abra el inspector, y la factura la pagas tú.
- **Solicitar acceso a la API de Idealista** en
  `developers.idealista.com/access-request`. Tarda, así que cuanto antes mejor.
- **Geocodificar la notaría que falta**: Enrique Ruiz de Bustillo Pont, calle
  Sant Antoni Mª Claret 1, Sabadell. Es la incidencia grave de los datos.
- **Conseguir un volcado de despachos de abogados**, que no existe. Mientras
  tanto la capa aparece como "sin datos" en la interfaz.
- **Revisar las condiciones del Consejo General del Notariado** antes de vender.
