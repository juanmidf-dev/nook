"""
Genera el corte de datos que consume el frontend, leyéndolo de Supabase.

**Por qué un fichero y no una consulta desde el navegador.**

La clave publicable de Supabase viaja en el bundle de JavaScript: cualquiera
que abra el inspector la tiene. Conceder lectura sobre `pois` al rol anónimo
haría que el censo de competencia y los puntos de demanda —el activo que se
vende— se pudieran descargar enteros con una petición. Por eso `schema.sql` no
concede nada a `anon`, y por eso este script existe.

Aquí el servicio lee con la clave secreta, que vive solo en los secretos del
repositorio, y deja un fichero con lo justo para pintar un municipio. El
navegador sigue recalculando en vivo al mover los sliders, que es lo que hace
la herramienta usable, pero no tiene acceso a la base de datos.

El coste es que los datos son tan frescos como la última exportación. Para una
ingesta mensual, sobra.

    python scripts/exportar_municipio.py sabadell
"""

from __future__ import annotations

import json
import math
import os
import pathlib
import sys

import requests

RAIZ = pathlib.Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "src" / "data"

# Municipios que se pueden exportar. El centro y el zoom son los que usa el
# mapa al abrirse; el radio acota qué puntos entran en el corte.
MUNICIPIOS: dict[str, dict] = {
    "sabadell": {
        "codIne": "08187",
        "nombre": "Sabadell",
        "provincia": "Barcelona",
        "centro": [2.1097, 41.5431],
        "zoom": 13,
        "radio_m": 5000,
    },
    "barcelona": {
        "codIne": "08019",
        "nombre": "Barcelona",
        "provincia": "Barcelona",
        "centro": [2.1686, 41.3874],
        "zoom": 12,
        "radio_m": 7000,
    },
    "madrid": {
        "codIne": "28079",
        "nombre": "Madrid",
        "provincia": "Madrid",
        "centro": [-3.7038, 40.4168],
        "zoom": 12,
        "radio_m": 8000,
    },
}


def caja(centro: list[float], radio_m: float) -> tuple[float, float, float, float]:
    lon, lat = centro
    d_lat = radio_m / 111132.95
    d_lon = radio_m / (111320 * math.cos(math.radians(lat)))
    return lat - d_lat, lat + d_lat, lon - d_lon, lon + d_lon


def pide(base: str, cabeceras: dict, ruta: str, params: dict) -> list[dict]:
    r = requests.get(f"{base}/rest/v1/{ruta}", headers=cabeceras, params=params, timeout=90)
    if r.status_code >= 300:
        raise SystemExit(f"Supabase devolvió {r.status_code}: {r.text[:300]}")
    return r.json()


def exporta(clave: str) -> pathlib.Path:
    muni = MUNICIPIOS[clave]
    url = os.environ.get("SUPABASE_URL")
    secreto = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not secreto:
        raise SystemExit("faltan SUPABASE_URL o SUPABASE_SERVICE_KEY")

    base = url.rstrip("/")
    cab = {"apikey": secreto}
    if secreto.startswith("eyJ"):
        cab["Authorization"] = f"Bearer {secreto}"

    lat_min, lat_max, lon_min, lon_max = caja(muni["centro"], muni["radio_m"])

    # Los que sí entran al mapa: por caja, que no depende de que `cod_ine`
    # esté relleno —las notarías y Overture no lo traen—.
    filas = pide(base, cab, "pois", {
        "select": "fuente_id,tipo,nombre,direccion,cp,municipio,telefono,email,web,lat,lon",
        "lat": f"gte.{lat_min}",
        "lon": f"gte.{lon_min}",
        "and": f"(lat.lte.{lat_max},lon.lte.{lon_max})",
        "activo": "is.true",
        "limit": "20000",
    })

    pois = [
        {
            "id": f["fuente_id"],
            "categoria": f["tipo"],
            "nombre": f["nombre"],
            "direccion": f.get("direccion") or "",
            "lat": f["lat"],
            "lon": f["lon"],
            **({"telefono": f["telefono"]} if f.get("telefono") else {}),
            **({"web": f["web"]} if f.get("web") else {}),
        }
        for f in filas
    ]

    # Y los que NO entran, con su motivo. Se declaran en la interfaz en vez de
    # desaparecer: una notaría ausente de la capa de competencia hace que el
    # mapa recomiende el portal de al lado de una notaría ya abierta.
    sin_ubicar = pide(base, cab, "pois", {
        "select": "tipo,nombre,direccion,geocode_fuente,geocode_calidad",
        "municipio": f"eq.{muni['nombre']}",
        "lat": "is.null",
        "limit": "2000",
    })
    incidencias = [
        {
            "categoria": f["tipo"],
            "nombre": f["nombre"],
            "direccion": f.get("direccion") or "",
            # Distinguir los dos casos importa: "no se encontró" se arregla
            # mejorando la consulta, "se encontró mal" buscándola a mano.
            "motivo": (
                f"solo a nivel de {f['geocode_calidad']}"
                if f.get("geocode_fuente")
                else "sin coordenadas"
            ),
        }
        for f in sin_ubicar
    ]

    locales = pide(base, cab, "locales", {
        "select": "fuente_id,titulo,direccion,lat,lon,fuente",
        "lat": f"gte.{lat_min}",
        "lon": f"gte.{lon_min}",
        "and": f"(lat.lte.{lat_max},lon.lte.{lon_max})",
        "limit": "5000",
    })

    salida = DESTINO / f"{clave}.json"
    previo = json.loads(salida.read_text(encoding="utf-8")) if salida.exists() else {}

    datos = {
        "municipio": {k: muni[k] for k in ("codIne", "nombre", "provincia", "centro", "zoom")},
        "pois": pois,
        # Idealista aún no se ingiere, así que la tabla `locales` está vacía.
        # Se conservan los que ya hubiera en el fichero en vez de borrarlos:
        # son datos reales que costaron conseguirse, y sustituirlos por una
        # lista vacía sería perder información sin ganar nada.
        "locales": [
            {"id": l["fuente_id"], "nombre": l.get("titulo") or "Local en alquiler",
             "direccion": l.get("direccion") or "", "fuente": l.get("fuente") or "",
             "lat": l["lat"], "lon": l["lon"]}
            for l in locales
        ] or previo.get("locales", []),
        "incidencias": incidencias,
    }

    salida.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")

    from collections import Counter
    print(f"{clave}: {len(pois)} puntos, {len(datos['locales'])} locales, "
          f"{len(incidencias)} incidencias")
    print("  por categoría:", dict(Counter(p["categoria"] for p in pois)))
    print("  ->", salida)
    return salida


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in MUNICIPIOS:
        raise SystemExit(f"uso: exportar_municipio.py <{'|'.join(MUNICIPIOS)}>")
    exporta(sys.argv[1])
