"""
Escritura del resultado: a fichero (modo prueba) o a Supabase (modo real).

El modo prueba existe porque estos extractores no se pueden ensayar en local
—ni el entorno de desarrollo ni el equipo tienen salida hacia notariado.org,
el Banco de España o el INE—, así que la primera vez que un extractor toca
datos de verdad es dentro de un runner de GitHub. Escribir directamente en la
base de datos en esa primera ejecución sería temerario: en modo prueba el
resultado queda como artefacto descargable y se revisa antes de tocar nada.
"""

from __future__ import annotations

import json
import logging
import pathlib
from dataclasses import asdict

import requests

from .modelo import Poi

log = logging.getLogger("nook.salida")


def a_ndjson(pois: list[Poi], destino: pathlib.Path) -> pathlib.Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8") as f:
        for p in pois:
            f.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")
    log.info("escritos %d registros en %s", len(pois), destino)
    return destino


def resumen(pois: list[Poi]) -> dict:
    """Cifras que se imprimen al final de cada ejecución y van al log de Actions."""
    from collections import Counter

    por_tipo = Counter(p.tipo for p in pois)
    sin_coord = [p for p in pois if not p.geolocalizado]
    por_calidad = Counter(p.geocode_calidad for p in pois if p.geolocalizado)

    # Los que se quedaron sin coordenada no son todos el mismo caso, y
    # mezclarlos oculta el que importa. "No lo encontré" se arregla mejorando
    # la consulta; "lo encontré pero solo a nivel de municipio" se arregla
    # buscando la dirección a mano, y hasta entonces es un hueco conocido en
    # la capa de competencia. Separarlos es lo que permite saber cuál toca.
    # El discriminador es `geocode_fuente`, no `geocode_calidad`: esta última
    # arranca valiendo "desconocida" por defecto, así que un registro que
    # ningún geocodificador llegó a ver es indistinguible por calidad de uno
    # que sí se resolvió con precisión dudosa. La fuente solo se rellena
    # cuando alguien respondió de verdad.
    descartadas = Counter(p.geocode_calidad for p in sin_coord if p.geocode_fuente)

    return {
        "total": len(pois),
        "por_tipo": dict(por_tipo),
        "sin_coordenadas": len(sin_coord),
        "por_calidad": dict(por_calidad),
        # Encontradas, pero con una precisión que no sirve al modelo: su
        # coordenada se descarta a propósito en vez de colocar la notaría en
        # el centro del pueblo. Ver CALIDADES_NO_UBICABLES en geocode.py.
        "descartadas_por_calidad": dict(descartadas),
        # No aparecieron en ningún geocodificador.
        "no_encontradas": len(sin_coord) - sum(descartadas.values()),
    }


def _comprueba_claves_uniformes(trozo: list[dict], desde: int) -> None:
    """
    PostgREST rechaza un lote entero si sus objetos no comparten claves, con
    un `PGRST102: All object keys must match` que no dice cuál sobra ni cuál
    falta. Merece la pena detectarlo aquí: el error llega tras la
    geocodificación, o sea, tres cuartos de hora después de empezar.
    """
    if not trozo:
        return
    referencia = set(trozo[0])
    for n, obj in enumerate(trozo[1:], start=1):
        if set(obj) != referencia:
            sobran = sorted(set(obj) - referencia)
            faltan = sorted(referencia - set(obj))
            raise RuntimeError(
                f"el registro {desde + n} no tiene las mismas claves que el "
                f"primero del lote (sobran: {sobran or 'ninguna'}; "
                f"faltan: {faltan or 'ninguna'}). PostgREST rechazaria el lote."
            )


