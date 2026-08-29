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

    def upsert_pois(self, pois: list[Poi]) -> int:
        escritos = 0
        for i in range(0, len(pois), self.lote):
            trozo = [p.para_supabase() for p in pois[i : i + self.lote]]
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
