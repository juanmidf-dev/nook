"""
Oficinas bancarias desde el Registro de Oficinas del Banco de España.

El Banco de España publica el listado en su Oficina Virtual, con un formulario
de consulta que devuelve un CSV ("Detalle_oficinas.csv"). No es una API: hay
que pasar por el formulario o descargar el fichero a mano. Por eso este
extractor está diseñado alrededor del **fichero**, no del endpoint — así
funciona igual si el flujo se automatiza o si alguien lo descarga y lo deja en
`datos/entrada/`.

El formato tiene sus cosas:

- codificación latin-1, no UTF-8;
- separador `;` rodeado de espacios, y una columna vacía al final de cada
  línea porque todas terminan en `;`;
- valores con relleno de espacios a la derecha ("CATALUÑA           ");
- el código INE del municipio va partido en dos columnas, provincia y
  municipio, que hay que concatenar con relleno de ceros;
- las direcciones traen el tipo de vía abreviado en dos letras y a veces el
  número de oficina repetido al final ("PLACA MAJOR, 32 0032").

Ninguna de estas cosas está documentada; salen de mirar un fichero real.
"""

from __future__ import annotations

import csv
import io
import logging
import pathlib
from typing import Iterable

from ..modelo import Poi, id_estable, limpia_direccion

log = logging.getLogger("nook.bancos")

CODIFICACION = "latin-1"

# Solo las oficinas que atienden al público. El fichero incluye también
# servicios centrales y oficinas no operativas, que no generan tránsito de
# personas y por tanto no son demanda notarial.
TIPOS_UTILES = {"operativas"}


def _clave(nombre: str) -> str:
    return nombre.strip().lower().replace(".", "").replace("ó", "o").replace("í", "i").replace("á", "a")


def _campo(fila: dict[str, str], *alias: str) -> str | None:
    for a in alias:
        for k, v in fila.items():
            if k and _clave(k) == _clave(a):
                v = (v or "").strip()
                return v or None
    return None


def cod_ine(cod_provincia: str | None, cod_municipio: str | None) -> str | None:
    """
    Reconstruye el código INE de 5 dígitos.

    El fichero trae la provincia con dos dígitos y el municipio con los que
    hagan falta; el código INE es provincia(2) + municipio(3) con ceros a la
    izquierda. Sabadell aparece como 08 + 187 y tiene que quedar en 08187.
    """
    if not cod_provincia or not cod_municipio:
        return None
    p = cod_provincia.strip().zfill(2)
    m = cod_municipio.strip().zfill(3)
    if not (p.isdigit() and m.isdigit()):
        return None
    return f"{p}{m}"


def nombre_entidad(bruto: str | None) -> tuple[str | None, str | None]:
    """Separa "BANCO SANTANDER, S.A. (0049)" en nombre y código de entidad."""
    if not bruto:
        return None, None
    s = bruto.strip()
    codigo = None
    if s.endswith(")") and "(" in s:
        cabeza, _, cola = s.rpartition("(")
        posible = cola.rstrip(")").strip()
        if posible.isdigit():
            codigo = posible
            s = cabeza.strip()
    s = s.rstrip(" ,")
    if s.isupper():
        s = s.title()
        for w in ("S.A.E.", "S.A.", "S.L.", "S.C.C.", "B.B.V.A."):
            s = s.replace(w.title(), w)
    return s or None, codigo


