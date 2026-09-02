"""
Construye el catálogo de municipios de España desde el INE.

Produce dos cosas:

- `src/data/municipios.json`, el árbol comunidad -> provincia -> municipio que
  alimenta los desplegables del mapa.
- Opcionalmente, el volcado a la tabla `municipios` de Supabase, que lleva
  vacía desde el principio y es el motivo por el que `pois.cod_ine` no tiene
  clave ajena. Con ella cargada se puede recuperar esa integridad.

Fuente: «Relación de municipios y códigos por comunidades autónomas y
provincias» del INE, que es el registro oficial y se publica cada 1 de enero.

    python scripts/catalogo_municipios.py            # solo el JSON
    python scripts/catalogo_municipios.py --supabase # además, a la base de datos
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import sys

import requests

RAIZ = pathlib.Path(__file__).resolve().parents[1]
SALIDA = RAIZ / "src" / "data" / "municipios.json"

# El diccionario del INE cambia de nombre cada año. Se fija el año en vez de
# apuntar a "el último": un catálogo que cambia solo entre dos ejecuciones
# haría que un municipio apareciera o desapareciera del desplegable sin que
# nadie hubiera tocado nada.
ANIO = 26
URL = f"https://www.ine.es/daco/daco42/codmun/diccionario{ANIO}.xlsx"

# El fichero del INE trae los códigos, no los nombres de comunidad y
# provincia. Son tablas oficiales y fijas, así que van aquí literales.
CCAA = {
    "01": "Andalucía", "02": "Aragón", "03": "Asturias, Principado de",
    "04": "Balears, Illes", "05": "Canarias", "06": "Cantabria",
    "07": "Castilla y León", "08": "Castilla - La Mancha", "09": "Cataluña",
    "10": "Comunitat Valenciana", "11": "Extremadura", "12": "Galicia",
    "13": "Madrid, Comunidad de", "14": "Murcia, Región de",
    "15": "Navarra, Comunidad Foral de", "16": "País Vasco",
    "17": "Rioja, La", "18": "Ceuta", "19": "Melilla",
}

# Tabla única del proyecto: la de `pipelines/nook/geografia.py`, que es la que
# usa el pipeline para deducir la provincia del código postal. Duplicarla aquí
# haría que un día dejaran de coincidir.
sys.path.insert(0, str(RAIZ / "pipelines"))
from nook.geografia import PROVINCIAS  # noqa: E402



def descarga() -> list[dict]:
    import openpyxl

    r = requests.get(URL, timeout=180, headers={
        "User-Agent": "NookBot/1.0 (+https://github.com/juanmidf-dev/nook)",
    })
    if r.status_code != 200:
        raise SystemExit(f"el INE devolvió {r.status_code} en {URL}")

    hoja = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True).worksheets[0]
    filas = []
    for fila in hoja.iter_rows(values_only=True):
        # La primera fila es el título y la segunda la cabecera.
        if not fila or fila[0] in (None, "CODAUTO") or not str(fila[0]).isdigit():
            continue
        codauto, cpro, cmun, _dc, nombre = fila[:5]
        filas.append({
            "cod_ine": f"{cpro}{cmun}",
            "nombre": str(nombre).strip(),
            "cod_provincia": str(cpro),
            "provincia": PROVINCIAS.get(str(cpro), "?"),
            "cod_ccaa": str(codauto),
            "ccaa": CCAA.get(str(codauto), "?"),
        })
    return filas


def arbol(filas: list[dict]) -> dict:
    """
    Comunidad -> provincia -> municipios, ordenado alfabéticamente.

    Se guarda como listas y no como diccionarios anidados con nombres largos
    repetidos: el fichero lo descarga el navegador, y con 8.000 municipios la
    diferencia entre una estructura y otra son cientos de kilobytes.
    """
    por_ccaa: dict[str, dict] = {}
    for f in filas:
        c = por_ccaa.setdefault(f["cod_ccaa"], {"nombre": f["ccaa"], "provincias": {}})
        p = c["provincias"].setdefault(f["cod_provincia"], {"nombre": f["provincia"], "municipios": []})
        p["municipios"].append([f["cod_ine"], f["nombre"]])

    return {
        "fuente": f"INE, relación de municipios a 1 de enero de 20{ANIO}",
        "ccaa": [
            {
                "cod": cod,
                "nombre": c["nombre"],
                "provincias": [
                    {
                        "cod": pcod,
                        "nombre": p["nombre"],
                        "municipios": sorted(p["municipios"], key=lambda m: m[1]),
                    }
                    for pcod, p in sorted(c["provincias"].items())
                ],
            }
            for cod, c in sorted(por_ccaa.items(), key=lambda kv: kv[1]["nombre"])
        ],
    }


def a_supabase(filas: list[dict]) -> None:
    url, secreto = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not secreto:
        raise SystemExit("faltan SUPABASE_URL o SUPABASE_SERVICE_KEY")
    cab = {"apikey": secreto, "Content-Type": "application/json",
           "Prefer": "resolution=merge-duplicates,return=minimal"}
    if secreto.startswith("eyJ"):
        cab["Authorization"] = f"Bearer {secreto}"

    base = url.rstrip("/") + "/rest/v1/municipios"
    lote = 500
    for i in range(0, len(filas), lote):
        trozo = [
            {k: f[k] for k in ("cod_ine", "nombre", "provincia", "cod_provincia", "ccaa")}
            for f in filas[i : i + lote]
        ]
        r = requests.post(base, params={"on_conflict": "cod_ine"}, headers=cab,
                          data=json.dumps(trozo, ensure_ascii=False).encode("utf-8"),
                          timeout=120)
        if r.status_code >= 300:
            raise SystemExit(f"Supabase devolvió {r.status_code}: {r.text[:300]}")
        print(f"  escritos {min(i + lote, len(filas))}/{len(filas)}")


if __name__ == "__main__":
    filas = descarga()
    if len(filas) < 8000:
        # España tiene algo más de 8.100 municipios. Muchos menos significa
        # que el formato del fichero cambió, no que hayan desaparecido.
        raise SystemExit(f"solo {len(filas)} municipios; el fichero del INE no encaja")

    SALIDA.write_text(
        json.dumps(arbol(filas), ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"{len(filas)} municipios -> {SALIDA} ({SALIDA.stat().st_size // 1024} KB)")

    if "--supabase" in sys.argv:
        print("volcando a Supabase...")
        a_supabase(filas)
