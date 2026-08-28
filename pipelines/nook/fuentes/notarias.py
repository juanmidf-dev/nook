"""
Notarías, desde la Guía Notarial del Consejo General del Notariado.

**Endpoint confirmado.** La Guía Notarial (`guianotarial.notariado.org`) es
una aplicación React y la lista no está en el HTML. El bundle
`static/js/main.*.js` declara la tabla completa de rutas; la que interesa es
el buscador:

    POST https://guianotarial.notariado.org/guianotarial/rest/buscar/notarios

El cuerpo es el formulario de búsqueda con todos los campos presentes, aunque
vayan vacíos. Con todos los filtros en blanco y `codigoSituacionNotario: AC`
devuelve el censo nacional de notarios en activo —2.641 registros en la
comprobación del 28/08/2026— en **una sola petición y sin paginar**.

Que sea una sola petición no es una comodidad, es el diseño: el portal corta
con 429 "Demasiadas peticiones" tras unas veinte peticiones seguidas, incluso
espaciándolas dos segundos. Enumerar las 52 provincias, que era la otra forma
de recorrer el censo, se queda a medias y además deja la IP del runner
marcada. Si algún día hace falta filtrar por provincia, se filtra sobre el
resultado nacional, no lanzando 52 consultas.

El endpoint no pide autenticación para este buscador. La aplicación tiene un
`/tokenjwt` para otras pantallas, pero `/buscar/notarios` responde sin él.

Sobre el riesgo no técnico: esto es un directorio profesional público, pero el
uso comercial conviene revisarlo con el Consejo General del Notariado antes de
vender el informe. Está anotado en CLAUDE.md.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Iterable

from ..http import Cliente
from ..modelo import Poi, extrae_cp, id_estable, limpia_direccion

log = logging.getLogger("nook.notarias")

BASE_POR_DEFECTO = "https://guianotarial.notariado.org/guianotarial/rest"

# `or` y no el segundo argumento de environ.get: el workflow pasa
# NOOK_ENDPOINT_NOTARIAS siempre, y cuando el secreto no existe la variable
# llega definida pero vacia. environ.get devuelve "" en ese caso, no el
# defecto, y la URL acababa siendo "/buscar/notarios" a secas.
#
# El rstrip es por lo mismo que ya paso con SUPABASE_URL: una barra de mas al
# final del valor duplica el separador y la ruta deja de existir.
BASE = (os.environ.get("NOOK_ENDPOINT_NOTARIAS") or BASE_POR_DEFECTO).rstrip("/")
ENDPOINT = f"{BASE}/buscar/notarios"

# El buscador rechaza el cuerpo si le faltan campos: hay que mandarlos todos,
# vacíos los que no filtran. "AC" es notario en activo; sin ese filtro entran
# también excedentes y jubilados, que no son competencia instalada.
FILTRO_VACIO: dict[str, str] = {
    "nombre": "",
    "apellidos": "",
    "direccion": "",
    "codigoPostal": "",
    "codigoProvincia": "",
    "municipio": "",
    "idiomaExtranjero": "",
    "codigoSituacionNotario": "AC",
}

CABECERAS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    # Sin Referer el portal responde igual hoy, pero es la petición que hace
    # su propia interfaz y no cuesta nada parecerse a ella.
    "Referer": "https://guianotarial.notariado.org/guianotarial/",
}

ALIAS = {
    # `apellidos_nombre` es como lo publica la Guía; el resto son alias por si
    # cambia el envoltorio. No cuesta nada y evita una ejecución en blanco.
    "apellidos_nombre": ("apellidos_nombre", "apellidosNombre", "nombreCompleto"),
    "nombre": ("nombre", "name", "notario", "nombreNotario", "denominacion"),
    "apellidos": ("apellidos", "surname", "apellido1", "apellidosNotario"),
    "direccion": ("direccion", "domicilio", "address", "calle", "via"),
    "cp": ("cp", "codigoPostal", "codPostal", "postalCode"),
    "municipio": ("municipio", "poblacion", "localidad", "city", "town"),
    "provincia": ("provincia", "province", "prov"),
    "telefono": ("telefono", "tlf", "phone", "telefono1"),
    "fax": ("fax",),
    "email": (
        # Orden deliberado: la dirección de la notaría identifica al despacho,
        # que es lo que se mapea. La personal es el último recurso.
        "correoElectronicoNotaria",
        "correoElectronicoCorporativo",
        "correoElectronicoPersonal",
        "email",
        "correo",
        "mail",
    ),
    "codigo": ("codigoNotaria", "codigo_notaria"),
    "ultimas_voluntades": ("codigoUltimasVoluntades",),
    "idiomas": ("idiomasExtranjeros", "idiomas"),
    "estado": ("estado", "codigoSituacionNotario", "situacion"),
}


def _saca(reg: dict[str, Any], campo: str) -> str | None:
    """Busca un campo por cualquiera de sus alias, ignorando mayúsculas."""
    normalizado = {str(k).lower(): v for k, v in reg.items()}
    for alias in ALIAS[campo]:
        v = normalizado.get(alias.lower())
        if v not in (None, ""):
            return str(v).strip()
    return None


def nombre_legible(apellidos_nombre: str) -> str:
    """
    "Díaz-Fraile del Monte, Aurora Cristina" -> "Aurora Cristina Díaz-Fraile del Monte".

    La Guía lo publica invertido para ordenar alfabéticamente. Se le da la
    vuelta porque este nombre acaba impreso en el informe que se entrega al
    cliente, y ahí "Apellidos, Nombre" se lee como un listado de sistema.
    Solo se parte por la primera coma: hay apellidos compuestos con coma
    detrás, pero el nombre siempre va después de la primera.
    """
    if "," not in apellidos_nombre:
        return apellidos_nombre.strip()
    apellidos, _, nombre = apellidos_nombre.partition(",")
    return f"{nombre.strip()} {apellidos.strip()}".strip()


# La dirección cierra con el código postal pegado, sin separador:
# "Calle Del Sol, número 1 Pl 2  08201".
_CP_FINAL = re.compile(r"\s+(\d{5})\s*$")


def interpreta_registro(reg: dict[str, Any]) -> Poi | None:
    bruto = _saca(reg, "apellidos_nombre")
    if bruto:
        nombre = nombre_legible(bruto)
    else:
        nombre = _saca(reg, "nombre")
        apellidos = _saca(reg, "apellidos")
        if nombre and apellidos and apellidos not in nombre:
            nombre = f"{nombre} {apellidos}"
    if not nombre:
        return None

    direccion_bruta = _saca(reg, "direccion")
    cp = _saca(reg, "cp") or extrae_cp(direccion_bruta)
    # Se quita el CP del final de la vía: el geocodificador lo recibe aparte y
    # dejarlo pegado al portal empeora la coincidencia a nivel de calle.
    if direccion_bruta:
        direccion_bruta = _CP_FINAL.sub("", direccion_bruta)
    direccion = limpia_direccion(direccion_bruta)

    municipio = _saca(reg, "municipio")
    provincia = _saca(reg, "provincia")

    # A diferencia de lo que se supuso antes de ver la respuesta, la Guía sí
    # publica clave propia: `codigoNotaria`. Se usa tal cual, porque sobrevive
    # a un cambio de domicilio del despacho; el hash de nombre y dirección, no
    # —una notaría que se muda aparecería como cierre más alta nueva.
    codigo = _saca(reg, "codigo")
    fuente_id = codigo or id_estable(nombre, direccion or "", municipio or "", cp or "")

    return Poi(
        tipo="notaria",
        fuente="notariado",
        fuente_id=fuente_id,
        nombre=nombre,
        direccion=direccion,
        cp=cp,
        municipio=municipio,
        provincia=provincia,
        telefono=_saca(reg, "telefono"),
        email=_saca(reg, "email"),
        extra={
            k: v
            for k, v in {
                "codigo_notaria": codigo,
                "codigo_ultimas_voluntades": _saca(reg, "ultimas_voluntades"),
                "idiomas": _saca(reg, "idiomas"),
                "fax": _saca(reg, "fax"),
                "estado": _saca(reg, "estado"),
                # Se guarda el nombre tal y como lo publica la fuente: si
                # mañana hay que cotejar con el original, sin esto habría que
                # deshacer la inversión a mano.
                "apellidos_nombre": bruto,
            }.items()
            if v
        },
    )


def interpreta_respuesta(datos: Any) -> list[Poi]:
    """
    Saca los registros de una respuesta sin fijar el envoltorio.

    Hoy `/buscar/notarios` devuelve una lista pelada. Se aceptan también los
    envoltorios habituales de estos portales para que un cambio cosmético no
    tumbe la ingesta: el coste es una comprobación, y la alternativa es un
    mes sin capa de competencia.
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

    registros = list(registros)
    pois = [p for r in registros if isinstance(r, dict) for p in [interpreta_registro(r)] if p]

    # Un descarte aislado es un registro raro; un descarte masivo es que la
    # fuente cambió de forma y hay que mirarla, no seguir como si nada.
    descartados = len(registros) - len(pois)
    if descartados:
        log.warning("notarías descartadas por no tener nombre: %d de %d", descartados, len(registros))
    log.info("notarías interpretadas: %d de %d registros", len(pois), len(registros))

    duplicados = len(pois) - len({p.fuente_id for p in pois})
    if duplicados:
        log.warning("¡%d fuente_id repetidos! el upsert mensual perdería registros", duplicados)
    return pois


def extrae(
    cliente: Cliente | None = None,
    endpoint: str | None = None,
    provincia: str | None = None,
) -> list[Poi]:
    """
    Trae el censo notarial. `provincia` filtra **sobre el resultado**, no en
    la consulta: ver la nota sobre el 429 en la cabecera del módulo.
    """
    url = endpoint or ENDPOINT
    # Pausa alta a propósito: aunque solo se haga una petición, este cliente
    # se comparte y el portal ya ha demostrado que corta rápido.
    cliente = cliente or Cliente(pausa_s=2.0)
    datos = cliente.json_post(url, json=dict(FILTRO_VACIO), headers=CABECERAS)
    pois = interpreta_respuesta(datos)

    if provincia:
        codigo = str(provincia).zfill(2)
        pois = [p for p in pois if (p.cp or "")[:2] == codigo]
        log.info("filtradas a la provincia %s: %d notarías", codigo, len(pois))
    return pois