def interpreta(texto: str) -> list[Poi]:
    """
    Convierte el contenido del CSV en Poi.

    Toma el texto ya decodificado en vez de una ruta para poder probarlo con
    fragmentos pequeños y no depender del fichero completo.
    """
    lector = csv.DictReader(io.StringIO(texto), delimiter=";")
    pois: list[Poi] = []
    descartadas = 0

    for bruta in lector:
        fila = { (k or "").strip(): (v or "").strip() for k, v in bruta.items() if k is not None }

        # El fichero termina con un bloque de metadatos —una fila de
        # almohadillas, los criterios de la consulta y las fechas de
        # obtención y de referencia— que el lector de CSV entrega como filas
        # normales. Sin filtrarlo se cuelan dos "oficinas" llamadas
        # "########" en mitad del parque bancario.
        entidad_bruta = _campo(fila, "Entidad") or ""
        if set(entidad_bruta) <= {"#"} and entidad_bruta:
            continue
        if not _campo(fila, "Domicilio") or not _campo(fila, "Cod. Provincia"):
            descartadas += 1
            continue

        tipo_oficina = (_campo(fila, "Tipo") or "").lower()
        if tipo_oficina and tipo_oficina not in TIPOS_UTILES:
            descartadas += 1
            continue

        nombre, codigo = nombre_entidad(_campo(fila, "Entidad"))
        if not nombre:
            continue

        domicilio = _campo(fila, "Domicilio")  # en bruto: se usa para el id
        municipio = _campo(fila, "Municipio/Poblacion", "Municipio/Población", "Municipio")
        ine = cod_ine(_campo(fila, "Cod. Provincia"), _campo(fila, "Cod. Municipio", "Cód. Municipio"))

        pois.append(
            Poi(
                tipo="banco",
                fuente="bde",
                # El fichero no trae identificador de oficina, así que se
                # construye uno determinista: sin él, cada ejecución mensual
                # insertaría el parque bancario entero otra vez.
                # El id se construye con el domicilio EN BRUTO, no con el
                # limpio: la limpieza quita el número de oficina que el
                # fichero repite al final ("PLACA MAJOR, 32 0032"), y ese
                # número es justo lo que distingue dos sucursales de la misma
                # entidad en la misma calle. Con el domicilio limpio, dos
                # oficinas reales colapsaban en un solo registro.
                fuente_id=id_estable(codigo or nombre, domicilio or "", ine or "", _campo(fila, "CP") or ""),
                nombre=nombre,
                direccion=limpia_direccion(domicilio),
                cp=_campo(fila, "CP"),
                municipio=(municipio or "").title() or None,
                cod_ine=ine,
                provincia=_campo(fila, "Provincia"),
                extra={
                    "cod_entidad": codigo,
                    "tipo_entidad": _campo(fila, "Tipo Entidad"),
                    "ccaa": (_campo(fila, "CCAA") or "").title() or None,
                },
            )
        )

    # Dos registros del mismo banco, misma dirección y mismo CP producen el
    # mismo id. Pasa en el fichero real —la misma oficina anotada dos veces
    # con puntuación distinta— y el upsert las funde en una. Se prefiere eso a
    # meter el número de fila en el id: el orden del fichero cambia entre
    # descargas y cada mes se crearían registros nuevos en vez de actualizar
    # los existentes. Pero se avisa, porque si el número crece hay que mirarlo.
    colisiones = len(pois) - len({p.fuente_id for p in pois})
    if colisiones:
        log.warning("BdE: %d registros comparten id y se fundirán al escribir", colisiones)

    log.info("BdE: %d oficinas operativas, %d filas descartadas", len(pois), descartadas)
    return pois


def desde_fichero(ruta: pathlib.Path) -> list[Poi]:
    datos = ruta.read_bytes()
    for codificacion in (CODIFICACION, "cp1252", "utf-8-sig"):
        try:
            return interpreta(datos.decode(codificacion))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"no se pudo decodificar {ruta}")


def desde_carpeta(carpeta: pathlib.Path) -> list[Poi]:
    """Lee todos los CSV de una carpeta: el BdE se descarga por provincia."""
    pois: list[Poi] = []
    ficheros = sorted(carpeta.glob("*.csv"))
    if not ficheros:
        log.warning("no hay CSV del Banco de España en %s", carpeta)
    for f in ficheros:
        log.info("leyendo %s", f.name)
        pois += desde_fichero(f)
    return pois
