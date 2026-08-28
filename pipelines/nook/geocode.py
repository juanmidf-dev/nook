"""
Geocodificación con CartoCiudad (IGN).

Se usa CartoCiudad y no Nominatim ni Google porque es el geocodificador
oficial español: se alimenta del callejero del INE y del Catastro, entiende
las abreviaturas de vía que traen los ficheros oficiales, es gratuito y no
tiene restricción de almacenamiento. Nominatim queda como red de seguridad
cuando CartoCiudad no encuentra la dirección.

Lo importante de este módulo no es acertar siempre, sino **declarar con qué
precisión ha acertado**. Una notaría situada solo a nivel de municipio no
sirve para medir competencia a 600 metros, y tiene que poder filtrarse sin
volver a geocodificar España entera.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .http import Cliente
from .modelo import Calidad

log = logging.getLogger("nook.geocode")

CARTOCIUDAD = "https://www.cartociudad.es/geocoder/api/geocoder/findJsonp"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

# CartoCiudad devuelve el tipo de resultado en `type`. Se traduce a las tres
# calidades que le importan al modelo de calor.
CALIDAD_POR_TIPO: dict[str, Calidad] = {
    "portal": "portal",
    "Portal": "portal",
    "punto_kilometrico": "via",
    "callejero": "via",
    "Calle": "via",
    "carretera": "via",
    "municipio": "municipio",
    "Municipio": "municipio",
    "poblacion": "municipio",
    "toponimo": "municipio",
}


@dataclass
class Resultado:
    lat: float
    lon: float
    calidad: Calidad
    fuente: str
    etiqueta: str | None = None


def _calidad(tipo: str | None, estado: object) -> Calidad:
    if tipo and tipo in CALIDAD_POR_TIPO:
        return CALIDAD_POR_TIPO[tipo]
    # `state` 1 en CartoCiudad significa coincidencia exacta de portal.
    if str(estado) == "1":
        return "portal"
    return "desconocida"


def interpreta_cartociudad(datos: object) -> Resultado | None:
    """
    Extrae el mejor candidato de una respuesta de CartoCiudad.

    Aislado de la red a propósito: es la parte que se rompe cuando el
    organismo cambia el formato, y así se puede probar con respuestas
    guardadas sin depender de que el servicio esté levantado.
    """
    if datos is None:
        return None
    candidatos = datos if isinstance(datos, list) else [datos]
    for c in candidatos:
        if not isinstance(c, dict):
            continue
        lat, lon = c.get("lat"), c.get("lng")
        if lat is None or lon is None:
            continue
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        # España peninsular, Baleares y Canarias. Un resultado fuera de esta
        # caja es un error del geocodificador, no una dirección rara.
        if not (27.0 <= lat <= 44.0 and -19.0 <= lon <= 5.0):
            log.warning("descartada coordenada fuera de España: %s, %s", lat, lon)
            continue
        return Resultado(
            lat=lat,
            lon=lon,
            calidad=_calidad(c.get("type"), c.get("state")),
            fuente="cartociudad",
            etiqueta=c.get("address") or c.get("name"),
        )
    return None


def interpreta_nominatim(datos: object) -> Resultado | None:
    if not isinstance(datos, list) or not datos:
        return None
    c = datos[0]
    try:
        lat, lon = float(c["lat"]), float(c["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (27.0 <= lat <= 44.0 and -19.0 <= lon <= 5.0):
        return None
    clase = c.get("class")
    calidad: Calidad = "portal" if clase in ("place", "building") else "via"
    return Resultado(lat, lon, calidad, "nominatim", c.get("display_name"))


class Geocodificador:
    def __init__(self, cliente: Cliente | None = None, usar_nominatim: bool = True) -> None:
        # Un segundo entre peticiones es lo que pide la política de uso de
        # Nominatim, y CartoCiudad lo tolera de sobra.
        self.cliente = cliente or Cliente(pausa_s=1.0)
        self.usar_nominatim = usar_nominatim
        self.cache: dict[str, Resultado | None] = {}

    def geocodifica(self, direccion: str, municipio: str | None = None,
                    provincia: str | None = None) -> Resultado | None:
        consulta = ", ".join(x for x in (direccion, municipio, provincia, "España") if x)
        if consulta in self.cache:
            return self.cache[consulta]

        r = interpreta_cartociudad(
            self.cliente.json(CARTOCIUDAD, params={"q": consulta, "no_process": "false"})
        )
        if r is None and self.usar_nominatim:
            r = interpreta_nominatim(
                self.cliente.json(
                    NOMINATIM,
                    params={"q": consulta, "format": "json", "limit": 1, "countrycodes": "es"},
                )
            )
        if r is None:
            log.warning("sin geocodificar: %s", consulta)
        self.cache[consulta] = r
        return r
