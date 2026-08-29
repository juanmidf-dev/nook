"""
Pruebas de la extracción de Overture.

La consulta SQL se ejecuta contra un parquet local construido en el propio
test con la misma forma que el dataset real —estructuras anidadas `names`,
`categories`, `addresses`, geometría en WKB y la caja `bbox`—. Es la única
manera de comprobar que el SQL y el mapeo funcionan sin bajarse cientos de
gigas ni depender de que S3 responda.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nook.fuentes.overture import (
    CATEGORIAS,
    CATEGORIAS_EXCLUIDAS,
    BBox,
    clasifica,
    consulta_sql,
    expresion_geometria,
    fila_a_poi,
)

# duckdb solo hace falta para las pruebas que ejecutan SQL. La clasificacion
# de categorias y el mapeo de filas son logica pura, y saltarselos por no
# tener duckdb instalado dejaba sin cubrir justo lo que mas se toca. Windows
# con Python 3.14, por ejemplo, no tiene rueda de duckdb 1.1.3.
try:
    import duckdb
except ImportError:  # pragma: no cover
    duckdb = None


def _exige_duckdb():
    if duckdb is None:
        pytest.skip("duckdb no está instalado en este entorno")


class TestClasifica:
    def test_categoria_principal(self):
        assert clasifica("real_estate_agent", None) == "inmobiliaria"
        assert clasifica("lawyer", None) == "abogados"
        assert clasifica("banks", None) == "banco"

    def test_mira_tambien_las_alternativas(self):
        # Muchos despachos se clasifican como servicios profesionales y solo
        # llevan "lawyer" en la lista secundaria.
        assert clasifica("professional_services", ["lawyer"]) == "abogados"

    def test_ignora_lo_que_no_interesa(self):
        assert clasifica("restaurant", ["bar"]) is None
        assert clasifica(None, None) is None


class TestFilaAPoi:
    def base(self, **kw):
        fila = {
            "id": "ov-1",
            "nombre": "Finques Exemple",
            "categoria": "real_estate_agent",
            "categorias_alt": None,
            "confianza": 0.9,
            "direccion": "CL SANT JOAN 39",
            "cp": "08202",
            "municipio": "Sabadell",
            "region": "Barcelona",
            "web": "https://ejemplo.test",
            "telefono": "937000000",
            "lat": 41.5474,
            "lon": 2.1099,
        }
        fila.update(kw)
        return fila

    def test_mapea_los_campos(self):
        p = fila_a_poi(self.base())
        assert p is not None
        assert p.tipo == "inmobiliaria"
        assert p.fuente == "overture"
        assert p.fuente_id == "ov-1"
        assert p.direccion == "Calle Sant Joan 39"
        assert p.geocode_calidad == "portal"

    def test_descarta_categorias_ajenas(self):
        assert fila_a_poi(self.base(categoria="restaurant")) is None

    def test_descarta_sin_coordenadas(self):
        assert fila_a_poi(self.base(lat=None)) is None

    def test_descarta_sin_nombre(self):
        assert fila_a_poi(self.base(nombre="  ")) is None

    def test_saca_el_cp_de_la_direccion_si_falta(self):
        p = fila_a_poi(self.base(cp=None, direccion="CL SANT JOAN 39, 08202"))
        assert p.cp == "08202"


class TestConsultaSQL:
    """La consulta real, contra un parquet con la forma del dataset."""

    @staticmethod
    def _conexion_espacial():
        """
        La extensión espacial de DuckDB se descarga la primera vez. En un
        entorno sin salida a internet no está disponible, así que este test se
        salta ahí y se ejecuta de verdad en el runner de Actions, que sí tiene
        red. Las comprobaciones que no dependen de ella —acceso a las
        estructuras anidadas y filtros— están en `test_filtros_sin_spatial`,
        que sí corre en cualquier sitio.
        """
        _exige_duckdb()
        con = duckdb.connect()
        try:
            con.execute("INSTALL spatial; LOAD spatial;")
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"extensión spatial de DuckDB no disponible: {e}")
        return con

    @pytest.fixture
    def parquet(self, tmp_path):
        con = self._conexion_espacial()
        destino = tmp_path / "places.parquet"
        con.execute(
            f"""
            COPY (
              SELECT * FROM (VALUES
                ('ov-1', {{'primary': 'Finques Exemple'}},
                 {{'primary': 'real_estate_agent', 'alternate': ['agency']}}, 0.91::DOUBLE,
                 [{{'freeform': 'CL SANT JOAN 39', 'postcode': '08202',
                    'locality': 'Sabadell', 'region': 'Barcelona', 'country': 'ES'}}],
                 ['https://ejemplo.test'], ['937000000'], ['hola@ejemplo.test'],
                 ST_AsWKB(ST_Point(2.1099, 41.5474)),
                 {{'xmin': 2.1099, 'xmax': 2.1099, 'ymin': 41.5474, 'ymax': 41.5474}}),
                ('ov-5', {{'primary': 'Immobilier Exemple'}},
                 {{'primary': 'real_estate_agent', 'alternate': [NULL]}}, 0.95::DOUBLE,
                 [{{'freeform': 'RUE DE LA PAIX 1', 'postcode': '66000',
                    'locality': 'Perpignan', 'region': 'Pyrenees-Orientales', 'country': 'FR'}}],
                 [NULL], [NULL], [NULL],
                 ST_AsWKB(ST_Point(2.1080, 41.5460)),
                 {{'xmin': 2.1080, 'xmax': 2.1080, 'ymin': 41.5460, 'ymax': 41.5460}}),
                ('ov-2', {{'primary': 'Bufete Exemple'}},
                 {{'primary': 'professional_services', 'alternate': ['lawyer']}}, 0.80::DOUBLE,
                 [{{'freeform': 'CL ADVOCATS 1', 'postcode': '08201',
                    'locality': 'Sabadell', 'region': 'Barcelona', 'country': 'ES'}}],
                 [NULL], [NULL], [NULL],
                 ST_AsWKB(ST_Point(2.1050, 41.5500)),
                 {{'xmin': 2.1050, 'xmax': 2.1050, 'ymin': 41.5500, 'ymax': 41.5500}}),
                ('ov-3', {{'primary': 'Baja confianza'}},
                 {{'primary': 'real_estate_agent', 'alternate': [NULL]}}, 0.20::DOUBLE,
                 [{{'freeform': 'CL DUDOSA 9', 'postcode': '08201',
                    'locality': 'Sabadell', 'region': 'Barcelona', 'country': 'ES'}}],
                 [NULL], [NULL], [NULL],
                 ST_AsWKB(ST_Point(2.1060, 41.5510)),
                 {{'xmin': 2.1060, 'xmax': 2.1060, 'ymin': 41.5510, 'ymax': 41.5510}}),
                ('ov-4', {{'primary': 'Fuera de la caja'}},
                 {{'primary': 'real_estate_agent', 'alternate': [NULL]}}, 0.95::DOUBLE,
                 [{{'freeform': 'CL LEJOS 1', 'postcode': '28001',
                    'locality': 'Madrid', 'region': 'Madrid', 'country': 'ES'}}],
                 [NULL], [NULL], [NULL],
                 ST_AsWKB(ST_Point(-3.7038, 40.4168)),
                 {{'xmin': -3.7038, 'xmax': -3.7038, 'ymin': 40.4168, 'ymax': 40.4168}})
              ) AS t(id, names, categories, confidence, addresses, websites, phones, emails, geometry, bbox)
            ) TO '{destino}' (FORMAT PARQUET)
            """
        )
        return destino

    def test_detecta_el_tipo_de_la_geometria(self, parquet):
        con = self._conexion_espacial()
        # No se fija cuál de las dos sale: depende de la versión de la
        # extensión spatial, que se descarga en ejecución y no está fijada
        # como sí lo está la de duckdb. Lo que importa es que la consulta
        # armada con lo que devuelva se ejecute.
        expr = expresion_geometria(con, str(parquet))
        assert expr in ("geometry", "ST_GeomFromWKB(geometry)")
        sql = consulta_sql(BBox.de_centro(41.5431, 2.1097, 6000), expr)
        con.execute(sql.replace("{origen}", str(parquet))).fetchall()

    def test_origen_ilegible_asume_wkb(self):
        _exige_duckdb()
        # Una ruta que no existe no debe propagar la excepción desde aquí: el
        # error se entiende mucho mejor cuando lo da la consulta de verdad.
        assert (
            expresion_geometria(duckdb.connect(), "/no/existe/*.parquet")
            == "ST_GeomFromWKB(geometry)"
        )

    def test_filtra_y_transforma(self, parquet):
        con = self._conexion_espacial()
        caja = BBox.de_centro(41.5431, 2.1097, 6000)
        # Se pregunta el tipo en vez de fijarlo: escrito el parquet con
        # ST_AsWKB, DuckDB lo relee como GEOMETRY si su extensión spatial
        # entiende los metadatos GeoParquet, y entonces envolverlo otra vez
        # en ST_GeomFromWKB no encaja con ninguna sobrecarga.
        geometria = expresion_geometria(con, str(parquet))
        sql = consulta_sql(caja, geometria).replace("{origen}", str(parquet))
        filas = con.execute(sql).fetchall()
        columnas = [d[0] for d in con.description]
        pois = [p for f in filas if (p := fila_a_poi(dict(zip(columnas, f)))) is not None]

        nombres = {p.nombre for p in pois}
        # Dentro de la caja y con confianza suficiente.
        assert "Finques Exemple" in nombres
        # Clasificado por la categoría alternativa.
        assert "Bufete Exemple" in nombres
        # Confianza por debajo del umbral: Overture arrastra registros
        # automáticos de baja calidad y para lo que se vende importa más la
        # precisión que el volumen.
        assert "Baja confianza" not in nombres
        # Madrid queda fuera de la caja de Sabadell.
        assert "Fuera de la caja" not in nombres
        # Y este cae dentro de la caja y tiene confianza de sobra, pero es
        # francés: lo descarta el filtro de país, no la geometría.
        assert "Immobilier Exemple" not in nombres

        bufete = next(p for p in pois if p.nombre == "Bufete Exemple")
        assert bufete.tipo == "abogados"
        assert bufete.lat == pytest.approx(41.5500, abs=1e-4)
        assert bufete.lon == pytest.approx(2.1050, abs=1e-4)


class TestFiltrosSinSpatial:
    """
    Misma consulta, con la geometría sustituida por columnas planas.

    Comprueba lo que de verdad se rompe cuando Overture cambia algo: el
    acceso a las estructuras anidadas (`names.primary`, `categories.primary`,
    `addresses[1].freeform`) y los filtros de caja y de confianza. Corre sin
    la extensión espacial, así que se ejecuta también en entornos sin red.
    """

    @pytest.fixture
    def parquet(self, tmp_path):
        _exige_duckdb()
        con = duckdb.connect()
        destino = tmp_path / "places_planas.parquet"
        con.execute(
            f"""
            COPY (
              SELECT * FROM (VALUES
                ('ov-1', {{'primary': 'Finques Exemple'}},
                 {{'primary': 'real_estate_agent', 'alternate': ['agency']}}, 0.91::DOUBLE,
                 [{{'freeform': 'CL SANT JOAN 39', 'postcode': '08202',
                    'locality': 'Sabadell', 'region': 'Barcelona', 'country': 'ES'}}],
                 ['https://ejemplo.test'], ['937000000'], ['hola@ejemplo.test'], 41.5474, 2.1099,
                 {{'xmin': 2.1099, 'xmax': 2.1099, 'ymin': 41.5474, 'ymax': 41.5474}}),
                ('ov-3', {{'primary': 'Baja confianza'}},
                 {{'primary': 'real_estate_agent', 'alternate': [NULL]}}, 0.20::DOUBLE,
                 [{{'freeform': 'CL DUDOSA 9', 'postcode': '08201',
                    'locality': 'Sabadell', 'region': 'Barcelona', 'country': 'ES'}}],
                 [NULL], [NULL], [NULL], 41.5510, 2.1060,
                 {{'xmin': 2.1060, 'xmax': 2.1060, 'ymin': 41.5510, 'ymax': 41.5510}}),
                ('ov-4', {{'primary': 'Fuera de la caja'}},
                 {{'primary': 'real_estate_agent', 'alternate': [NULL]}}, 0.95::DOUBLE,
                 [{{'freeform': 'CL LEJOS 1', 'postcode': '28001',
                    'locality': 'Madrid', 'region': 'Madrid', 'country': 'ES'}}],
                 [NULL], [NULL], [NULL], 40.4168, -3.7038,
                 {{'xmin': -3.7038, 'xmax': -3.7038, 'ymin': 40.4168, 'ymax': 40.4168}}),
                ('ov-5', NULL,
                 {{'primary': 'real_estate_agent', 'alternate': [NULL]}}, 0.99::DOUBLE,
                 [{{'freeform': 'CL SIN NOMBRE 1', 'postcode': '08201',
                    'locality': 'Sabadell', 'region': 'Barcelona', 'country': 'ES'}}],
                 [NULL], [NULL], [NULL], 41.5480, 2.1090,
                 {{'xmin': 2.1090, 'xmax': 2.1090, 'ymin': 41.5480, 'ymax': 41.5480}})
              ) AS t(id, names, categories, confidence, addresses, websites, phones, emails, lat_p, lon_p, bbox)
            ) TO '{destino}' (FORMAT PARQUET)
            """
        )
        return destino

    def test_estructuras_anidadas_y_filtros(self, parquet):
        caja = BBox.de_centro(41.5431, 2.1097, 6000)
        sql = (
            consulta_sql(caja)
            .replace("{origen}", str(parquet))
            .replace("ST_Y(ST_GeomFromWKB(geometry))", "lat_p")
            .replace("ST_X(ST_GeomFromWKB(geometry))", "lon_p")
        )
        _exige_duckdb()
        con = duckdb.connect()
        filas = con.execute(sql).fetchall()
        columnas = [d[0] for d in con.description]
        pois = [p for f in filas if (p := fila_a_poi(dict(zip(columnas, f)))) is not None]
        nombres = {p.nombre for p in pois}

        assert nombres == {"Finques Exemple"}, nombres
        p = pois[0]
        assert p.direccion == "Calle Sant Joan 39"
        assert p.cp == "08202"
        assert p.municipio == "Sabadell"
        assert p.web == "https://ejemplo.test"
        assert p.telefono == "937000000"
        assert p.extra["confianza"] == pytest.approx(0.91)


class TestNoCuentaNotariasComoDemanda:
    """
    `notary_public` estuvo en el conjunto de abogados. Con eso, una notaria
    catalogada en Overture entraba como DEMANDA: sumaba peso justo encima de
    donde ya hay competencia instalada, que es el error que el modelo entero
    existe para evitar, y ademas duplicaba un punto que la Guia Notarial ya
    da como censo oficial.
    """

    def test_notaria_pura_se_descarta(self):
        assert clasifica("notary_public", None) is None

    def test_notaria_etiquetada_tambien_como_abogado(self):
        # El caso real: en Overture una notaria suele llevar las dos. Si la
        # exclusion no fuera lo primero, `lawyer` la colaria como demanda.
        assert clasifica("lawyer", ["notary_public"]) is None
        assert clasifica("notary_public", ["lawyer", "legal_services"]) is None

    def test_un_abogado_de_verdad_sigue_siendo_demanda(self):
        assert clasifica("lawyer", None) == "abogados"
        assert clasifica("professional_services", ["lawyer"]) == "abogados"

    def test_no_arrastra_a_las_demas_categorias(self):
        assert clasifica("real_estate_agent", None) == "inmobiliaria"
        assert clasifica("banks", None) == "banco"


class TestCategoriasExistenDeVerdad:
    """
    Una categoria que no existe en la taxonomia de Overture no da error:
    simplemente no coincide nunca. La capa sale vacia o a medias y nada lo
    anuncia.

    Paso de verdad. La primera version de CATEGORIAS tenia seis codigos
    inventados, entre ellos `bank` —el real es `banks`— y `real_estate_agency`,
    que no existe. Con eso, la capa de bancos de Overture habria casado solo
    con `credit_union`.
    """

    def _taxonomia(self):
        import pathlib

        csv = (
            pathlib.Path(__file__).resolve().parents[1]
            / "datos" / "referencia" / "overture_categorias.csv"
        )
        if not csv.exists():
            pytest.skip(f"falta la taxonomia de referencia en {csv}")
        codigos = set()
        for linea in csv.read_text(encoding="utf-8-sig").splitlines()[1:]:
            if ";" in linea:
                codigos.add(linea.split(";", 1)[0].strip())
        return codigos

    def test_la_taxonomia_de_referencia_se_lee(self):
        tax = self._taxonomia()
        assert len(tax) > 2000, f"solo {len(tax)} categorias, el fichero no encaja"
        # Anclas conocidas, para detectar que el formato cambio.
        assert {"lawyer", "banks", "real_estate_agent"} <= tax

    def test_ninguna_categoria_usada_es_inventada(self):
        tax = self._taxonomia()
        usadas = {c for cs in CATEGORIAS.values() for c in cs}
        fantasma = sorted(usadas - tax)
        assert not fantasma, f"categorias que no existen en Overture: {fantasma}"

    def test_las_excluidas_tambien_existen(self):
        # Si `notary_public` dejara de llamarse asi, la exclusion dejaria de
        # aplicarse en silencio y las notarias volverian a contar como demanda.
        tax = self._taxonomia()
        fantasma = sorted(CATEGORIAS_EXCLUIDAS - tax)
        assert not fantasma, f"exclusiones que ya no existen: {fantasma}"

    def test_ningun_tipo_se_queda_sin_categorias(self):
        for tipo, cs in CATEGORIAS.items():
            assert cs, f"{tipo} no tiene ninguna categoria"


class TestGestorias:
    """
    La capa de demanda mas grande que faltaba. En Espana las gestorias
    canalizan constitucion de sociedades, poderes, compraventa de vehiculos y
    tramitacion de herencias.
    """

    def test_se_clasifican_las_cinco(self):
        for c in ("accountant", "bookkeeper", "tax_services",
                  "payroll_services", "business_consulting"):
            assert clasifica(c, None) == "gestoria", c

    def test_por_categoria_alternativa(self):
        assert clasifica("professional_services", ["accountant"]) == "gestoria"

    def test_la_agencia_tributaria_no_es_una_gestoria(self):
        # `tax_office` cuelga de public_service_and_government: es Hacienda,
        # no un despacho que derive trabajo a una notaria.
        assert clasifica("tax_office", None) is None

    def test_no_pisa_a_los_abogados(self):
        # `tax_law` es un despacho de abogados fiscalista, no una gestoria.
        assert clasifica("tax_law", None) == "abogados"


class TestFiltroDePais:
    """
    Overture es mundial y las cajas son rectangulos, pero Espana no lo es: la
    caja de Cataluna se mete en Francia por el norte y la peninsular arrastra
    parte de Marruecos. Sin filtro entrarian POIs de otros paises que despues
    nadie sabria de donde salieron.
    """

    def test_la_consulta_filtra_por_pais(self):
        sql = consulta_sql(BBox.de_centro(41.5431, 2.1097, 6000))
        assert "addresses[1].country" in sql
        assert "'ES'" in sql
