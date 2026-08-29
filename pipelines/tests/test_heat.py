"""
El motor de calor, y sobre todo: que las dos implementaciones coincidan.

`src/lib/heat.ts` corre en el navegador para que los sliders recalculen en
vivo, y `nook/heat.py` hace el mismo cálculo para lotes e informes en PDF. Que
den el mismo número es un requisito del producto: si el mapa que ve el notario
y el informe que se le entrega discrepan, el informe no vale nada.

Hasta el 29/08/2026 no lo comprobaba nada, y ya se habían separado: la versión
de Python tenía un término de población que la de TypeScript no implementa.
Peor aún, `heat.py` ni siquiera podía importarse —h3, numpy, pyproj y scipy no
estaban en `requirements.txt`—, así que nunca se había ejecutado en CI.

El fixture lo genera `scripts/exportar_heat_ts.mjs` ejecutando el motor de
TypeScript de verdad. Si se toca cualquiera de los dos motores hay que
regenerarlo; CI comprueba que está al día.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

np = pytest.importorskip("numpy")
h3 = pytest.importorskip("h3")
pytest.importorskip("scipy")

from nook.heat import Config, Punto, calcular, celdas_de_poligono  # noqa: E402

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "heat_ts.json"

# Tolerancia. No se exige igualdad binaria: son dos implementaciones de coma
# flotante distintas, con proyecciones y órdenes de suma que no tienen por qué
# coincidir bit a bit. Pero el score va de 0 a 100 y una diferencia de 0,01
# jamás cambia una decisión de ubicación, mientras que una de 1,0 sí podría
# alterar el orden de las mejores celdas.
TOLERANCIA_SCORE = 0.01


@pytest.fixture(scope="module")
def caso_ts():
    if not FIXTURE.exists():
        pytest.skip(f"falta {FIXTURE}; se genera con scripts/exportar_heat_ts.mjs")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _puntos(datos) -> list[Punto]:
    return [
        Punto(tipo=p["categoria"], lat=p["lat"], lon=p["lon"])
        for p in datos["puntos"]
    ]


class TestEquivalenciaConElMotorDelNavegador:
    def test_el_fixture_trae_varios_casos(self, caso_ts):
        # Un solo caso no distingue un motor correcto de uno que ignora la
        # configuración y siempre devuelve lo mismo.
        assert len(caso_ts["casos"]) >= 4

    @pytest.mark.parametrize(
        "nombre",
        ["por-defecto", "sin-competencia", "competencia-total", "pesos-dispares", "rejilla-fina"],
    )
    def test_mismo_score_que_typescript(self, caso_ts, nombre):
        caso = caso_ts["casos"][nombre]
        cfg_ts = caso["config"]

        celdas = list(caso["celdas"].keys())
        cfg = Config(
            resolucion=cfg_ts["resolucion"],
            bandwidth_m=float(cfg_ts["bandwidthM"]),
            pesos={
                "notaria": -1.0,  # el signo marca competencia; la magnitud no
                                  # importa porque se normaliza aparte
                **{k: float(v) for k, v in cfg_ts["pesos"].items()},
            },
            peso_competencia=float(cfg_ts["pesoCompetencia"]),
        )
        py = calcular(celdas, _puntos(caso_ts), cfg)

        assert set(py) == set(caso["celdas"]), "los dos motores no cubren las mismas celdas"

        peores = sorted(
            ((abs(py[h]["score"] - v["score"]), h) for h, v in caso["celdas"].items()),
            reverse=True,
        )[:3]
        diferencia = peores[0][0]
        assert diferencia <= TOLERANCIA_SCORE, (
            f"[{nombre}] los motores discrepan hasta {diferencia:.4f} puntos de score. "
            f"Peores celdas: {[(h, round(d, 4)) for d, h in peores]}"
        )

    def test_el_orden_de_las_mejores_celdas_coincide(self, caso_ts):
        # Lo que se le enseña al notario es un ranking. Que los scores casi
        # coincidan no basta si el orden cambia.
        caso = caso_ts["casos"]["por-defecto"]
        cfg_ts = caso["config"]
        celdas = list(caso["celdas"].keys())
        cfg = Config(
            resolucion=cfg_ts["resolucion"],
            bandwidth_m=float(cfg_ts["bandwidthM"]),
            pesos={"notaria": -1.0, **{k: float(v) for k, v in cfg_ts["pesos"].items()}},
            peso_competencia=float(cfg_ts["pesoCompetencia"]),
        )
        py = calcular(celdas, _puntos(caso_ts), cfg)

        top_py = [h for h, _ in sorted(py.items(), key=lambda kv: -kv[1]["score"])[:10]]
        top_ts = [h for h, _ in sorted(caso["celdas"].items(), key=lambda kv: -kv[1]["score"])[:10]]
        assert top_py == top_ts


class TestModelo:
    """
    El comportamiento que el producto promete, con independencia del otro
    motor. Ver el punto 1 de CLAUDE.md.
    """

    def _celdas(self):
        # Un cuadrado pequeño alrededor de Sabadell.
        poligono = [(2.09, 41.53), (2.13, 41.53), (2.13, 41.56), (2.09, 41.56), (2.09, 41.53)]
        return celdas_de_poligono(poligono, 9)

    def test_sin_puntos_no_hay_score(self):
        r = calcular(self._celdas(), [])
        assert all(c["demanda"] == 0 for c in r.values())

    def test_sin_celdas_devuelve_vacio(self):
        assert calcular([], [Punto(tipo="banco", lat=41.54, lon=2.11)]) == {}

    def test_la_competencia_desplaza_la_mejor_ubicacion(self):
        """
        Lo que hace util a la herramienta: entre dos zonas con demanda
        parecida, gana la que no tiene notaria al lado.

        No se comprueba que baje el score de la celda ocupada, porque con
        normalizacion min-max la mejor celda siempre vale 100 y la
        comprobacion pasaria sola. Lo que importa es cual es la mejor.
        """
        celdas = self._celdas()
        zona_a = [Punto(tipo="banco", lat=41.545, lon=2.105) for _ in range(6)]
        zona_b = [Punto(tipo="banco", lat=41.538, lon=2.120) for _ in range(6)]

        sin_notaria = calcular(celdas, zona_a + zona_b)
        mejor_sin = max(sin_notaria, key=lambda h: sin_notaria[h]["score"])

        # Se planta una notaria encima de la zona que ganaba.
        lat_mejor, lon_mejor = h3.cell_to_latlng(mejor_sin)
        con_notaria = calcular(
            celdas, zona_a + zona_b + [Punto(tipo="notaria", lat=lat_mejor, lon=lon_mejor)]
        )
        mejor_con = max(con_notaria, key=lambda h: con_notaria[h]["score"])

        assert mejor_con != mejor_sin, "la notaria no ha desplazado la recomendacion"
        # Y la celda ocupada ya no puede ser la mejor.
        assert con_notaria[mejor_sin]["score"] < con_notaria[mejor_con]["score"]

    def test_peso_competencia_cero_ignora_las_notarias(self):
        celdas = self._celdas()
        demanda = [Punto(tipo="banco", lat=41.545, lon=2.11)]
        cfg = Config(peso_competencia=0.0)
        a = calcular(celdas, demanda, cfg)
        b = calcular(celdas, demanda + [Punto(tipo="notaria", lat=41.545, lon=2.11)], cfg)
        assert all(abs(a[h]["score"] - b[h]["score"]) < 1e-9 for h in a)

    def test_el_score_va_de_0_a_100(self):
        celdas = self._celdas()
        puntos = [
            Punto(tipo="banco", lat=41.545, lon=2.11),
            Punto(tipo="inmobiliaria", lat=41.535, lon=2.12),
            Punto(tipo="notaria", lat=41.55, lon=2.10),
        ]
        r = calcular(celdas, puntos)
        assert all(0.0 <= c["score"] <= 100.0 for c in r.values())
        assert max(c["score"] for c in r.values()) == pytest.approx(100.0)

    def test_un_punto_lejano_no_aporta(self):
        # Más allá de tres sigmas la aportación es despreciable. Si no fuera
        # así, un punto en la otra punta de la ciudad movería el mapa entero.
        celdas = self._celdas()
        cerca = calcular(celdas, [Punto(tipo="banco", lat=41.545, lon=2.11)])
        lejos = calcular(celdas, [Punto(tipo="banco", lat=41.545, lon=2.11),
                                  Punto(tipo="banco", lat=40.4, lon=-3.7)])
        h = max(cerca, key=lambda x: cerca[x]["demanda"])
        assert cerca[h]["demanda"] == pytest.approx(lejos[h]["demanda"], rel=1e-9)

    def test_el_detalle_reparte_por_tipo(self):
        celdas = self._celdas()
        r = calcular(celdas, [
            Punto(tipo="banco", lat=41.545, lon=2.11),
            Punto(tipo="gestoria", lat=41.545, lon=2.11),
        ])
        h = max(r, key=lambda x: r[x]["demanda"])
        assert set(r[h]["detalle"]) == {"banco", "gestoria"}
        assert all(v > 0 for v in r[h]["detalle"].values())
