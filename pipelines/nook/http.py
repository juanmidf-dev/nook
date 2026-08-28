"""
Cliente HTTP para las fuentes públicas.

Todas las fuentes de Nook son portales de organismos públicos y colegios
profesionales, no APIs comerciales: aguantan mal las ráfagas y no tienen
ningún interés en que las machaquemos. De ahí el ritmo limitado por defecto y
el reintento con espera creciente. Un extractor que tarda veinte minutos y no
molesta a nadie es infinitamente preferible a uno que tarda dos y acaba con la
IP de los runners de GitHub bloqueada.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

import requests

log = logging.getLogger("nook.http")

# `callback([...]);` -> `[...]`. El nombre de la funcion varia, y puede no
# haberlo, asi que se acepta cualquiera y tambien el parentesis pelado.
_ENVOLTORIO_JSONP = re.compile(r"^\s*[\w$.]*\(\s*(.*?)\s*\)\s*;?\s*$", re.S)

AGENTE = (
    "NookBot/1.0 (+https://github.com/juanmidf-dev; herramienta de análisis "
    "de ubicación notarial; contacto: diazfraile97@gmail.com)"
)


@dataclass
class Cliente:
    """Sesión con ritmo limitado, reintentos y espera creciente."""

    pausa_s: float = 1.0
    intentos: int = 4
    timeout_s: float = 30.0
    agente: str = AGENTE

    def __post_init__(self) -> None:
        self.sesion = requests.Session()
        self.sesion.headers.update(
            {"User-Agent": self.agente, "Accept-Language": "es-ES,es;q=0.9"}
        )
        self._ultima = 0.0

    def _espera_ritmo(self) -> None:
        delta = time.monotonic() - self._ultima
        if delta < self.pausa_s:
            time.sleep(self.pausa_s - delta)
        self._ultima = time.monotonic()

    def get(self, url: str, **kw) -> requests.Response | None:
        """Devuelve la respuesta, o None si se agotaron los intentos."""
        for intento in range(1, self.intentos + 1):
            self._espera_ritmo()
            try:
                r = self.sesion.get(url, timeout=self.timeout_s, **kw)
            except requests.RequestException as e:
                log.warning("intento %d/%d fallo de red en %s: %s", intento, self.intentos, url, e)
            else:
                if r.status_code == 200:
                    return r
                # 429 y 5xx son transitorios; 404 y 403 no se reintentan
                # porque repetirlos solo gasta tiempo y llama la atención.
                if r.status_code in (429, 500, 502, 503, 504):
                    log.warning("intento %d/%d %s devolvió %d", intento, self.intentos, url, r.status_code)
                else:
                    log.error("%s devolvió %d, no se reintenta", url, r.status_code)
                    return None
            if intento < self.intentos:
                time.sleep(min(2**intento, 30))
        log.error("agotados los intentos con %s", url)
        return None

    def post(self, url: str, **kw) -> requests.Response | None:
        """
        Como `get`, con la misma política de ritmo y reintentos.

        Existe porque la Guía Notarial expone su buscador como POST con el
        filtro en el cuerpo: no hay forma de pedirle el censo con un GET.
        """
        for intento in range(1, self.intentos + 1):
            self._espera_ritmo()
            try:
                r = self.sesion.post(url, timeout=self.timeout_s, **kw)
            except requests.RequestException as e:
                log.warning("intento %d/%d fallo de red en %s: %s", intento, self.intentos, url, e)
            else:
                if r.status_code == 200:
                    return r
                if r.status_code in (429, 500, 502, 503, 504):
                    log.warning("intento %d/%d %s devolvió %d", intento, self.intentos, url, r.status_code)
                else:
                    log.error("%s devolvió %d, no se reintenta", url, r.status_code)
                    return None
            if intento < self.intentos:
                time.sleep(min(2**intento, 30))
        log.error("agotados los intentos con %s", url)
        return None

    def json(self, url: str, **kw) -> object | None:
        r = self.get(url, **kw)
        if r is None:
            return None
        try:
            return r.json()
        except ValueError:
            log.error("%s no devolvió JSON válido (content-type=%s)", url, r.headers.get("content-type"))
            return None

    def jsonp(self, url: str, **kw) -> object | None:
        """
        Como `json`, pero desenvolviendo la llamada JSONP.

        CartoCiudad solo publica `findJsonp`, que responde
        `callback([...])` con content-type application/x-javascript.
        `r.json()` no puede con eso, asi que el geocodificador oficial
        fallaba en todas y cada una de las peticiones y todo caia al
        respaldo de Nominatim sin que nada lo anunciara mas alla de un
        ERROR por linea en el log.
        """
        r = self.get(url, **kw)
        if r is None:
            return None
        m = _ENVOLTORIO_JSONP.match(r.text)
        cuerpo = m.group(1) if m else r.text
        try:
            return json.loads(cuerpo)
        except ValueError:
            log.error(
                "%s no devolvió JSONP interpretable (content-type=%s): %s",
                url, r.headers.get("content-type"), r.text[:120],
            )
            return None

    def json_post(self, url: str, **kw) -> object | None:
        r = self.post(url, **kw)
        if r is None:
            return None
        try:
            return r.json()
        except ValueError:
            log.error("%s no devolvió JSON válido (content-type=%s)", url, r.headers.get("content-type"))
            return None
