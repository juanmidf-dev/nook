"""
Exporta **todo** lo que hay en Supabase, repartido por provincias.

Sustituye al exportador de tres municipios escritos a mano. El problema de
aquel no era técnico: en la base de datos hay 54.335 puntos y el mapa solo veía
los 8.000 de Sabadell, Barcelona y Madrid, porque el diccionario `MUNICIPIOS`
tenía tres entradas y ampliarlo exigía teclear a mano el centro y el zoom de
cada municipio nuevo.

**Por qué por provincia y no por municipio.**

Un corte municipal no puede quedarse dentro del término: una notaría al otro
lado del límite es competencia real, así que el corte se toma por caja
alrededor del centro. Con tres municipios eso daba igual; con mil, los cortes
del área metropolitana de Barcelona se solapan tanto que el mismo punto
acabaría copiado en decenas de ficheros y el total se iría a cientos de megas.
Por provincia no hay duplicación —cada punto aparece una vez—, son 52 ficheros
en lugar de mil, y cambiar de municipio dentro de la misma provincia no cuesta
ni una descarga.

**Por qué el centro se calcula y no se escribe.**

Son 8.132 municipios: teclear centro y zoom no escala. El INE publica los
códigos pero no las coordenadas, y la columna `geom` de la tabla `municipios`
está vacía. Así que el centro sale de la **mediana** de los puntos del propio
municipio, que es lo único que hay y además es honesto: un municipio sin
ningún punto no tiene centro, y queda declarado sin datos en vez de aparecer
con un centro inventado.

Mediana y no media a propósito: una sola coordenada mal geocodificada
—CartoCiudad devolviendo otro pueblo— desplazaría la media del municipio
entero y el mapa abriría mirando al sitio equivocado.

    python scripts/exportar_espana.py
"""

from __future__ import annotations

import collections
import json
import math
import os
import pathlib
import statistics
import sys

import requests

RAIZ = pathlib.Path(__file__).resolve().parents[1]
CATALOGO = RAIZ / "src" / "data" / "municipios.json"

# `public/` y no `src/data/`: estos ficheros los pide el navegador cuando el
# usuario elige provincia, no van dentro del bundle. Metidos en `src/`, Vite
# generaría 52 chunks de JavaScript y el de Barcelona pesa megas.
DESTINO = RAIZ / "public" / "datos"

sys.path.insert(0, str(RAIZ / "pipelines"))
from nook.geografia import PROVINCIAS, cod_provincia_desde_cp  # noqa: E402
from nook.modelo import normaliza  # noqa: E402

# PostgREST corta a 1.000 filas y **no avisa**: devuelve 200 con la primera
# página y ya. Pedir `limit=100000` no sirve, porque el tope del servidor manda
# sobre el del cliente.
PAGINA = 1000

CAMPOS = (
    "fuente_id,tipo,nombre,direccion,cp,municipio,cod_ine,"
    "telefono,email,web,lat,lon,geocode_fuente,geocode_calidad"
)

DEMANDA = {"banco", "inmobiliaria", "abogados", "gestoria"}


def pide(base: str, cab: dict, ruta: str, params: dict) -> list[dict]:
    """Trae todas las filas, paginando hasta que el servidor se queda corto."""
    filas: list[dict] = []
    desde = 0
    while True:
        p = dict(params, limit=str(PAGINA), offset=str(desde))
        r = requests.get(f"{base}/rest/v1/{ruta}", headers=cab, params=p, timeout=120)
        if r.status_code >= 300:
            raise SystemExit(f"Supabase devolvio {r.status_code}: {r.text[:300]}")
        pagina = r.json()
        filas.extend(pagina)
        if len(pagina) < PAGINA:
            return filas
        desde += PAGINA
        print(f"  {ruta}: {len(filas)} filas...", flush=True)
        if desde > 500_000:
            raise SystemExit(f"{ruta}: mas de 500.000 filas, algo no encaja")