class Supabase:
    """
    Escritura por PostgREST con upsert.

    Se usa la API REST y no una conexión directa de PostgreSQL para no tener
    que abrir la base de datos a los rangos de IP de GitHub: el runner solo
    necesita la URL del proyecto y la service key, ambas como secretos del
    repositorio.
    """

    def __init__(self, url: str, service_key: str, lote: int = 500) -> None:
        self.base = url.rstrip("/") + "/rest/v1"
        self.lote = lote
        self.cabeceras = {
            "apikey": service_key,
            "Content-Type": "application/json",
            # merge-duplicates convierte el insert en upsert: la ejecución
            # mensual actualiza los registros existentes en vez de duplicarlos.
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        # Las dos generaciones de clave de Supabase quieren cosas distintas.
        #
        # La antigua `service_role` es un JWT y va también en Authorization,
        # que es de donde PostgREST saca el rol. La nueva `sb_secret_...` no
        # es un JWT: mandarla en Authorization hace que la petición llegue a
        # la base de datos y se rechace al intentar interpretarla como token,
        # aunque coincida con el valor de `apikey`. Con la nueva basta con
        # `apikey`, que es donde la pasarela resuelve el rol.
        #
        # Se distingue por la forma y no por configuración: un JWT siempre
        # empieza por la cabecera '{"alg"' en base64, o sea "eyJ".
        if service_key.startswith("eyJ"):
            self.cabeceras["Authorization"] = f"Bearer {service_key}"

    def tipos_admitidos(self) -> set[str] | None:
        """
        Los valores que el enum `poi_tipo` acepta hoy en la base de datos.

        PostgREST publica en su raíz un OpenAPI con la definición de cada
        tabla, y las columnas de tipo enumerado traen ahí sus valores. Es una
        lectura, no toca nada.

        Devuelve None si no se puede averiguar, y eso **no** debe bloquear la
        ingesta: un chequeo previo que da falsos negativos es peor que no
        tenerlo, porque acabaría impidiendo escrituras perfectamente válidas.
        """
        try:
            r = requests.get(self.base + "/", headers=self.cabeceras, timeout=30)
            if r.status_code >= 300:
                return None
            definiciones = r.json().get("definitions", {})
            tipo = definiciones.get("pois", {}).get("properties", {}).get("tipo", {})
        except Exception as e:  # noqa: BLE001
            log.warning("no se pudo leer el esquema de Supabase (%s)", e)
            return None

        valores = tipo.get("enum")
        if valores:
            return set(valores)
        # PostgREST viejo describe el enum dentro de `format`, no en `enum`.
        formato = tipo.get("format", "")
        if "'" in formato:
            import re as _re

            return set(_re.findall(r"'([^']+)'", formato)) or None
        return None

    def comprueba_tipos(self, pois: list[Poi]) -> None:
        """
        Aborta antes de trabajar si la base de datos no acepta algún tipo.

        Existe porque tres fallos distintos del 29/08/2026 se manifestaron
        solo **al escribir**, después de hacer todo el trabajo: las claves no
        uniformes, las claves repetidas y un valor de enum que faltaba. Con
        Overture eso cuesta ocho minutos; con notarías o bancos, setenta,
        porque la geocodificación va por delante.
        """
        admitidos = self.tipos_admitidos()
        if admitidos is None:
            log.warning("no se pudo comprobar el enum poi_tipo; se sigue igualmente")
            return
        usados = {p.tipo for p in pois}
        faltan = sorted(usados - admitidos)
        if faltan:
            raise SystemExit(
                "la base de datos no admite el tipo/s " + ", ".join(faltan)
                + ". Admite: " + ", ".join(sorted(admitidos))
                + ". Aplica el bloque correspondiente de infra/schema.sql, "
                + "por ejemplo: alter type poi_tipo add value if not exists '"
                + faltan[0] + "';"
            )
        log.info("la base de datos admite los %d tipos que se van a escribir", len(usados))

    def upsert_pois(self, pois: list[Poi]) -> int:
        escritos = 0
        for i in range(0, len(pois), self.lote):
            trozo = [p.para_supabase() for p in pois[i : i + self.lote]]
            _comprueba_claves_uniformes(trozo, i)
            r = requests.post(
                f"{self.base}/pois",
                params={"on_conflict": "fuente,fuente_id"},
                headers=self.cabeceras,
                data=json.dumps(trozo, ensure_ascii=False).encode("utf-8"),
                timeout=120,
            )
            if r.status_code >= 300:
                log.error("Supabase devolvió %d: %s", r.status_code, r.text[:500])
                raise RuntimeError(f"fallo escribiendo en Supabase: {r.status_code}")
            escritos += len(trozo)
            log.info("escritos %d/%d", escritos, len(pois))
        return escritos

    def registra_ingesta(self, fuente: str, ambito: str, res: dict, estado: str,
                         mensaje: str | None = None) -> None:
        requests.post(
            f"{self.base}/ingestas",
            headers={**self.cabeceras, "Prefer": "return=minimal"},
            data=json.dumps(
                {
                    "fuente": fuente,
                    "ambito": ambito,
                    "estado": estado,
                    "registros": res.get("total"),
                    "mensaje": mensaje,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            timeout=30,
        )
