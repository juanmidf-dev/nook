"""
Inmobiliarias y despachos de abogados desde Overture Maps Places.

Por qué Overture y no Google Places: los términos de Google prohíben
almacenar los resultados más de 30 días salvo el `place_id`, así que con
Google no se puede construir una base de datos propia — que es justamente el
activo del negocio. Overture publica bajo licencia abierta, permite almacenar
y redistribuir, y se descarga entero como parquet desde S3 sin clave ni cuota.

La descarga se hace con DuckDB leyendo el parquet remoto y filtrando por
bounding box en el propio motor: solo bajan las filas de la zona pedida, no
los cientos de gigas del dataset mundial.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

from ..modelo import Poi, Tipo, extrae_cp, id_estable, limpia_direccion

log = logging.getLogger("nook.overture")

# El `release` se fija a propósito en vez de usar "latest": una ingesta
# mensual que cambia de versión de dataset sin avisar mueve puntos de sitio y
# hace imposible explicar por qué el mapa de un cliente cambió de un mes a
# otro. Se sube de versión a mano, viendo el diff.
RELEASE = "2025-08-20.0"
BASE = f"s3://overturemaps-us-west-2/release/{RELEASE}/theme=places/type=place/*"

# Categorías de Overture que interesan, por tipo de Nook. Se comparan tanto
# contra la categoría principal como contra las alternativas, porque muchos
# despachos se clasifican como "professional_services" con "lawyer" en la
# lista secundaria.
CATEGORIAS: dict[Tipo, set[str]] = {
    "inmobiliaria": {
        "real_estate_agency", "real_estate_agent", "real_estate",
        "real_estate_service", "property_management",
    },
    "abogados": {
        "lawyer", "law_firm", "legal_services", "attorney", "notary_public",
        "solicitor", "legal",
    },
    "banco": {"bank", "banking_and_finance", "credit_union"},
}

# Overture arrastra registros de baja confianza procedentes de fuentes
# automáticas. Por debajo de este umbral hay bastante ruido —negocios
# cerrados, duplicados, puntos sin nombre— y para lo que vendemos importa más
# la precisión que el volumen.
CONFIANZA_MINIMA = 0.5


@dataclass
class BBox:
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    @staticmethod
    def de_centro(lat: float, lon: float, radio_m: float) -> "BBox":
        import math

        d_lat = radio_m / 111132.95
        d_lon = radio_m / (111320 * math.cos(math.radians(lat)))
        return BBox(lat - d_lat, lon - d_lon, lat + d_lat, lon + d_lon)


# España peninsular + Baleares + Canarias, en dos cajas: una sola caja que las
# englobara arrastraría medio Atlántico y Marruecos.
ESPANA = [
    BBox(35.9, -9.5, 43.9, 4.4),    # peninsular y Baleares
    BBox(27.5, -18.2, 29.5, -13.3),  # Canarias
]


def consulta_sql(b: BBox) -> str:
    """
    SQL de extracción. Separado de la ejecución para poder probarlo contra un
    parquet local, que es la única forma de validar la transformación sin
    depender de la red.
    """
    return f"""
    SELECT
        id,
        names.primary                                   AS nombre,
        categories.primary                              AS categoria,
        categories.alternate                            AS categorias_alt,
        confidence                                      AS confianza,
        addresses[1].freeform                           AS direccion,
        addresses[1].postcode                           AS cp,
        addresses[1].locality                           AS municipio,
        addresses[1].region                             AS region,
        websites[1]                                     AS web,
        phones[1]                                       AS telefono,
        ST_Y(ST_GeomFromWKB(geometry))                  AS lat,
        ST_X(ST_GeomFromWKB(geometry))                  AS lon
    FROM read_parquet('{{origen}}', filename=true, hive_partitioning=1)
    WHERE bbox.ymin BETWEEN {b.min_lat} AND {b.max_lat}
      AND bbox.xmin BETWEEN {b.min_lon} AND {b.max_lon}
      AND confidence >= {CONFIANZA_MINIMA}
      AND names.primary IS NOT NULL
    """


def clasifica(categoria: str | None, alternativas: Iterable[str] | None) -> Tipo | None:
    """Traduce la taxonomía de Overture a los tipos de Nook."""
    candidatas = {c for c in [categoria, *(alternativas or [])] if c}
    for tipo, validas in CATEGORIAS.items():
        if candidatas & validas:
            return tipo
    return None


def fila_a_poi(fila: dict[str, Any]) -> Poi | None:
    """
    Transforma una fila del parquet en un Poi.

    Devuelve None si la fila no interesa o no es utilizable. Es una función
    pura para poder probarla con filas construidas a mano.
    """
    tipo = clasifica(fila.get("categoria"), fila.get("categorias_alt"))
    if tipo is None:
        return None
    lat, lon = fila.get("lat"), fila.get("lon")
    if lat is None or lon is None:
        return None

    nombre = (fila.get("nombre") or "").strip()
    if not nombre:
        return None

    direccion = limpia_direccion(fila.get("direccion"))
    return Poi(
        tipo=tipo,
        fuente="overture",
        # Overture tiene id propio y estable entre releases; se usa ese, y se
        # cae al hash solo si faltara.
        fuente_id=str(fila.get("id") or id_estable(nombre, direccion or "", f"{lat:.5f}", f"{lon:.5f}")),
        nombre=nombre,
        direccion=direccion,
        cp=fila.get("cp") or extrae_cp(fila.get("direccion")),
        municipio=fila.get("municipio"),
        provincia=fila.get("region"),
        telefono=fila.get("telefono"),
        web=fila.get("web"),
        lat=float(lat),
        lon=float(lon),
        geocode_fuente="overture",
        # Overture da la posición del propio establecimiento, no una
        # dirección geocodificada: es lo más preciso que manejamos.
        geocode_calidad="portal",
        extra={"confianza": fila.get("confianza"), "categoria_overture": fila.get("categoria")},
    )


def extrae(cajas: list[BBox] | None = None, origen: str = BASE) -> list[Poi]:
    """Ejecuta la consulta contra Overture y devuelve los Poi ya clasificados."""
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2'; SET s3_access_key_id=''; SET s3_secret_access_key='';")

    pois: list[Poi] = []
    for b in cajas or ESPANA:
        sql = consulta_sql(b).replace("{origen}", origen)
        log.info("consultando Overture en %s", b)
        filas = con.execute(sql).fetchall()
        columnas = [d[0] for d in con.description]
        for f in filas:
            poi = fila_a_poi(dict(zip(columnas, f)))
            if poi is not None:
                pois.append(poi)
        log.info("  %d filas, %d útiles acumuladas", len(filas), len(pois))
    return pois
