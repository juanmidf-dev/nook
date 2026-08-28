"""
Reconocimiento de fuentes.

Ni el entorno de desarrollo ni el equipo local tienen salida hacia
notariado.org o el Banco de España, así que no hay forma de mirar cómo son
esas respuestas antes de escribir el extractor. Escribir el parser a ciegas y
esperar a que funcione en producción es la receta de tres ejecuciones fallidas
seguidas.

Este módulo hace lo contrario: se ejecuta primero, desde un runner que sí
tiene red, y su único trabajo es **traerse muestras** de lo que hay ahí fuera
—el HTML, los bundles de JavaScript, las respuestas de los endpoints que
encuentre— y dejarlas como artefacto descargable. Con esas muestras delante se
escribe el parser exacto, una vez.

La Guía Notarial es una aplicación React, así que la lista de notarías no está
en el HTML: la pide su JavaScript a algún endpoint. La estrategia es bajar los
bundles y buscar en ellos las rutas de API.
"""

from __future__ import annotations

import json
import logging
import pathlib
import re
from dataclasses import dataclass, field

from .http import Cliente

log = logging.getLogger("nook.recon")

OBJETIVOS = {
    "guia_notarial": "http://guianotarial.notariado.org/",
    "notariado": "https://www.notariado.org/portal/elige-a-tu-notario",
    "catastro_notarios": "https://www1.sedecatastro.gob.es/administracionElectronica/SECBuscaNotarios.aspx",
    "bde_oficinas": "https://app.bde.es/exbwciu/exbwciuias/xml/Arranque.html",
}

# Rutas que suelen aparecer en las SPA de organismos españoles. No se prueban
# a lo loco: solo las que además aparezcan citadas en el JavaScript.
PISTAS_API = re.compile(
    r"""["'`](/(?:api|rest|services|servicios|ws)/[A-Za-z0-9_\-/{}.]*)["'`]"""
)
PISTAS_BASE = re.compile(r"""["'`](https?://[A-Za-z0-9.\-]+/(?:api|rest|services)[A-Za-z0-9_\-/]*)["'`]""")
PISTAS_BUNDLE = re.compile(r"""(?:src|href)=["']([^"']+\.(?:js|css))["']""")


@dataclass
class Hallazgo:
    nombre: str
    url: str
    estado: str
    tipo_contenido: str | None = None
    bytes: int = 0
    rutas_api: list[str] = field(default_factory=list)
    bundles: list[str] = field(default_factory=list)
    nota: str | None = None


def _guarda(carpeta: pathlib.Path, nombre: str, contenido: bytes) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / nombre).write_bytes(contenido)


def explora(destino: pathlib.Path, cliente: Cliente | None = None) -> list[Hallazgo]:
    cliente = cliente or Cliente(pausa_s=1.5)
    hallazgos: list[Hallazgo] = []

    for nombre, url in OBJETIVOS.items():
        r = cliente.get(url)
        if r is None:
            hallazgos.append(Hallazgo(nombre, url, "inalcanzable"))
            continue

        cuerpo = r.content
        _guarda(destino / nombre, "index.html", cuerpo)
        texto = r.text

        h = Hallazgo(
            nombre=nombre,
            url=url,
            estado="ok",
            tipo_contenido=r.headers.get("content-type"),
            bytes=len(cuerpo),
            rutas_api=sorted(set(PISTAS_API.findall(texto)) | set(PISTAS_BASE.findall(texto))),
            bundles=sorted(set(PISTAS_BUNDLE.findall(texto))),
        )

        # Los bundles son donde de verdad está la información: una SPA no
        # deja sus rutas de API en el HTML.
        from urllib.parse import urljoin

        for i, b in enumerate(h.bundles[:8]):
            u = urljoin(url, b)
            if not u.endswith(".js"):
                continue
            rb = cliente.get(u)
            if rb is None:
                continue
            _guarda(destino / nombre / "bundles", f"{i:02d}_{pathlib.Path(b).name}", rb.content)
            encontradas = set(PISTAS_API.findall(rb.text)) | set(PISTAS_BASE.findall(rb.text))
            if encontradas:
                log.info("%s: %d rutas candidatas en %s", nombre, len(encontradas), b)
                h.rutas_api = sorted(set(h.rutas_api) | encontradas)

        hallazgos.append(h)

    # Segunda pasada: probar las rutas encontradas y guardar lo que devuelvan.
    from urllib.parse import urljoin

    for h in hallazgos:
        if h.estado != "ok":
            continue
        for j, ruta in enumerate(h.rutas_api[:25]):
            u = ruta if ruta.startswith("http") else urljoin(h.url, ruta)
            r = cliente.get(u)
            if r is None:
                continue
            nombre_fichero = f"{j:02d}_" + re.sub(r"[^A-Za-z0-9]+", "_", ruta)[:60]
            ext = "json" if "json" in (r.headers.get("content-type") or "") else "txt"
            _guarda(destino / h.nombre / "respuestas", f"{nombre_fichero}.{ext}", r.content[:2_000_000])
            log.info("%s -> %s (%s, %d bytes)", u, r.status_code, r.headers.get("content-type"), len(r.content))

    (destino / "resumen.json").write_text(
        json.dumps([h.__dict__ for h in hallazgos], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return hallazgos
