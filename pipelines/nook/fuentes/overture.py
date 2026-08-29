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
#
# Pero fijarlo tiene un coste que hay que conocer: **Overture borra de S3 las
# releases antiguas**. El 29/08/2026 solo quedaban dos publicadas,
# `2026-07-22.0` y `2026-08-19.0`; la que estaba fijada aquí era de un año
# antes y ya no existía, así que la ingesta moría con un `IO Error: No files
# found`. Al menos falla en alto y en cuatro segundos, no en silencio.
#
# Para comprobar qué hay publicado ahora mismo, sin credenciales:
#   https://overturemaps-us-west-2.s3.amazonaws.com/?list-type=2&prefix=release/&delimiter=/
RELEASE = "2026-08-19.0"
BASE = f"s3://overturemaps-us-west-2/release/{RELEASE}/theme=places/type=place/*"

# Categorías de Overture que interesan, por tipo de Nook. Se comparan tanto
# contra la categoría principal como contra las alternativas, porque muchos
# despachos se clasifican como "professional_services" con "lawyer" en la
# lista secundaria.
# Los códigos salen de la taxonomía oficial de Overture (2.117 categorías,
# `overture_categories.csv` del repositorio de esquema), no de suponer cómo se
# llamarían. La versión anterior de este diccionario tenía seis nombres
# inventados que no casaban con nada: `bank` —el código real es `banks`—,
# `real_estate_agency`, `law_firm`, `attorney`, `solicitor` y
# `banking_and_finance`. Una categoría que no existe no da error: simplemente
# no coincide nunca, y la capa sale más pobre de lo que debería sin que nada
# lo anuncie.
CATEGORIAS: dict[Tipo, set[str]] = {
    # Subárbol `real_estate`, pero solo lo que intermedia operaciones. Quedan
    # fuera `apartments`, `condominium`, `holiday_park`, `university_housing`
    # y compañía: son inmuebles, no negocios que generen trabajo notarial.
    "inmobiliaria": {
        "real_estate", "real_estate_agent", "apartment_agent",
        "real_estate_service", "commercial_real_estate", "property_management",
        "mortgage_broker", "escrow_services", "builders", "home_developer",
        "estate_liquidation",
    },
    # Subárbol `lawyer` completo más `legal_services`. Se incluyen las
    # especialidades (`tax_law`, `real_estate_law`, `estate_planning_law`...)
    # porque en Overture un despacho especializado lleva la especialidad como
    # categoría principal, no `lawyer`: sin ellas se perdían justo los que más
    # trabajo notarial generan. Algunas son de EE. UU. y en España no
    # aparecerán; no molestan.
    "abogados": {
        "lawyer", "legal_services", "paralegal_services",
        "appellate_practice_lawyers", "bankruptcy_law", "business_law",
        "civil_rights_lawyers", "contract_law", "criminal_defense_law",
        "disability_law", "divorce_and_family_law", "dui_law",
        "employment_law", "entertainment_law", "estate_planning_law",
        "general_litigation", "immigration_law", "ip_and_internet_law",
        "medical_law", "personal_injury_law", "real_estate_law",
        "social_security_law", "tax_law", "traffic_ticketing_law",
        "wills_trusts_and_probate", "workers_compensation_law",
        "court_reporter", "process_servers",
    },
    # Subárbol `bank_credit_union`. El Banco de España sigue siendo la fuente
    # buena para esta capa —es registro oficial y trae el código INE—; Overture
    # solo la completa donde el volcado del BdE no llegue.
    "banco": {"bank_credit_union", "banks", "credit_union"},
    # Gestorías administrativas y asesorías fiscales y contables. En España
    # canalizan constitución y modificación de sociedades, poderes,
    # compraventa de vehículos y tramitación de herencias: un polígono con
    # seis gestorías genera más actos notariales que seis inmobiliarias.
    #
    # `tax_office` queda fuera aunque el nombre invite: su rama en la
    # taxonomía es `public_service_and_government`, o sea, la Agencia
    # Tributaria. Eso no es un despacho que derive trabajo a una notaría.
    "gestoria": {
        "accountant", "bookkeeper", "tax_services",
        "payroll_services", "business_consulting",
    },
}