# Artículos que cada fuente coloca donde le parece. El INE los pospone
# —«Hospitalet de Llobregat, L'», «Coruña, A»—, las demás fuentes los
# anteponen o los quitan directamente.
ARTICULOS = {"el", "la", "lo", "los", "las", "l", "els", "les", "es",
             "sa", "ses", "o", "a", "os", "as", "na"}


def claves(nombre: str) -> tuple[str, str, str]:
    """
    Tres formas del mismo nombre, de más estricta a más permisiva.

    1. El nombre normalizado tal cual.
    2. Sin los artículos de los extremos, que es donde cada fuente los mueve:
       «L'Hospitalet de Llobregat» y «Hospitalet de Llobregat, L'» son el
       mismo sitio escrito por dos organismos distintos.
    3. Las palabras ordenadas, que absorbe cualquier reordenación.

    La tercera **no** vale por sí sola, y este es el motivo: ordenando las
    palabras, «Mora de Rubielos» y «Rubielos de Mora» —dos municipios
    distintos de Teruel, a 30 km uno del otro— salen idénticos. Lo mismo con
    «Negrilla de Palencia» y «Palencia de Negrilla» en Salamanca. Por eso se
    prueba en último lugar y solo cuando no hay empate.
    """
    n = normaliza(nombre)
    palabras = n.split()
    while palabras and palabras[0] in ARTICULOS:
        palabras.pop(0)
    while palabras and palabras[-1] in ARTICULOS:
        palabras.pop()
    sin_articulo = " ".join(palabras) or n
    return n, sin_articulo, " ".join(sorted(palabras or n.split()))


def indice_ine() -> tuple[list[dict], dict[str, dict]]:
    """
    Del catálogo del INE: tres índices (provincia, clave) -> cod_ine, y las fichas.

    La clave lleva la provincia porque hay nombres repetidos en España
    —Villanueva, Los Santos, Fuentes: 17 se repiten entre provincias— y cruzar
    solo por nombre metería los puntos de un municipio en otro a 500 km.

    Las claves ambiguas dentro de una misma provincia se **borran** del índice
    en vez de quedarse con una de las dos. Un punto sin municipio asignado
    entra igual en su provincia y se cuenta aparte; un punto asignado al
    municipio equivocado falsea el mapa de otro sitio sin que nada lo delate.
    """
    cat = json.loads(CATALOGO.read_text(encoding="utf-8"))
    niveles: list[dict] = [{}, {}, {}]
    ambiguas: list[set] = [set(), set(), set()]
    fichas: dict[str, dict] = {}

    for ccaa in cat["ccaa"]:
        for prov in ccaa["provincias"]:
            for cod_ine, nombre in prov["municipios"]:
                fichas[cod_ine] = {
                    "nombre": nombre,
                    "provincia": prov["nombre"],
                    "cod_provincia": prov["cod"],
                }
                for i, c in enumerate(claves(nombre)):
                    k = (prov["cod"], c)
                    if niveles[i].setdefault(k, cod_ine) != cod_ine:
                        ambiguas[i].add(k)

    for i, malas in enumerate(ambiguas):
        for k in malas:
            del niveles[i][k]
        if malas:
            print(f"  nivel {i + 1}: {len(malas)} claves ambiguas descartadas")
    return niveles, fichas


def cod_provincia_de(fila: dict) -> str | None:
    """
    La provincia de un punto, por orden de fiabilidad.

    El `cod_ine` lo pone el geocodificador oficial o la propia fuente, así que
    manda. Después el código postal, que en España determina la provincia sin
    excepciones. El campo `provincia` en texto no se usa aquí: viene de Overture
    como texto libre y trae desde «Catalonia» hasta barrios de Madrid.
    """
    cod_ine = fila.get("cod_ine")
    if cod_ine and str(cod_ine)[:2] in PROVINCIAS:
        return str(cod_ine)[:2]
    return cod_provincia_desde_cp(fila.get("cp"))


