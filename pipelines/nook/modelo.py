"""
Modelo de datos común a todas las fuentes.

Cada extractor produce `Poi`. Todo lo que viene después —geocodificación,
deduplicación, escritura— trabaja solo con este tipo, así que añadir una
quinta fuente no obliga a tocar nada más.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Tipo = Literal["notaria", "banco", "inmobiliaria", "abogados", "gestoria"]
Fuente = Literal["notariado", "colegio_notarial", "bde", "overture", "osm", "icab_ica", "manual"]

# Calidad de la posición. Se guarda siempre, porque una notaría situada solo a
# nivel de municipio no sirve para medir competencia a 600 m y hay que poder
# filtrarla sin volver a geocodificar todo.
Calidad = Literal["portal", "via", "municipio", "desconocida"]


@dataclass
class Poi:
    tipo: Tipo
    fuente: Fuente
    fuente_id: str
    nombre: str
    direccion: str | None = None
    cp: str | None = None
    municipio: str | None = None
    cod_ine: str | None = None
    provincia: str | None = None
    telefono: str | None = None
    email: str | None = None
    web: str | None = None
    lat: float | None = None
    lon: float | None = None
    geocode_fuente: str | None = None
    geocode_calidad: Calidad = "desconocida"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def geolocalizado(self) -> bool:
        return self.lat is not None and self.lon is not None

    def para_supabase(self) -> dict[str, Any]:
        """
        El registro completo, con los huecos como `null` explícito.

        No se filtran los campos vacíos, aunque apetezca. PostgREST exige que
        todos los objetos de un mismo lote tengan **las mismas claves**: si una
        notaría lleva correo y la siguiente no, quitar la clave a la segunda
        hace que rechace el lote entero con
        `PGRST102: All object keys must match`. Pasó en la primera ingesta
        real, después de 45 minutos de geocodificación.

        Mandar el null explícito además es lo correcto para el upsert: cada
        ejecución relee el censo completo, así que un campo vacío significa que
        la fuente ya no lo trae, no que no lo sepamos.

        `geom` no se manda: la rellena el trigger `geom_desde_latlon` a partir
        de lat/lon, porque la API REST no puede construir un `geography`.
        """
        d = asdict(self)
        # `extra` es NOT NULL en el esquema, con default '{}'. Un None aquí
        # rompería la inserción en vez de caer al default.
        d["extra"] = d.get("extra") or {}
        return d


def normaliza(texto: str) -> str:
    """Minúsculas, sin acentos y sin puntuación: base para comparar nombres."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"\b(s\.?a\.?u?\.?|s\.?l\.?u?\.?|s\.?c\.?c\.?|sae)\b", " ", t)
    t = re.sub(r"[^a-z0-9ñ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def id_estable(*partes: str) -> str:
    """
    Identificador determinista a partir de los campos que no cambian.

    Hace falta porque la mayoría de estas fuentes no dan un id propio: el
    Banco de España publica un listado sin clave, y la Guía Notarial pagina.
    Sin un id estable, cada ejecución mensual insertaría duplicados en vez de
    actualizar, y el histórico dejaría de servir para nada.
    """
    semilla = "|".join(normaliza(p) for p in partes if p)
    return hashlib.sha1(semilla.encode("utf-8")).hexdigest()[:16]


# Prefijos de tipo de vía que el Banco de España publica abreviados en dos
# letras, y su forma legible. Sin expandirlos, el listado que se entrega al
# notario se lee como un volcado de sistema.
VIAS = {
    "CL": "Calle", "AV": "Avenida", "PZ": "Plaza", "PS": "Paseo", "PG": "Polígono",
    "CR": "Carretera", "TR": "Travesía", "RD": "Ronda", "CM": "Camino",
    "GL": "Glorieta", "PJ": "Pasaje", "UR": "Urbanización", "BO": "Barrio",
    "RB": "Rambla", "PQ": "Parque", "CJ": "Callejón", "LG": "Lugar",
    "CS": "Caserío", "BJ": "Bajada", "SB": "Subida", "CH": "Chalet",
}


# Palabras que ya son un tipo de vía, en castellano y en catalán. Si la
# dirección empieza por una de ellas no se le antepone el prefijo expandido:
# el Banco de España clasifica "Via Massagué" como calle, y "Calle Via
# Massagué" queda mal en un documento que se entrega a un cliente.
YA_ES_VIA = {
    "calle", "avenida", "plaza", "paseo", "ronda", "camino", "carretera",
    "travesia", "travesía", "glorieta", "pasaje", "poligono", "polígono",
    "carrer", "avinguda", "placa", "plaça", "passeig", "rambla", "via",
    "cami", "camí", "ctra", "urbanizacion", "urbanización", "barrio",
}

# Abreviaturas de tipo de vía que aparecen dentro del propio domicilio. Si el
# registro ya trae código de vía delante ("PS PO. PLACA MAJOR") la abreviatura
# sobra y se quita; si no lo trae —los registros con código "ZZ", sin
# clasificar— hay que expandirla, no borrarla: borrarla dejaba "ZZ AV. DE
# MATADEPERA, 46" convertido en "De Matadepera, 46", una dirección que ya no
# se puede geocodificar.
_ABREVIATURAS = {
    "po.": "Paseo", "pº": "Paseo", "ps.": "Paseo",
    "av.": "Avenida", "avda.": "Avenida", "avgda.": "Avenida",
    "c/": "Calle", "cl.": "Calle", "c.": "Calle",
    "ctra.": "Carretera", "crta.": "Carretera",
    "pza.": "Plaza", "pl.": "Plaza",
    "rda.": "Ronda", "rbla.": "Rambla",
}
_ABREV_RE = re.compile(
    r"^(" + "|".join(re.escape(a) for a in sorted(_ABREVIATURAS, key=len, reverse=True)) + r")\s*",
    re.IGNORECASE,
)


# Número final rellenado con ceros: "AV MATADEPERA 0079", "CL RAMBLA, 95 0095".
_NUM_FINAL = re.compile(r"\s+0+(\d*)\s*$")


def _resuelve_numero_final(s: str) -> str:
    """
    El Banco de España cierra el domicilio con el número de portal rellenado
    a cuatro o cinco dígitos, y a veces el número ya aparece antes en el
    campo.

    La primera versión de esto borraba el número final entero. Parecía
    correcto con "PLACA MAJOR, 32 0032" —donde efectivamente sobra— pero
    destruía "CR DE TERRASSA 0335", que no es un código de oficina: es el
    número 335 de la carretera de Terrassa. Media provincia se quedaba con
    direcciones sin portal.
    """
    m = _NUM_FINAL.search(s)
    if not m:
        return s
    numero = m.group(1)
    resto = s[: m.start()].rstrip(" ,.")
    # "... 46. 0" — solo ceros: no hay número que rescatar, es relleno.
    if not numero:
        return resto
    ya_esta = re.search(rf"(?<!\d){re.escape(numero)}(?!\d)", resto) is not None
    return resto if ya_esta else f"{resto} {numero}"


def limpia_direccion(bruto: str | None) -> str | None:
    if not bruto:
        return None
    s = " ".join(str(bruto).split())
    s = _resuelve_numero_final(s)

    prefijo: str | None = None
    m = re.match(r"^([A-Z]{2})\s+(.*)$", s)
    if m and m.group(1) in VIAS:
        prefijo, s = VIAS[m.group(1)], m.group(2)
    elif m and m.group(1) == "ZZ":
        s = m.group(2)

    if s.isupper():
        s = s.title()
    m = _ABREV_RE.match(s)
    if m:
        expandida = _ABREVIATURAS[m.group(1).lower()]
        s = s[m.end() :].strip()
        if prefijo is None:
            prefijo = expandida

    primera = s.split(" ", 1)[0].lower().strip(".,")
    if prefijo and primera not in YA_ES_VIA:
        s = f"{prefijo} {s}"
    return s.strip(" ,") or None


CP_RE = re.compile(r"\b(\d{5})\b")


def extrae_cp(texto: str | None) -> str | None:
    if not texto:
        return None
    m = CP_RE.search(texto)
    if not m:
        return None
    cp = m.group(1)
    # Los códigos postales españoles empiezan por el código de provincia,
    # 01-52. Un "08999" es válido; un "99123" es basura de otro campo.
    return cp if 1 <= int(cp[:2]) <= 52 else None


def colapsa_por_id(pois: list[Poi]) -> tuple[list[Poi], int]:
    """
    Deja un solo registro por `(fuente, fuente_id)`.

    Hace falta porque el upsert de PostgREST se traduce en un `ON CONFLICT`, y
    Postgres rechaza la **sentencia entera** si dos filas del mismo lote
    apuntan a la misma fila destino:

        21000: ON CONFLICT DO UPDATE command cannot affect row a second time

    No es teórico: el volcado del Banco de España trae filas repetidas. El
    Banco Sabadell aparece dos veces en Plaça Sant Roc 20, y Eurodivisas seis
    veces en la T4 de Barajas —seis mostradores en el mismo punto, que para un
    modelo de densidad no son seis focos de demanda—. La ingesta real murió
    ahí después de escribir 3.500 de 4.024 filas.

    Es distinto de `deduplica`, y los dos hacen falta: aquélla une lo que **dos
    fuentes** ven como el mismo sitio, comparando nombre y distancia, y solo
    actúa sobre registros ya geolocalizados. Ésta resuelve que **una misma
    fuente** repita la misma clave, pase lo que pase con las coordenadas.
    """
    vistos: dict[tuple[str, str], Poi] = {}
    salida: list[Poi] = []
    fusionados = 0

    for p in pois:
        clave = (p.fuente, p.fuente_id)
        q = vistos.get(clave)
        if q is None:
            vistos[clave] = p
            salida.append(p)
            continue

        fusionados += 1
        for campo in ("telefono", "email", "web", "direccion", "cp",
                      "cod_ine", "municipio", "provincia"):
            if getattr(q, campo) is None and getattr(p, campo) is not None:
                setattr(q, campo, getattr(p, campo))
        # Las coordenadas se copian juntas o no se copian: media coordenada
        # no es un dato incompleto, es un punto en el meridiano de Greenwich.
        if not q.geolocalizado and p.geolocalizado:
            q.lat, q.lon = p.lat, p.lon
            q.geocode_fuente, q.geocode_calidad = p.geocode_fuente, p.geocode_calidad
        # Se deja constancia: que la fuente repita una clave es información
        # sobre la fuente, no ruido que convenga esconder.
        q.extra["repetidos_en_origen"] = q.extra.get("repetidos_en_origen", 1) + 1

    return salida, fusionados


def deduplica(pois: list[Poi], umbral_m: float = 60.0) -> tuple[list[Poi], int]:
    """
    Une registros que son el mismo sitio visto por dos fuentes.

    Criterio: mismo tipo, nombres normalizados iguales o uno contenido en el
    otro, y a menos de `umbral_m`. No se intenta nada más listo (ni distancia
    de edición ni fuzzy sobre la dirección) porque un falso positivo aquí
    borra un punto de demanda real, y prefiero un duplicado visible a un dato
    desaparecido en silencio.
    """
    salida: list[Poi] = []
    fusionados = 0
    for p in pois:
        if not p.geolocalizado:
            salida.append(p)
            continue
        np_ = normaliza(p.nombre)
        for q in salida:
            if q.tipo != p.tipo or not q.geolocalizado:
                continue
            nq = normaliza(q.nombre)
            if not (np_ == nq or (len(np_) > 6 and len(nq) > 6 and (np_ in nq or nq in np_))):
                continue
            if distancia_m(p.lat, p.lon, q.lat, q.lon) > umbral_m:
                continue
            # Se conserva el registro existente y se completan sus huecos.
            for campo in ("telefono", "email", "web", "direccion", "cp", "cod_ine"):
                if getattr(q, campo) is None and getattr(p, campo) is not None:
                    setattr(q, campo, getattr(p, campo))
            q.extra.setdefault("tambien_en", []).append(f"{p.fuente}:{p.fuente_id}")
            fusionados += 1
            break
        else:
            salida.append(p)
    return salida, fusionados


def distancia_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
