"""
Normalizacion geografica.

El campo `provincia` que traen las fuentes no vale para agrupar: en un mismo
volcado de Overture salen "Tarragona", "Provincia de Tarragona" y "tarragona",
Cataluna aparece como "Catalonia", "Catalunya" y "CT", y hay barrios de Madrid
metidos en el campo de provincia. Con eso, cualquier recuento sale fragmentado
y cruzar fuentes por nombre pierde los que se escriben distinto.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nook.geografia import (  # noqa: E402
    PROVINCIAS,
    cod_provincia_desde_cp,
    normaliza,
    provincia_desde_cp,
)
from nook.modelo import Poi  # noqa: E402


class TestProvinciaDesdeCP:
    @pytest.mark.parametrize(
        "cp, esperado",
        [
            ("08201", "Barcelona"),
            ("28006", "Madrid"),
            ("43001", "Tarragona"),
            ("17001", "Girona"),
            ("  46001  ", "Valencia/València"),   # con espacios de sobra
            ("51001", "Ceuta"),
            ("52001", "Melilla"),
        ],
    )
    def test_deduce_la_provincia(self, cp, esperado):
        assert provincia_desde_cp(cp) == esperado

    @pytest.mark.parametrize("cp", [None, "", "0820", "abcde", "99999", "00123"])
    def test_lo_que_no_se_puede_deducir_no_se_inventa(self, cp):
        assert provincia_desde_cp(cp) is None
        assert cod_provincia_desde_cp(cp) is None

    def test_estan_las_52(self):
        assert len(PROVINCIAS) == 52
        assert all(len(k) == 2 and k.isdigit() for k in PROVINCIAS)


class TestNormaliza:
    def _poi(self, cp=None, provincia=None):
        return Poi(tipo="banco", fuente="overture", fuente_id=f"x{cp}{provincia}",
                   nombre="N", cp=cp, provincia=provincia)

    def test_corrige_los_nombres_de_overture(self):
        # Los cinco casos reales que aparecieron en el informe de cobertura.
        pois = [
            self._poi("43001", "Provincia de Tarragona"),
            self._poi("17001", "Gerona"),
            self._poi("25001", "Lérida"),
            self._poi("08001", "Catalonia"),
            self._poi("28001", "Arganzuela - Imperial"),
        ]
        corregidas, _ = normaliza(pois)
        assert corregidas == 5
        assert [p.provincia for p in pois] == [
            "Tarragona", "Girona", "Lleida", "Barcelona", "Madrid",
        ]

    def test_no_toca_lo_que_ya_esta_bien(self):
        pois = [self._poi("08201", "Barcelona")]
        corregidas, _ = normaliza(pois)
        assert corregidas == 0
        assert pois[0].provincia == "Barcelona"

    def test_sin_codigo_postal_se_deja_como_esta(self):
        # Preferible una provincia dudosa a ninguna: el dato original puede
        # ser correcto, y borrarlo seria perder informacion.
        pois = [self._poi(None, "Vizcaya")]
        corregidas, sin_deducir = normaliza(pois)
        assert corregidas == 0 and sin_deducir == 0
        assert pois[0].provincia == "Vizcaya"

    def test_cuenta_los_que_se_quedan_sin_nada(self):
        pois = [self._poi(None, None)]
        _, sin_deducir = normaliza(pois)
        assert sin_deducir == 1


class TestCuadraConElINE:
    def test_los_codigos_coinciden_con_el_catalogo(self):
        """
        La tabla de provincias y el catalogo del INE tienen que hablar de las
        mismas provincias. Si el INE anadiera o renombrara una y la tabla no
        se actualizara, el cruce por provincia empezaria a fallar en silencio.
        """
        catalogo = (
            pathlib.Path(__file__).resolve().parents[2] / "src" / "data" / "municipios.json"
        )
        if not catalogo.exists():
            pytest.skip("falta el catalogo; se genera con scripts/catalogo_municipios.py")
        import json

        d = json.loads(catalogo.read_text(encoding="utf-8"))
        del_catalogo = {p["cod"] for c in d["ccaa"] for p in c["provincias"]}
        assert del_catalogo == set(PROVINCIAS), (
            f"solo en el catalogo: {sorted(del_catalogo - set(PROVINCIAS))}; "
            f"solo en la tabla: {sorted(set(PROVINCIAS) - del_catalogo)}"
        )
