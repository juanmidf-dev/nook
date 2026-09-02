"""
Normalización geográfica.

Existe porque el campo `provincia` que traen las fuentes no vale para agrupar.
Overture lo publica como texto libre y en un mismo volcado aparecen «Tarragona»,
«Provincia de Tarragona» y «tarragona»; Cataluña sale como «Catalonia»,
«Catalunya», «CT» y «Cataluña»; y hay barrios de Madrid —«Arganzuela -
Imperial»— metidos en el campo de provincia.

Con eso, cualquier recuento por provincia sale fragmentado, y cruzar dos
fuentes por nombre de municipio pierde los que se escriben distinto: la Guía
Notarial dice «L'Hospitalet de Llobregat» donde el Banco de España dice
«Hospitalet De Llobregat(L')».

La salida es el código postal. En España **los dos primeros dígitos del código
postal son el código de provincia**, sin excepciones, así que la provincia se
deriva en vez de creerse lo que venga escrito.
"""

from __future__ import annotations

import re

# Nombres canónicos, los del INE. Es la única tabla de provincias del
# proyecto: `scripts/catalogo_municipios.py` importa esta misma.
PROVINCIAS: dict[str, str] = {
    "01": "Araba/Álava", "02": "Albacete", "03": "Alicante/Alacant",
    "04": "Almería", "05": "Ávila", "06": "Badajoz", "07": "Balears, Illes",
    "08": "Barcelona", "09": "Burgos", "10": "Cáceres", "11": "Cádiz",
    "12": "Castellón/Castelló", "13": "Ciudad Real", "14": "Córdoba",
    "15": "Coruña, A", "16": "Cuenca", "17": "Girona", "18": "Granada",
    "19": "Guadalajara", "20": "Gipuzkoa", "21": "Huelva", "22": "Huesca",
    "23": "Jaén", "24": "León", "25": "Lleida", "26": "Rioja, La",
    "27": "Lugo", "28": "Madrid", "29": "Málaga", "30": "Murcia",
    "31": "Navarra", "32": "Ourense", "33": "Asturias", "34": "Palencia",
    "35": "Palmas, Las", "36": "Pontevedra", "37": "Salamanca",
    "38": "Santa Cruz de Tenerife", "39": "Cantabria", "40": "Segovia",
    "41": "Sevilla", "42": "Soria", "43": "Tarragona", "44": "Teruel",
    "45": "Toledo", "46": "Valencia/València", "47": "Valladolid",
    "48": "Bizkaia", "49": "Zamora", "50": "Zaragoza", "51": "Ceuta",
    "52": "Melilla",
}

_CP = re.compile(r"^\s*(\d{5})\s*$")


def cod_provincia_desde_cp(cp: str | None) -> str | None:
    """
    Los dos primeros dígitos de un código postal español.

    Devuelve None si el código no es de cinco cifras o si los dos primeros no
    corresponden a ninguna provincia: hay ficheros que traen códigos postales
    extranjeros o truncados, y prefiero no asignar provincia a inventarla.
    """
    if not cp:
        return None
    m = _CP.match(str(cp))
    if not m:
        return None
    codigo = m.group(1)[:2]
    return codigo if codigo in PROVINCIAS else None


def provincia_desde_cp(cp: str | None) -> str | None:
    """El nombre canónico de la provincia, deducido del código postal."""
    codigo = cod_provincia_desde_cp(cp)
    return PROVINCIAS[codigo] if codigo else None


def normaliza(pois: list) -> tuple[int, int]:
    """
    Reescribe `provincia` con el nombre canónico cuando el código postal lo
    permite, y completa los dos primeros dígitos de `cod_ine` si falta.

    Lo que no se puede deducir se deja como está: un código postal no
    identifica un municipio —uno grande tiene muchos, y uno pequeño comparte
    el suyo con los vecinos—, así que `cod_ine` completo solo lo pone el
    geocodificador, que sí devuelve el código del INE.

    Devuelve (provincias corregidas, provincias que no se pudieron deducir).
    """
    corregidas = sin_deducir = 0
    for p in pois:
        canonico = provincia_desde_cp(getattr(p, "cp", None))
        if canonico is None:
            if not getattr(p, "provincia", None):
                sin_deducir += 1
            continue
        if p.provincia != canonico:
            p.provincia = canonico
            corregidas += 1
    return corregidas, sin_deducir