def asigna_municipio(fila: dict, niveles: list[dict], cod_prov: str | None) -> str | None:
    """El cod_ine del punto: el suyo si lo trae, y si no por nombre dentro de su provincia."""
    cod_ine = fila.get("cod_ine")
    if cod_ine and len(str(cod_ine)) == 5 and str(cod_ine).isdigit():
        return str(cod_ine)
    muni = fila.get("municipio")
    if not muni or not cod_prov:
        return None
    for nivel, c in zip(niveles, claves(muni)):
        encontrado = nivel.get((cod_prov, c))
        if encontrado:
            return encontrado
    return None


def compacta(f: dict) -> dict:
    """Solo lo que pinta el mapa, y sin campos vacíos: son 54.000 registros."""
    p = {
        "id": f["fuente_id"],
        "categoria": f["tipo"],
        "nombre": f["nombre"],
        "lat": f["lat"],
        "lon": f["lon"],
    }
    for campo in ("direccion", "telefono", "email", "web"):
        if f.get(campo):
            p[campo] = f[campo]
    return p


def geometria(puntos: list[dict]) -> dict:
    """
    Centro, radio y zoom de un municipio a partir de sus propios puntos.

    El radio sale del percentil 90 de la distancia al centro, no del máximo: un
    punto mal geocodificado a 40 km estiraría la caja hasta dejar el municipio
    como una mancha en una esquina. Y se acota por abajo porque en un pueblo con
    dos puntos la dispersión es casi cero, y una caja de 200 metros no deja ver
    nada alrededor —que es justo lo que hace falta, porque la competencia del
    pueblo de al lado también cuenta—.
    """
    lats = [p["lat"] for p in puntos]
    lons = [p["lon"] for p in puntos]
    lat_c, lon_c = statistics.median(lats), statistics.median(lons)
    m_lat = 111132.95
    m_lon = 111320 * math.cos(math.radians(lat_c))

    distancias = sorted(
        math.hypot((la - lat_c) * m_lat, (lo - lon_c) * m_lon)
        for la, lo in zip(lats, lons)
    )
    p90 = distancias[min(len(distancias) - 1, int(len(distancias) * 0.9))]
    radio = max(2500.0, min(12000.0, p90 * 1.25))

    # El zoom que encuadra ese radio en una ventana de unos 900 px. Sale de la
    # escala de Web Mercator: cada nivel dobla la resolución.
    zoom = math.log2(156543.03 * math.cos(math.radians(lat_c)) * 900 / (radio * 2))
    return {
        "centro": [round(lon_c, 5), round(lat_c, 5)],
        "zoom": round(max(9.0, min(14.5, zoom)), 1),
        "radio": int(radio),
    }


