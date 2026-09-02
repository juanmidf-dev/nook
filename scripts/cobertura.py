"""
Qué municipios tienen datos y de qué capas.

Existe porque «¿está ya cargado todo?» es la pregunta que más se repite y la
que peor se responde de memoria. La ingesta de notarías es nacional, la de
bancos depende de qué volcados del Banco de España se hayan descargado a mano,
y la de Overture de qué cajas se hayan pedido. Tres coberturas distintas que
solo se pueden saber mirando.

    python scripts/cobertura.py
"""

from __future__ import annotations

import collections
import os
import sys

import requests

PAGINA = 1000


def pide(base: str, cab: dict, ruta: str, params: dict) -> list[dict]:
    """Pagina hasta el final: PostgREST corta a 1.000 filas y no avisa."""
    filas: list[dict] = []
    desde = 0
    while True:
        p = dict(params, limit=str(PAGINA), offset=str(desde))
        r = requests.get(f"{base}/rest/v1/{ruta}", headers=cab, params=p, timeout=120)
        if r.status_code >= 300:
            raise SystemExit(f"Supabase devolvió {r.status_code}: {r.text[:300]}")
        pagina = r.json()
        filas.extend(pagina)
        if len(pagina) < PAGINA:
            return filas
        desde += PAGINA
        if desde > 500_000:
            raise SystemExit(f"{ruta}: demasiadas filas, algo no encaja")


def main() -> None:
    url, secreto = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not secreto:
        raise SystemExit("faltan SUPABASE_URL o SUPABASE_SERVICE_KEY")
    base = url.rstrip("/")
    cab = {"apikey": secreto}
    if secreto.startswith("eyJ"):
        cab["Authorization"] = f"Bearer {secreto}"

    pois = pide(base, cab, "pois", {"select": "tipo,provincia,municipio,lat", "activo": "is.true"})
    municipios = pide(base, cab, "municipios", {"select": "cod_ine"})

    print(f"catálogo de municipios en la base de datos: {len(municipios):,}".replace(",", "."))
    print(f"puntos totales: {len(pois):,}".replace(",", "."))

    DEMANDA = {"banco", "inmobiliaria", "abogados", "gestoria"}

    por_tipo = collections.Counter(p["tipo"] for p in pois)
    print("\n=== puntos por capa ===")
    for t, n in por_tipo.most_common():
        sin_coord = sum(1 for p in pois if p["tipo"] == t and p["lat"] is None)
        print(f"   {t:14} {n:>7,}  ({sin_coord} sin ubicar)".replace(",", "."))

    # Municipios distintos con al menos un punto de cada clase.
    con_notaria = {p["municipio"] for p in pois if p["tipo"] == "notaria" and p["municipio"]}
    con_demanda = {p["municipio"] for p in pois if p["tipo"] in DEMANDA and p["municipio"]}
    print("\n=== municipios nombrados con al menos un punto ===")
    print(f"   con notarías (competencia): {len(con_notaria):,}".replace(",", "."))
    print(f"   con demanda:                {len(con_demanda):,}".replace(",", "."))
    print(f"   con ambas cosas:            {len(con_notaria & con_demanda):,}".replace(",", "."))
    print(f"   solo competencia:           {len(con_notaria - con_demanda):,}".replace(",", "."))

    # Por provincia: es donde se ve el hueco de verdad.
    provs = collections.defaultdict(lambda: {"notaria": 0, "demanda": 0})
    for p in pois:
        if not p.get("provincia"):
            continue
        clave = "notaria" if p["tipo"] == "notaria" else ("demanda" if p["tipo"] in DEMANDA else None)
        if clave:
            provs[p["provincia"]][clave] += 1

    con, sin = [], []
    for prov, c in sorted(provs.items()):
        (con if c["demanda"] else sin).append((prov, c))

    print(f"\n=== provincias CON demanda cargada: {len(con)} ===")
    for prov, c in sorted(con, key=lambda x: -x[1]["demanda"]):
        print(f"   {prov:22} {c['demanda']:>7,} demanda | {c['notaria']:>4} notarías".replace(",", "."))

    print(f"\n=== provincias SOLO con notarías: {len(sin)} ===")
    print("   " + ", ".join(p for p, _ in sin))
    print(f"\n   Suman {sum(c['notaria'] for _, c in sin):,} notarías sin ninguna capa de demanda.".replace(",", "."))


if __name__ == "__main__":
    main()
