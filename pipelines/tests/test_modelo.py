"""Pruebas del modelo común. Sin red: todo son casos tomados de ficheros reales."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nook.modelo import Poi, deduplica, extrae_cp, id_estable, limpia_direccion, normaliza


class TestLimpiaDireccion:
    """
    Los casos vienen del fichero real del Banco de España. El más importante
    es el del número de portal: la primera versión borraba el número final
    rellenado con ceros creyendo que era un código de oficina repetido, y
    dejaba media provincia con direcciones sin portal.
    """

    def test_expande_el_codigo_de_via(self):
        assert limpia_direccion("CL LES TRES CREUS 00087") == "Calle Les Tres Creus 87"

    def test_conserva_el_numero_de_portal(self):
        assert limpia_direccion("CR DE TERRASSA 0335") == "Carretera De Terrassa 335"
        assert limpia_direccion("AV MATADEPERA 0079") == "Avenida Matadepera 79"

    def test_quita_el_numero_repetido(self):
        assert limpia_direccion("CL RAMBLA, 95 0095") == "Rambla, 95"
        assert limpia_direccion("PS PO. PLACA MAJOR, 32 0032") == "Placa Major, 32"

    def test_expande_la_abreviatura_cuando_no_hay_codigo_de_via(self):
        # "ZZ" es "sin clasificar": la abreviatura interna es la única pista
        # del tipo de vía y borrarla dejaba "De Matadepera, 46".
        assert limpia_direccion("ZZ AV. DE MATADEPERA, 46. 0") == "Avenida De Matadepera, 46"
        assert limpia_direccion("ZZ RDA. EUROPA 00524") == "Ronda Europa 524"

    def test_no_duplica_el_tipo_de_via(self):
        assert limpia_direccion("RB RAMBLA 0184") == "Rambla 184"
        assert limpia_direccion("CL VIA MASSAGUE 6 - 8") == "Via Massague 6 - 8"

    def test_respeta_lo_que_ya_viene_bien(self):
        assert limpia_direccion("CL Pi i Margall 10-12") == "Calle Pi i Margall 10-12"

    def test_vacios(self):
        assert limpia_direccion(None) is None
        assert limpia_direccion("   ") is None


class TestCodigoPostal:
    def test_extrae(self):
        assert extrae_cp("Calle Mayor 3, 08202 Sabadell") == "08202"

    def test_descarta_lo_que_no_es_provincia(self):
        # 99 no es un código de provincia español: es basura de otro campo.
        assert extrae_cp("ref 99123 interna") is None

    def test_sin_numero(self):
        assert extrae_cp("Calle Mayor") is None


class TestIdEstable:
    def test_es_determinista(self):
        assert id_estable("Banco X", "Calle Mayor 3") == id_estable("Banco X", "Calle Mayor 3")

    def test_ignora_forma_societaria_y_acentos(self):
        # El mismo banco escrito de dos formas tiene que dar el mismo id, o la
        # ejecución mensual duplica en vez de actualizar.
        assert id_estable("BANCO SANTANDER, S.A.") == id_estable("Banco Santander SA")

    def test_distingue_direcciones_distintas(self):
        assert id_estable("Banco X", "Calle Mayor 3") != id_estable("Banco X", "Calle Mayor 4")


class TestNormaliza:
    def test_quita_acentos_y_puntuacion(self):
        assert normaliza("Plaça Sant Roc, 20.") == "placa sant roc 20"


def _poi(nombre, lat, lon, tipo="inmobiliaria", fuente="overture", **kw):
    return Poi(tipo=tipo, fuente=fuente, fuente_id=nombre, nombre=nombre, lat=lat, lon=lon, **kw)


class TestDeduplica:
    def test_funde_el_mismo_sitio_de_dos_fuentes(self):
        a = _poi("Fincamps", 41.5474, 2.1099)
        b = _poi("Fincamps", 41.5474, 2.1099, fuente="osm", telefono="937000000")
        salida, fusionados = deduplica([a, b])
        assert fusionados == 1
        assert len(salida) == 1
        # Los huecos del que se conserva se rellenan con lo que traía el otro.
        assert salida[0].telefono == "937000000"

    def test_no_funde_sitios_lejanos_con_el_mismo_nombre(self):
        # Una cadena con dos oficinas en la misma ciudad son dos puntos de
        # demanda, no uno.
        a = _poi("Tecnocasa", 41.5474, 2.1099)
        b = _poi("Tecnocasa", 41.5600, 2.1200)
        salida, fusionados = deduplica([a, b])
        assert fusionados == 0
        assert len(salida) == 2

    def test_no_funde_tipos_distintos(self):
        a = _poi("Central", 41.5474, 2.1099, tipo="banco")
        b = _poi("Central", 41.5474, 2.1099, tipo="inmobiliaria")
        _, fusionados = deduplica([a, b])
        assert fusionados == 0

    def test_conserva_los_que_no_tienen_coordenadas(self):
        # Se quedan fuera de la comparación, pero no se pierden: se declaran
        # después como incidencia.
        a = Poi(tipo="notaria", fuente="notariado", fuente_id="x", nombre="Sin geo")
        salida, _ = deduplica([a])
        assert len(salida) == 1


class TestCabecerasSupabase:
    """
    Supabase tiene dos generaciones de clave y no aceptan las mismas
    cabeceras. Enviar la nueva `sb_secret_...` en Authorization hace que la
    peticion llegue a la base de datos y se rechace al leerla como JWT, asi
    que la ingesta entera fallaria con un 401 dificil de interpretar.
    """

    def _cabeceras(self, clave):
        from nook.salida import Supabase

        return Supabase("https://abc.supabase.co", clave).cabeceras

    def test_clave_nueva_no_lleva_authorization(self):
        h = self._cabeceras("sb_secret_MBqnmG4cx10MUV6051qbpA")
        assert h["apikey"] == "sb_secret_MBqnmG4cx10MUV6051qbpA"
        assert "Authorization" not in h

    def test_clave_legada_si_lleva_authorization(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.firma"
        h = self._cabeceras(jwt)
        assert h["Authorization"] == f"Bearer {jwt}"
        assert h["apikey"] == jwt

    def test_la_url_no_duplica_la_barra(self):
        from nook.salida import Supabase

        assert Supabase("https://abc.supabase.co/", "k").base == "https://abc.supabase.co/rest/v1"

    def test_el_upsert_sigue_siendo_upsert(self):
        # Sin merge-duplicates el insert mensual duplicaria el censo entero.
        assert "merge-duplicates" in self._cabeceras("k")["Prefer"]


class TestParaSupabase:
    """
    PostgREST exige que todos los objetos de un lote compartan claves. Filtrar
    los campos vacios hacia que una notaria con correo y otra sin el generaran
    claves distintas, y rechazaba el lote entero con PGRST102. Paso en la
    primera ingesta real, despues de 45 minutos de geocodificacion.
    """

    def _poi(self, **kw):
        from nook.modelo import Poi

        base = dict(tipo="notaria", fuente="notariado", fuente_id="1", nombre="N")
        base.update(kw)
        return Poi(**base)

    def test_dos_registros_desiguales_comparten_claves(self):
        con_todo = self._poi(email="a@b.es", telefono="900", web="https://x.es").para_supabase()
        sin_nada = self._poi().para_supabase()
        assert set(con_todo) == set(sin_nada)

    def test_los_huecos_van_como_null_explicito(self):
        d = self._poi().para_supabase()
        assert "email" in d and d["email"] is None
        assert "telefono" in d and d["telefono"] is None

    def test_extra_nunca_es_null(self):
        # La columna es NOT NULL con default '{}'; un None romperia el insert.
        d = self._poi().para_supabase()
        assert d["extra"] == {}

    def test_no_manda_geom(self):
        # La rellena el trigger: la API REST no puede construir un geography.
        assert "geom" not in self._poi().para_supabase()

    def test_no_cuela_la_propiedad_geolocalizado(self):
        assert "geolocalizado" not in self._poi(lat=41.5, lon=2.1).para_supabase()


class TestDefensaDeLote:
    def test_detecta_claves_distintas(self):
        import pytest

        from nook.salida import _comprueba_claves_uniformes

        with pytest.raises(RuntimeError, match="mismas claves"):
            _comprueba_claves_uniformes([{"a": 1, "b": 2}, {"a": 1}], 0)

    def test_lote_uniforme_pasa(self):
        from nook.salida import _comprueba_claves_uniformes

        _comprueba_claves_uniformes([{"a": 1, "b": None}, {"a": 2, "b": 3}], 0)

    def test_lote_vacio_no_revienta(self):
        from nook.salida import _comprueba_claves_uniformes

        _comprueba_claves_uniformes([], 0)


class TestColapsaPorId:
    """
    Postgres rechaza la sentencia entera si dos filas del mismo lote apuntan a
    la misma fila destino: `21000: ON CONFLICT DO UPDATE command cannot affect
    row a second time`. La ingesta real de bancos murio ahi despues de escribir
    3.500 de 4.024 filas, porque el volcado del BdE trae filas repetidas.
    """

    def _poi(self, fid="1", **kw):
        from nook.modelo import Poi

        base = dict(tipo="banco", fuente="bde", fuente_id=fid, nombre="Oficina")
        base.update(kw)
        return Poi(**base)

    def test_no_deja_claves_repetidas(self):
        from nook.modelo import colapsa_por_id

        pois, n = colapsa_por_id([self._poi("a"), self._poi("a"), self._poi("b")])
        assert len(pois) == 2
        assert n == 1
        assert len({(p.fuente, p.fuente_id) for p in pois}) == 2

    def test_la_misma_clave_en_fuentes_distintas_no_choca(self):
        from nook.modelo import colapsa_por_id

        a = self._poi("x")
        b = self._poi("x", fuente="overture")
        pois, n = colapsa_por_id([a, b])
        assert len(pois) == 2 and n == 0

    def test_rellena_los_huecos_del_primero(self):
        from nook.modelo import colapsa_por_id

        pois, _ = colapsa_por_id([
            self._poi("a", telefono=None, web="https://x.es"),
            self._poi("a", telefono="900", web=None),
        ])
        assert pois[0].telefono == "900"
        assert pois[0].web == "https://x.es"

    def test_las_coordenadas_van_en_pareja(self):
        # Media coordenada no es un dato incompleto: es un punto en Greenwich.
        from nook.modelo import colapsa_por_id

        pois, _ = colapsa_por_id([
            self._poi("a"),
            self._poi("a", lat=41.5, lon=2.1, geocode_calidad="portal"),
        ])
        assert pois[0].lat == 41.5 and pois[0].lon == 2.1
        assert pois[0].geocode_calidad == "portal"

    def test_no_pisa_una_coordenada_buena(self):
        from nook.modelo import colapsa_por_id

        pois, _ = colapsa_por_id([
            self._poi("a", lat=41.5, lon=2.1),
            self._poi("a", lat=40.0, lon=-3.7),
        ])
        assert pois[0].lat == 41.5

    def test_deja_constancia_de_la_repeticion(self):
        from nook.modelo import colapsa_por_id

        pois, _ = colapsa_por_id([self._poi("a")] * 1 + [self._poi("a"), self._poi("a")])
        assert pois[0].extra["repetidos_en_origen"] == 3

    def test_el_caso_real_de_eurodivisas(self):
        # Seis mostradores con la misma clave en la T4 de Barajas.
        from nook.modelo import colapsa_por_id

        seis = [self._poi("euro", nombre="Eurodivisas, S.A.") for _ in range(6)]
        pois, n = colapsa_por_id(seis)
        assert len(pois) == 1 and n == 5
        assert pois[0].extra["repetidos_en_origen"] == 6