def main() -> None:
    url, secreto = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not secreto:
        raise SystemExit("faltan SUPABASE_URL o SUPABASE_SERVICE_KEY")
    base = url.rstrip("/")
    cab = {"apikey": secreto}
    if secreto.startswith("eyJ"):
        cab["Authorization"] = f"Bearer {secreto}"

    niveles, fichas = indice_ine()
    print(f"catalogo del INE: {len(fichas)} municipios")

    print("descargando pois...")
    filas = pide(base, cab, "pois", {"select": CAMPOS, "activo": "is.true"})
    print("descargando locales...")
    locales = pide(base, cab, "locales", {"select": "fuente_id,titulo,direccion,lat,lon,fuente,cp"})

    # Misma regla que la ingesta: cero registros no significa «no hay datos»,
    # significa que algo dejó de encajar. Mejor fallar que dejar el mapa en
    # blanco sin que nada dé error.
    if not filas:
        raise SystemExit("la consulta de pois ha devuelto 0 filas; se aborta")

    por_provincia: dict[str, dict] = {
        cod: {"pois": [], "locales": [], "incidencias": []} for cod in PROVINCIAS
    }
    puntos_municipio: dict[str, list[dict]] = collections.defaultdict(list)
    sin_provincia = sin_municipio = 0

    for f in filas:
        cod_prov = cod_provincia_de(f)
        if not cod_prov:
            sin_provincia += 1
            continue
        cod_ine = asigna_municipio(f, niveles, cod_prov)

        if f.get("lat") is None or f.get("lon") is None:
            # Lo que no entra al mapa se declara, no se descarta: una notaría
            # ausente de la capa de competencia hace que el mapa recomiende el
            # portal de al lado de una notaría ya abierta.
            por_provincia[cod_prov]["incidencias"].append({
                "categoria": f["tipo"],
                "nombre": f["nombre"],
                "direccion": f.get("direccion") or "",
                "codIne": cod_ine,
                # «No se encontró» se arregla mejorando la consulta; «se
                # encontró mal» hay que buscarlo a mano. No son el mismo caso.
                "motivo": (
                    f"solo a nivel de {f.get('geocode_calidad')}"
                    if f.get("geocode_fuente") else "sin coordenadas"
                ),
            })
            continue

        if cod_ine:
            puntos_municipio[cod_ine].append(f)
        else:
            sin_municipio += 1
        por_provincia[cod_prov]["pois"].append(compacta(f))

    for l in locales:
        cod_prov = cod_provincia_desde_cp(l.get("cp"))
        if not cod_prov or l.get("lat") is None:
            continue
        por_provincia[cod_prov]["locales"].append({
            "id": l["fuente_id"],
            "nombre": l.get("titulo") or "Local en alquiler",
            "direccion": l.get("direccion") or "",
            "fuente": l.get("fuente") or "",
            "lat": l["lat"],
            "lon": l["lon"],
        })

    municipios_indice: dict[str, dict] = {}
    for cod_ine, puntos in puntos_municipio.items():
        ficha = fichas.get(cod_ine)
        if not ficha:
            # Un cod_ine que no está en el catálogo: municipio fusionado o
            # código mal formado. No se le inventa una ficha.
            continue
        conteos = collections.Counter(p["tipo"] for p in puntos)
        municipios_indice[cod_ine] = {
            "nombre": ficha["nombre"],
            "provincia": ficha["provincia"],
            "codProvincia": ficha["cod_provincia"],
            **geometria(puntos),
            "conteos": dict(conteos),
            "demanda": sum(n for t, n in conteos.items() if t in DEMANDA),
            "competencia": conteos.get("notaria", 0),
        }

    DESTINO.mkdir(parents=True, exist_ok=True)
    for antiguo in DESTINO.glob("*.json"):
        antiguo.unlink()

    resumen_prov = {}
    for cod, datos in sorted(por_provincia.items()):
        if not datos["pois"] and not datos["incidencias"]:
            continue
        fichero = DESTINO / f"p{cod}.json"
        fichero.write_text(
            json.dumps({"cod": cod, "nombre": PROVINCIAS[cod], **datos},
                       ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        resumen_prov[cod] = {
            "nombre": PROVINCIAS[cod],
            "puntos": len(datos["pois"]),
            "kb": fichero.stat().st_size // 1024,
        }

    (DESTINO / "indice.json").write_text(
        json.dumps({"municipios": municipios_indice, "provincias": resumen_prov},
                   ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    total_kb = sum(p["kb"] for p in resumen_prov.values())
    print(f"\n{len(filas)} puntos -> {len(resumen_prov)} provincias, {total_kb} KB en total")
    print(f"municipios con datos: {len(municipios_indice)} de {len(fichas)}")
    con_ambas = sum(1 for m in municipios_indice.values() if m["demanda"] and m["competencia"])
    print(f"   con demanda y competencia: {con_ambas}")
    print(f"   con una sola capa:         {len(municipios_indice) - con_ambas}")
    if sin_provincia:
        print(f"puntos sin provincia deducible: {sin_provincia}")
    if sin_municipio:
        print(f"puntos sin municipio del catalogo (entran igual en su provincia): {sin_municipio}")

    print("\nlos diez ficheros mas grandes:")
    for cod, p in sorted(resumen_prov.items(), key=lambda kv: -kv[1]["kb"])[:10]:
        print(f"   p{cod} {p['nombre']:24} {p['puntos']:>6} puntos  {p['kb']:>5} KB")


if __name__ == "__main__":
    main()
