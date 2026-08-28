"""
Convierte los Excel de `Raw data/xlsx` en el JSON que consume la aplicación.

Uso:
    python scripts/convertir_raw.py "ruta/a/Raw data/xlsx"

Es un puente temporal: cuando el pipeline de ingesta escriba en Supabase, la
aplicación leerá de allí y este script desaparece. Mientras tanto conviene que
la conversión sea reproducible y no un pegado manual, para poder repetirla cada
vez que se actualicen los volcados.

Requiere: pandas, openpyxl.
"""

import json
import pathlib
import re
import sys

import pandas as pd

DESTINO = pathlib.Path(__file__).resolve().parents[1] / "src/data/sabadell.json"

MUNICIPIO = {
    "codIne": "08187",
    "nombre": "Sabadell",
    "provincia": "Barcelona",
    "centro": [2.1097, 41.5431],
    "zoom": 13,
}

# El término municipal de Sabadell mide unos 37 km2; 6 km desde el centro lo
# cubren entero con margen. Todo lo que caiga fuera es un error del volcado,
# no un punto de demanda: en los Excel hay agencias de Barcelona, Manresa e
# incluso Sitges anotadas como "(cerca)". Dejarlas dentro no solo mete ruido,
# sino que estira la rejilla de análisis a decenas de kilómetros y hace que
# un punto aislado en mitad del campo puntúe 100.
RADIO_MUNICIPIO_M = 6000


def distancia_m(lat1, lon1, lat2, lon2) -> float:
    import math

    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def fuera_del_municipio(lat, lon) -> float | None:
    """Devuelve la distancia al centro si el punto está fuera del radio."""
    d = distancia_m(lat, lon, MUNICIPIO["centro"][1], MUNICIPIO["centro"][0])
    return d if d > RADIO_MUNICIPIO_M else None


def limpia_direccion(s: str) -> str:
    """
    Normaliza las direcciones.

    Los volcados del Banco de España traen el tipo de vía abreviado en dos
    letras al principio ("ZZ", "PS", "CL"), el número de oficina repetido al
    final ("0032") y el municipio, que aquí sobra porque todo el fichero es del
    mismo municipio. Sin limpiarlo, el listado que se entrega al notario se lee
    como un volcado de sistema en vez de como un documento.
    """
    s = str(s).strip()
    s = re.sub(r"^(ZZ|PS|CL|AV|PZ|CR|TR|PG|RD)\s+", "", s)
    s = re.sub(r"\s+0\d{3}\b", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"\s*,?\s*SABADELL\s*$", "", s, flags=re.I)
    s = s.strip(" ,")
    if s and s.upper() == s and any(c.isalpha() for c in s):
        s = s.title()
        s = re.sub(r"\bPo\.\b", "Passeig", s)
        s = re.sub(r"\bPlaca\b", "Plaça", s)
    return s


def titulo(s: str) -> str:
    s = str(s).strip()
    if s.isupper():
        s = s.title()
        for w in ["S.A.E.", "S.A.", "S.L.", "B.B.V.A."]:
            s = s.replace(w.title(), w)
    return s


def carga(ruta: pathlib.Path, categoria: str, prefijo: str, normalizar_nombre=False):
    df = pd.read_excel(ruta)
    filas, incidencias = [], []
    for i, r in df.iterrows():
        nombre = str(r["Name"]).strip()
        entidad = None
        m = re.match(r"^(.*?)\s*\((\d{4})\)\s*$", nombre)
        if m:
            nombre, entidad = m.group(1).strip(), m.group(2)
        if normalizar_nombre:
            nombre = titulo(nombre)

        # Sin coordenadas no se puede pintar ni medir distancias. No se inventa
        # una posición: se aparta y se declara, porque una notaría que falta en
        # la capa de competencia hace que el mapa recomiende justo el portal de
        # al lado de una notaría existente.
        if pd.isna(r["Latitude"]) or pd.isna(r["Longitude"]):
            incidencias.append(
                {
                    "categoria": categoria,
                    "nombre": nombre,
                    "direccion": limpia_direccion(r["Address"]),
                    "motivo": "sin coordenadas",
                }
            )
            continue

        lejos = fuera_del_municipio(float(r["Latitude"]), float(r["Longitude"]))
        if lejos is not None:
            incidencias.append(
                {
                    "categoria": categoria,
                    "nombre": nombre,
                    "direccion": limpia_direccion(r["Address"]),
                    "motivo": f"fuera del municipio ({lejos / 1000:.0f} km del centro)",
                }
            )
            continue

        fila = {
            "id": f"{prefijo}-{i + 1}",
            "categoria": categoria,
            "nombre": nombre,
            "direccion": limpia_direccion(r["Address"]),
            "lat": round(float(r["Latitude"]), 6),
            "lon": round(float(r["Longitude"]), 6),
        }
        if entidad:
            fila["entidad"] = entidad
        filas.append(fila)
    return filas, incidencias


def main(base: pathlib.Path) -> None:
    pois, incidencias = [], []
    for fichero, categoria, prefijo, norm in [
        ("Notarias.xlsx", "notaria", "not", False),
        ("Bank branches.xlsx", "banco", "ban", True),
        ("APIs.xlsx", "inmobiliaria", "inm", False),
    ]:
        f, inc = carga(base / fichero, categoria, prefijo, norm)
        pois += f
        incidencias += inc

    locales = []
    for i, r in pd.read_excel(base / "Idealista.xlsx").iterrows():
        if pd.isna(r["Latitude"]) or pd.isna(r["Longitude"]):
            continue
        if fuera_del_municipio(float(r["Latitude"]), float(r["Longitude"])) is not None:
            continue
        locales.append(
            {
                "id": f"loc-{i + 1}",
                "nombre": "Local en alquiler",
                "direccion": limpia_direccion(r["Address"]),
                "fuente": "Idealista",
                "lat": round(float(r["Latitude"]), 6),
                "lon": round(float(r["Longitude"]), 6),
            }
        )

    DESTINO.write_text(
        json.dumps(
            {"municipio": MUNICIPIO, "pois": pois, "locales": locales, "incidencias": incidencias},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    from collections import Counter

    print(Counter(p["categoria"] for p in pois), "locales:", len(locales))
    for inc in incidencias:
        print("INCIDENCIA:", inc)
    print("->", DESTINO)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("uso: python scripts/convertir_raw.py '<carpeta Raw data/xlsx>'")
    main(pathlib.Path(sys.argv[1]))
