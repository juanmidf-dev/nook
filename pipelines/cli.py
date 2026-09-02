"""
Punto de entrada del pipeline de ingesta.

    python cli.py reconocimiento
    python cli.py bancos     --prueba          # lee datos/bde/*.csv
    python cli.py overture   --provincia 08 --prueba
    python cli.py notarias   --prueba

`--prueba` es el modo por defecto en todo lo que no sea una ejecución
programada: escribe el resultado en `datos/salida/` como NDJSON y no toca
Supabase. Estos extractores no se pueden ensayar en local, así que la primera
vez que uno ve datos reales es dentro de un runner; escribir directo en la
base de datos en esa primera pasada sería temerario.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import sys

from nook import geocode, geografia
from nook.fuentes import bancos, notarias, overture
from nook.modelo import Poi, colapsa_por_id, deduplica
from nook.salida import Supabase, a_ndjson, resumen

RAIZ = pathlib.Path(__file__).resolve().parent
SALIDA = RAIZ / "datos" / "salida"

log = logging.getLogger("nook")


def geocodifica_pendientes(pois: list[Poi], limite: int | None = None) -> None:
    """Geocodifica solo lo que no trae coordenadas, y deja constancia de la calidad."""
    pendientes = [p for p in pois if not p.geolocalizado]
    if not pendientes:
        return
    log.info("geocodificando %d registros sin coordenadas", len(pendientes))
    g = geocode.Geocodificador()
    for i, p in enumerate(pendientes[: limite or len(pendientes)]):
        if not p.direccion:
            continue
        r = g.geocodifica(p.direccion, p.municipio, p.provincia)
        if r:
            # La calidad y la fuente se anotan siempre, también cuando la
            # coordenada se descarta: son la explicación del hueco. Sin ellas
            # el registro aparecería como "no se encontró", que es falso y
            # manda a buscar en el sitio equivocado.
            p.geocode_fuente, p.geocode_calidad = r.fuente, r.calidad
            # El geocodificador oficial sabe en qué municipio ha caído el
            # punto. Es mejor dato que el que traiga la fuente, y es la clave
            # con la que se cruzan las capas.
            if r.cod_ine and not p.cod_ine:
                p.cod_ine = r.cod_ine
            if r.municipio and not p.municipio:
                p.municipio = r.municipio
            if r.calidad in geocode.CALIDADES_NO_UBICABLES:
                log.warning(
                    "solo a nivel de %s, se deja sin coordenada: %s (%s)",
                    r.calidad, p.direccion, p.municipio,
                )
            else:
                p.lat, p.lon = r.lat, r.lon
        if (i + 1) % 100 == 0:
            log.info("  %d/%d", i + 1, len(pendientes))


def cliente_supabase() -> Supabase:
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise SystemExit("faltan SUPABASE_URL o SUPABASE_SERVICE_KEY")
    return Supabase(url, key)


def escribe(pois: list[Poi], fuente: str, prueba: bool) -> None:
    res = resumen(pois)
    log.info("resumen: %s", json.dumps(res, ensure_ascii=False))

    # Un extractor que devuelve cero registros casi nunca significa "no hay
    # datos": significa que la fuente cambió y el parser ya no encaja. Se
    # falla en vez de escribir un vacío, porque un upsert vacío no rompe nada
    # visiblemente pero deja el mapa sin esa capa hasta que alguien lo note.
    if not pois:
        raise SystemExit(f"{fuente}: 0 registros. Se aborta sin escribir.")

    destino = SALIDA / f"{fuente}.ndjson"
    a_ndjson(pois, destino)
    (SALIDA / f"{fuente}.resumen.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if prueba:
        log.info("modo prueba: no se escribe en Supabase. Revisa %s", destino)
        return

    sb = cliente_supabase()
    try:
        n = sb.upsert_pois(pois)
        sb.registra_ingesta(fuente, os.environ.get("NOOK_AMBITO", "ES"), res, "ok")
        log.info("escritos %d registros en Supabase", n)
    except Exception as e:  # noqa: BLE001 - se quiere registrar y relanzar
        sb.registra_ingesta(fuente, os.environ.get("NOOK_AMBITO", "ES"), res, "error", str(e))
        raise


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    ap = argparse.ArgumentParser(description="Ingesta de datos de Nook")
    ap.add_argument("comando", choices=["reconocimiento", "bancos", "overture", "notarias"])
    ap.add_argument("--prueba", action="store_true", help="no escribe en Supabase")
    ap.add_argument("--entrada", type=pathlib.Path, help="carpeta de ficheros de entrada (bancos)")
    ap.add_argument("--bbox", help="min_lat,min_lon,max_lat,max_lon (overture); varias cajas con ';'")
    ap.add_argument("--sin-geocodificar", action="store_true")
    args = ap.parse_args(argv)

    SALIDA.mkdir(parents=True, exist_ok=True)

    if args.comando == "reconocimiento":
        from nook.recon import explora

        hallazgos = explora(RAIZ / "datos" / "recon")
        for h in hallazgos:
            log.info("%-18s %-14s %d rutas candidatas", h.nombre, h.estado, len(h.rutas_api))
        return 0

    if args.comando == "bancos":
        # Carpeta versionada, no `datos/entrada/` (que está en .gitignore): el
        # CSV del Banco de España se descarga a mano y viaja en el
        # repositorio, porque ni Actions alcanza app.bde.es ni existe un
        # endpoint de descarga. Ver datos/bde/README.md.
        entrada = args.entrada or (RAIZ / "datos" / "bde")
        pois = bancos.desde_carpeta(entrada)

    elif args.comando == "overture":
        cajas = None
        if args.bbox:
            # Varias cajas separadas por ';'. Una comunidad autónoma no cabe
            # siempre en un rectángulo razonable, y pedir España de una vez
            # arrastra medio Atlántico: es más barato encadenar cajas
            # ajustadas que filtrar después lo que sobra.
            cajas = []
            for trozo in args.bbox.split(";"):
                trozo = trozo.strip()
                if not trozo:
                    continue
                a, b, c, d = (float(x) for x in trozo.split(","))
                cajas.append(overture.BBox(a, b, c, d))
        pois = overture.extrae(cajas)

    else:
        pois = notarias.extrae()

    # Antes de geocodificar, no después. La geocodificación es lo que hace
    # que una ingesta dure setenta minutos, y no tiene ningún sentido pagarlos
    # para descubrir al final que la base de datos no admite lo que traemos.
    if not args.prueba and pois:
        cliente_supabase().comprueba_tipos(pois)

    if not args.sin_geocodificar:
        geocodifica_pendientes(pois)

    pois, fusionados = deduplica(pois)
    if fusionados:
        log.info("deduplicación: %d registros fundidos", fusionados)

    # Después de deduplicar, no antes: deduplica puede dejar dos registros con
    # la misma clave si no llegó a fundirlos, y lo que no puede salir de aquí
    # es un lote con claves repetidas.
    pois, repetidos = colapsa_por_id(pois)
    if repetidos:
        log.info("claves repetidas en origen: %d registros colapsados", repetidos)

    # La provincia que traen las fuentes no vale para agrupar: Overture la
    # publica como texto libre y en un mismo volcado salen "Tarragona",
    # "Provincia de Tarragona" y "tarragona". Se deduce del código postal,
    # que en España identifica la provincia sin excepciones.
    corregidas, sin_deducir = geografia.normaliza(pois)
    log.info(
        "provincias normalizadas: %d corregidas, %d sin código postal utilizable",
        corregidas, sin_deducir,
    )

    escribe(pois, args.comando, prueba=args.prueba)
    return 0


if __name__ == "__main__":
    sys.exit(main())
