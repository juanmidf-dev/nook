"""
Notarías.

**Estado: pendiente de confirmar el endpoint.** La Guía Notarial
(`guianotarial.notariado.org`) es una aplicación React que pide los datos a un
endpoint que no está documentado y que no se puede inspeccionar desde aquí
—ni el entorno de desarrollo ni el equipo local tienen salida hacia ese
dominio—. El workflow `reconocimiento.yml` existe justamente para traerse esa
información desde un runner con red; con su artefacto delante se rellena
`ENDPOINT` y este módulo queda cerrado.

Mientras tanto, lo que sí está escrito y probado es la parte que no depende
del endpoint: la interpretación de un registro de notaría a `Poi`. Sea cual
sea la forma exacta de la respuesta, los campos que necesitamos son siempre
los mismos —nombre del notario, dirección, población, provincia, teléfono— y
`interpreta_registro` los busca por varios alias.

No se inventa un endpoint plausible ni se deja un scraper "a ver si suena":
un extractor que falla en silencio y devuelve cero notarías es peor que uno
que no existe, porque el mapa se queda sin capa de competencia y recomienda
justo el portal de al lado de una notaría existente.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Iterable

from ..http import Cliente
from ..modelo import Poi, extrae_cp, id_estable, limpia_direccion

log = logging.getLogger("nook.notarias")

# Se rellena tras el reconocimiento. Se puede sobreescribir sin tocar código
# con la variable de entorno NOOK_ENDPOINT_NOTARIAS, para poder probar un
# candidato desde Actions sin abrir un pull request por cada intento.
ENDPOINT: str | None = os.environ.get("NOOK_ENDPOINT_NOTARIAS")

ALIAS = {
    "nombre": ("nombre", "name", "notario", "nombreNotario", "nombreCompleto", "denominacion"),
    "apellidos": ("apellidos", "surname", "apellido1", "apellidosNotario"),
    "direccion": ("direccion", "domicilio", "address", "calle", "via"),
    "cp": ("cp", "codigoPostal", "codPostal", "postalCode"),
    "municipio": ("municipio", "poblacion", "localidad", "city", "town"),
    "provincia": ("provincia", "province", "prov"),
    "telefono": ("telefono", "tlf", "phone", "telefono1"),
    "email": ("email", "correo", "mail", "correoElectronico"),
    "colegio": ("colegio", "colegioNotarial", "colegio_notarial"),
}


def _saca(reg: dict[str, Any], campo: str) -> str | None:
    """Busca un campo por cualquiera de sus alias, ignorando mayúsculas."""
    normalizado = {str(k).lower(): v for k, v in reg.items()}
    for alias in ALIAS[campo]:
        v = normalizado.get(alias.lower())
        if v not in (None, ""):
            return str(v).strip()
    return None


def interpreta_registro(reg: dict[str, Any]) -> Poi | None:
    nombre = _saca(reg, "nombre")
    apellidos = _saca(reg, "apellidos")
    if nombre and apellidos and apellidos not in nombre:
        nombre = f"{nombre} {apellidos}"
    if not nombre:
        return None

    direccion = limpia_direccion(_saca(reg, "direccion"))
    municipio = _saca(reg, "municipio")
    provincia = _saca(reg, "provincia")
    cp = _saca(reg, "cp") or extrae_cp(_saca(reg, "direccion"))

    return Poi(
        tipo="notaria",
        fuente="notariado",
        # La Guía Notarial pagina y no expone un id propio en la respuesta
        # que se ve desde fuera, así que se construye uno determinista: sin
        # él, la ejecución mensual duplicaría el censo notarial entero.
        fuente_id=id_estable(nombre, direccion or "", municipio or "", cp or ""),
        nombre=nombre,
        direccion=direccion,
        cp=cp,
        municipio=municipio,
        provincia=provincia,
        telefono=_saca(reg, "telefono"),
        email=_saca(reg, "email"),
        extra={"colegio": _saca(reg, "colegio")},
    )


def interpreta_respuesta(datos: Any) -> list[Poi]:
    """
    Saca los registros de una respuesta sin conocer su envoltorio exacto.

    Las APIs de estos portales devuelven a veces una lista pelada y a veces un
    objeto con los resultados dentro de `content`, `data`, `items` o
    `resultados`. Se prueban todas en vez de fijar una, para que el extractor
    no se caiga por un cambio cosmético del envoltorio.
    """
    registros: Iterable[Any]
    if isinstance(datos, list):
        registros = datos
    elif isinstance(datos, dict):
        for clave in ("content", "data", "items", "resultados", "results", "notarios", "list"):
            if isinstance(datos.get(clave), list):
                registros = datos[clave]
                break
        else:
            registros = []
    else:
        registros = []

    pois = [p for r in registros if isinstance(r, dict) for p in [interpreta_registro(r)] if p]
    log.info("notarías interpretadas: %d de %d registros", len(pois), len(list(registros)))
    return pois


def extrae(cliente: Cliente | None = None, endpoint: str | None = None) -> list[Poi]:
    url = endpoint or ENDPOINT
    if not url:
        raise RuntimeError(
            "El endpoint de la Guía Notarial no está confirmado todavía. Ejecuta el "
            "workflow 'reconocimiento' y, con su artefacto, fija NOOK_ENDPOINT_NOTARIAS "
            "o la constante ENDPOINT de este módulo."
        )
    cliente = cliente or Cliente(pausa_s=1.5)
    return interpreta_respuesta(cliente.json(url))