# `notary_public` NO va en abogados, aunque sea lo primero que apetece.
#
# Una notaría española catalogada en Overture entraría entonces como demanda,
# sumando peso justo encima de donde ya hay una notaría instalada: el error
# que el modelo entero existe para evitar. Y ademas duplicaria un punto que ya
# tenemos de la Guia Notarial, que es censo oficial y completo.
#
# Se descarta en vez de mapearse a `notaria` precisamente por eso: la
# competencia ya la tenemos bien, y meterla por una segunda via solo añade
# duplicados que habria que deduplicar.
CATEGORIAS_EXCLUIDAS = {"notary_public"}

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


# Cómo leer la columna `geometry`. Overture la publica como WKB, pero DuckDB
# con la extensión spatial cargada reconoce los metadatos GeoParquet del
# fichero y puede devolverla ya convertida a GEOMETRY. En ese caso
# `ST_GeomFromWKB(geometry)` no encaja con ninguna sobrecarga y la consulta
# revienta entera. Cuál de las dos toca no se puede decidir a priori: depende
# de la versión de la extensión, que se descarga en tiempo de ejecución y no
# está fijada como sí lo está la de duckdb.
GEOM_WKB = "ST_GeomFromWKB(geometry)"
GEOM_NATIVA = "geometry"


def expresion_geometria(con, origen: str) -> str:
    """
    Pregunta al propio DuckDB de qué tipo le llega la columna, en vez de
    suponerlo. `DESCRIBE` solo lee metadatos del parquet: no descarga datos,
    así que sale gratis incluso contra S3.
    """
    try:
        filas = con.execute(
            f"DESCRIBE SELECT geometry FROM read_parquet('{origen}') LIMIT 0"
        ).fetchall()
    except Exception as e:  # noqa: BLE001
        log.warning("no se pudo describir la geometría de %s (%s); se asume WKB", origen, e)
        return GEOM_WKB
    tipo = filas[0][1].upper() if filas else ""
    log.info("columna geometry de tipo %s", tipo or "desconocido")
    return GEOM_NATIVA if "GEOMETRY" in tipo else GEOM_WKB


def consulta_sql(b: BBox, geometria: str = GEOM_WKB) -> str:
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
        -- El correo es parte del entregable de 199 euros: el notario compra
        -- una lista de puntos de demanda con la que poder contactar, y una
        -- lista sin forma de contactar vale bastante menos. Overture lo
        -- publica en `emails` y hasta ahora se estaba tirando.
        emails[1]                                       AS email,
        ST_Y({geometria})                               AS lat,
        ST_X({geometria})                               AS lon
    FROM read_parquet('{{origen}}', filename=true, hive_partitioning=1)
    WHERE bbox.ymin BETWEEN {b.min_lat} AND {b.max_lat}
      AND bbox.xmin BETWEEN {b.min_lon} AND {b.max_lon}
      AND confidence >= {CONFIANZA_MINIMA}
      AND names.primary IS NOT NULL
    """


def clasifica(categoria: str | None, alternativas: Iterable[str] | None) -> Tipo | None:
    """Traduce la taxonomía de Overture a los tipos de Nook."""
    candidatas = {c for c in [categoria, *(alternativas or [])] if c}
    # La exclusión va antes que nada: una notaría catalogada en Overture suele
    # llevar también `lawyer` entre sus categorías, así que sacarla del
    # conjunto de abogados no basta para que deje de contar como demanda.
    if candidatas & CATEGORIAS_EXCLUIDAS:
        return None
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
        email=fila.get("email"),
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

    geometria = expresion_geometria(con, origen)

    pois: list[Poi] = []
    for b in cajas or ESPANA:
        sql = consulta_sql(b, geometria).replace("{origen}", origen)
        log.info("consultando Overture en %s", b)
        filas = con.execute(sql).fetchall()
        columnas = [d[0] for d in con.description]
        for f in filas:
            poi = fila_a_poi(dict(zip(columnas, f)))
            if poi is not None:
                pois.append(poi)
        log.info("  %d filas, %d útiles acumuladas", len(filas), len(pois))
    return pois
