"""
Motor de calor de Nook.

Convierte una nube de puntos (notarías = competencia, bancos / inmobiliarias /
despachos = demanda) en un score por celda hexagonal H3.

Modelo
------
Para cada celda `c` y cada punto `p` a distancia `d` metros:

    aportacion(p, c) = peso[tipo(p)] * exp( - d^2 / (2 * sigma^2) )

`sigma` (bandwidth) es la distancia a la que un punto deja de influir de forma
apreciable: a 1 sigma conserva el 61 % de su peso, a 2 sigma el 14 %, a 3 sigma
el 1 %. Con sigma = 600 m, la influencia de un banco muere sobre los 1,8 km, que
es aproximadamente lo que una persona recorre a pie para ir a una notaría.

Se usa un kernel gaussiano en vez de un simple "contar dentro de un radio"
porque este último produce bordes duros y artefactos visuales feos: dos celdas
contiguas pueden diferir en un punto entero solo porque un banco cae justo a un
lado de la circunferencia. El gaussiano decae de forma continua.

La demanda y la competencia se calculan por separado y se combinan al final,
para poder enseñarlas como capas independientes en el front y para que el
notario entienda *por qué* una zona puntúa alto.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import h3
import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree

# ETRS89 / UTM 30N: sistema métrico oficial para la España peninsular.
# Se trabaja en metros porque el kernel se define en metros.
_TO_M = Transformer.from_crs("EPSG:4326", "EPSG:25830", always_xy=True)

# Más allá de 3 sigma la aportación es < 1,2 % del peso: se recorta el cálculo
# ahí para que el KDTree no tenga que mirar toda España por cada celda.
CORTE_SIGMAS = 3.0

PESOS_POR_DEFECTO: dict[str, float] = {
    "notaria": -3.0,
    "banco": 1.0,
    "inmobiliaria": 1.0,
    "abogados": 1.0,
    "gestoria": 1.0,
}


@dataclass
class Config:
    resolucion: int = 9          # ~174 m de arista, ~0,10 km2 por celda
    bandwidth_m: float = 600.0
    pesos: dict[str, float] = field(default_factory=lambda: dict(PESOS_POR_DEFECTO))
    peso_poblacion: float = 1.0
    # Cuánto castiga la competencia una vez demanda y competencia están en la
    # misma escala 0-1. 0 = ignorar las notarías existentes; 1 = una zona
    # saturada anula por completo su demanda. Ver nota en `calcular`.
    peso_competencia: float = 0.7


@dataclass
class Punto:
    tipo: str
    lat: float
    lon: float


def celdas_de_poligono(poligono_lonlat: list[tuple[float, float]], resolucion: int) -> list[str]:
    """Rejilla H3 que cubre un polígono dado como lista de (lon, lat)."""
    shape = h3.LatLngPoly([(lat, lon) for lon, lat in poligono_lonlat])
    return list(h3.polygon_to_cells(shape, resolucion))


def _proyectar(lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    x, y = _TO_M.transform(lons, lats)
    return np.column_stack([x, y])


def calcular(
    celdas: list[str],
    puntos: list[Punto],
    cfg: Config | None = None,
    poblacion: dict[str, float] | None = None,
) -> dict[str, dict]:
    """
    Devuelve {h3: {"demanda", "competencia", "score", "detalle": {tipo: aportacion}}}.

    `score` está normalizado 0-100 dentro del conjunto de celdas recibido, es
    decir, es relativo al municipio analizado: un 100 en Sabadell y un 100 en
    Madrid no son el mismo valor absoluto. Es lo que quiere el notario, que
    compara ubicaciones dentro de la ciudad donde ya ha decidido instalarse.
    """
    cfg = cfg or Config()
    if not celdas:
        return {}

    centros = np.array([h3.cell_to_latlng(c) for c in celdas])        # (n, 2) lat, lon
    xy_celdas = _proyectar(centros[:, 1], centros[:, 0])

    sigma = cfg.bandwidth_m
    radio = CORTE_SIGMAS * sigma
    dos_sigma2 = 2.0 * sigma * sigma

    aporte: dict[str, np.ndarray] = {}
    arbol_celdas = cKDTree(xy_celdas)

    for tipo in {p.tipo for p in puntos}:
        del_tipo = [p for p in puntos if p.tipo == tipo]
        xy_pts = _proyectar(
            np.array([p.lon for p in del_tipo]), np.array([p.lat for p in del_tipo])
        )
        acumulado = np.zeros(len(celdas))
        # Para cada punto, solo las celdas dentro del radio de corte.
        for idx_pt, vecinas in enumerate(arbol_celdas.query_ball_point(xy_pts, r=radio)):
            if not vecinas:
                continue
            vecinas = np.asarray(vecinas)
            d2 = np.sum((xy_celdas[vecinas] - xy_pts[idx_pt]) ** 2, axis=1)
            acumulado[vecinas] += np.exp(-d2 / dos_sigma2)
        aporte[tipo] = acumulado

    demanda = np.zeros(len(celdas))
    competencia = np.zeros(len(celdas))
    for tipo, acumulado in aporte.items():
        peso = cfg.pesos.get(tipo, 0.0)
        if peso >= 0:
            demanda += peso * acumulado
        else:
            competencia += abs(peso) * acumulado

    if poblacion:
        pob = np.array([poblacion.get(c, 0.0) for c in celdas])
        if pob.max() > 0:
            demanda += cfg.peso_poblacion * (pob / pob.max())

    # --- Combinación -------------------------------------------------------
    # Restar la competencia de la demanda *en bruto* no funciona: las dos
    # magnitudes tienen escalas distintas (hay ~10 veces más bancos que
    # notarías en una ciudad, así que la demanda domina siempre) y el
    # resultado acaba siendo un mapa de densidad comercial, no un mapa de
    # demanda insatisfecha. El máximo cae justo encima del casco antiguo,
    # que es exactamente donde ya están todas las notarías: inútil para el
    # notario que busca hueco.
    #
    # Se normalizan las dos capas por separado a 0-1 dentro del municipio y
    # solo después se combinan. Así `peso_competencia` significa algo
    # interpretable: "cuánto descuento por estar en zona saturada".
    dem_n = _normalizar(demanda)
    comp_n = _normalizar(competencia)
    bruto = dem_n - cfg.peso_competencia * comp_n
    # Min-max simple, sin recortar colas: las capas de entrada ya vienen
    # recortadas y aquí interesa conservar el orden exacto entre las mejores
    # celdas — si se recorta otra vez, la docena de celdas punteras empatan
    # todas a 100 y el ranking de ubicaciones deja de servir.
    score = _minmax(bruto) * 100.0

    return {
        c: {
            "demanda": float(demanda[i]),
            "competencia": float(competencia[i]),
            "demanda_norm": float(dem_n[i]),
            "competencia_norm": float(comp_n[i]),
            "score": float(score[i]),
            "detalle": {t: float(aporte[t][i]) for t in aporte},
        }
        for i, c in enumerate(celdas)
    }


def _normalizar(v: np.ndarray) -> np.ndarray:
    """
    Lleva un vector a 0-1 recortando por los percentiles 2 y 98.

    Sin el recorte, un único centro urbano muy denso aplasta el resto del mapa
    contra el 0 y el heatmap se ve plano fuera del centro. Recortando las colas
    se conserva el contraste en las zonas intermedias, que son justo donde el
    notario tiene que decidir.
    """
    if len(v) == 0:
        return v
    lo, hi = np.percentile(v, 2), np.percentile(v, 98)
    if hi - lo < 1e-9:
        return np.full_like(v, 0.5)
    return np.clip((v - lo) / (hi - lo), 0, 1)


def _minmax(v: np.ndarray) -> np.ndarray:
    lo, hi = v.min(), v.max()
    if hi - lo < 1e-9:
        return np.full_like(v, 0.5)
    return (v - lo) / (hi - lo)
