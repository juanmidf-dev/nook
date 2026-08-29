"""
Pruebas de la geocodificación.

El caso que motivó este fichero: la primera ingesta real del censo notarial
dejó 2.570 de 2.641 notarías sin coordenadas. Dos fallos encadenados y ninguno
ruidoso —CartoCiudad devolvía JSONP, que el cliente no sabía leer, y la
consulta llevaba dentro la planta, el local y la provincia, con lo que el IGN
respondía lista vacía en vez de un error—. Todo caía al respaldo de Nominatim,
que acertó un 2,7 %.

Una notaría sin coordenadas no aparece en la capa de competencia, y una
competencia incompleta hace que el mapa recomiende abrir al lado de una
notaría que ya existe. Es el fallo más caro del producto.

Las direcciones son copia literal del artefacto de esa ejecución. Ninguna
prueba toca la red.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nook.geocode import (  # noqa: E402
    interpreta_cartociudad,
    para_cartociudad,
)
from nook.http import Cliente  # noqa: E402


class TestParaCartociudad:
    """
    Medido contra el servicio real: con el texto completo acierta 0 de 30;
    reducido a "vía, portal", 28 de 30 y todas a nivel de portal.
    """

    @pytest.mark.parametrize(
        "bruta, esperada",
        [
            # Lo que mas abunda: planta pegada al portal.
            ("Calle Del Sol, número 1 Pl 2", "Calle Del Sol, 1"),
            ("Calle Santiago Rusiñol, número 3 Bajo", "Calle Santiago Rusiñol, 3"),
            ("Calle Castillo, número 56 Planta 3 Puerta B", "Calle Castillo, 56"),
            ("Plaza Del Farell, número 3 Local 4", "Plaza Del Farell, 3"),
            ("Calle Maria Auxiliadora, número 2 Escalera 1", "Calle Maria Auxiliadora, 2"),
            # El edificio entre parentesis tambien sobra para el IGN.
            (
                "Avenida Francesc Macià, número 60 Planta 6 (Torre Millenium)",
                "Avenida Francesc Macià, 60",
            ),
            # Ya limpia: no debe estropearla.
            ("Calle Molinos, número 25", "Calle Molinos, 25"),
            ("Calle San Juan de Dios, 9", "Calle San Juan de Dios, 9"),
            # Sin numero de portal: se queda la via, no se inventa un 1.
            ("Avenida Madrid, s/n (Esquina Camino Barreros)", "Avenida Madrid"),
            ("Calle Doctor Velázquez, s/n (Edificio Alfe)", "Calle Doctor Velázquez"),
            # Espacios de sobra en el original.
            ("Calle  Madrid,   número   6   Pl 3", "Calle Madrid, 6"),
        ],
    )
    def test_reduce_a_via_y_portal(self, bruta, esperada):
        assert para_cartociudad(bruta) == esperada

    def test_no_confunde_un_numero_de_la_via_con_el_portal(self):
        # "Nacional 340" lleva un numero dentro del nombre de la via. Si se
        # tomara el primero que aparece, la notaria acabaria en el portal 340
        # de una calle que no existe.
        assert para_cartociudad("Carretera Nacional 340, número 12") == "Carretera Nacional 340, 12"
        assert para_cartociudad("Calle 2 de Mayo, número 8") == "Calle 2 de Mayo, 8"

    def test_nunca_deja_lo_que_vacia_la_respuesta(self):
        ruido = ("número", " Pl ", "Planta", "Local", "Bajo", "Entresuelo")
        for bruta in [
            "Calle Del Sol, número 1 Pl 2",
            "Calle Castillo, número 56 Planta 3 Puerta B",
            "Avenida República Argentina, número 9 Local",
            "Calle Penyagolosa, número 4 Bajo",
        ]:
            salida = para_cartociudad(bruta)
            for r in ruido:
                assert r.lower() not in salida.lower(), f"{salida!r} conserva {r!r}"


class _Respuesta:
    """Lo mínimo de requests.Response que usa el cliente."""

    def __init__(self, texto, tipo="application/x-javascript"):
        self.text = texto
        self.headers = {"content-type": tipo}

    def json(self):
        raise ValueError("no es JSON")


class TestJsonp:
    def _cliente(self, monkeypatch, respuesta):
        c = Cliente(pausa_s=0)
        monkeypatch.setattr(c, "get", lambda *a, **k: respuesta)
        return c

    def test_desenvuelve_la_llamada(self, monkeypatch):
        c = self._cliente(monkeypatch, _Respuesta('callback([{"lat": 41.5, "lng": 2.1}])'))
        assert c.jsonp("http://x") == [{"lat": 41.5, "lng": 2.1}]

    def test_lista_vacia(self, monkeypatch):
        # Es lo que devuelve el IGN cuando no encuentra: vacio, no error.
        assert self._cliente(monkeypatch, _Respuesta("callback([])")).jsonp("http://x") == []

    def test_con_punto_y_coma_final(self, monkeypatch):
        c = self._cliente(monkeypatch, _Respuesta('jQuery123({"lat": 1});'))
        assert c.jsonp("http://x") == {"lat": 1}

    def test_json_pelado_sin_envoltorio(self, monkeypatch):
        # Si algun dia el IGN publica JSON de verdad, esto no debe romperse.
        c = self._cliente(monkeypatch, _Respuesta('[{"lat": 1}]', "application/json"))
        assert c.jsonp("http://x") == [{"lat": 1}]

    def test_basura_no_revienta(self, monkeypatch):
        assert self._cliente(monkeypatch, _Respuesta("<html>error</html>")).jsonp("http://x") is None

    def test_sin_respuesta(self, monkeypatch):
        c = Cliente(pausa_s=0)
        monkeypatch.setattr(c, "get", lambda *a, **k: None)
        assert c.jsonp("http://x") is None


class TestInterpretaCartociudad:
    # Respuesta literal del servicio para "Calle Del Sol, 1, Sabadell".
    REAL = [
        {
            "id": "09.08.MUN_081870677167",
            "province": "Barcelona",
            "muni": "Sabadell",
            "muniCode": "08187",
            "type": "portal",
            "address": "SOL",
            "postalCode": "08201",
            "lat": 41.54590376781237,
            "lng": 2.108844133114609,
            "portalNumber": 1,
            "state": 0,
        }
    ]

    def test_lee_la_respuesta_real(self):
        r = interpreta_cartociudad(self.REAL)
        assert r.calidad == "portal"
        assert r.fuente == "cartociudad"
        assert round(r.lat, 4) == 41.5459 and round(r.lon, 4) == 2.1088

    def test_lista_vacia_no_es_un_resultado(self):
        assert interpreta_cartociudad([]) is None

    def test_descarta_coordenadas_fuera_de_espana(self):
        # Un lon/lat invertido cae en Somalia. Mejor sin coordenada que con
        # una que coloca la notaria en otro continente.
        fuera = [dict(self.REAL[0], lat=2.1088, lng=41.5459)]
        assert interpreta_cartociudad(fuera) is None


class TestMotivoDelFallo:
    """
    `get` devuelve None tanto por excepcion de red como por un codigo que no
    se reintenta. Sin distinguirlos, el reconocimiento marcaba "inalcanzable"
    sin decir por que, y "no hay salida a este dominio" y "el dominio
    responde 403" llevan a decisiones opuestas.
    """

    def test_arranca_a_none(self):
        assert Cliente(pausa_s=0).ultimo_fallo is None

    def test_anota_el_codigo_que_no_se_reintenta(self, monkeypatch):
        c = Cliente(pausa_s=0)
        monkeypatch.setattr(c.sesion, "get", lambda *a, **k: _Respuesta403())
        assert c.get("http://x") is None
        assert c.ultimo_fallo == "HTTP 403"

    def test_anota_la_excepcion_de_red(self, monkeypatch):
        import requests

        c = Cliente(pausa_s=0, intentos=1)

        def revienta(*a, **k):
            raise requests.ConnectionError("no route to host")

        monkeypatch.setattr(c.sesion, "get", revienta)
        assert c.get("http://x") is None
        assert "ConnectionError" in c.ultimo_fallo

    def test_una_peticion_buena_lo_limpia(self, monkeypatch):
        c = Cliente(pausa_s=0)
        monkeypatch.setattr(c.sesion, "get", lambda *a, **k: _Respuesta403())
        c.get("http://x")
        monkeypatch.setattr(c.sesion, "get", lambda *a, **k: _Respuesta200())
        c.get("http://y")
        assert c.ultimo_fallo is None


class _Respuesta403:
    status_code = 403
    headers: dict = {}
    text = ""


class _Respuesta200:
    status_code = 200
    headers: dict = {}
    text = "{}"


class TestCalidadesNoUbicables:
    """
    Una notaria colocada en el centro del pueblo hace mas dano que una
    ausente: mete competencia donde no la hay y la quita de donde si. A sigma
    600 m, un centroide municipal no es "aproximadamente bien", es otro sitio.
    """

    def test_municipio_no_es_ubicable(self):
        from nook.geocode import CALIDADES_NO_UBICABLES

        assert "municipio" in CALIDADES_NO_UBICABLES

    def test_portal_y_via_si_lo_son(self):
        from nook.geocode import CALIDADES_NO_UBICABLES

        assert "portal" not in CALIDADES_NO_UBICABLES
        assert "via" not in CALIDADES_NO_UBICABLES


class TestResumenDistingueLosHuecos:
    """
    "No lo encontre" y "lo encontre mal" se arreglan de formas distintas.
    Sumarlos en un solo `sin_coordenadas` oculta cual toca.
    """

    def _poi(self, lat=None, lon=None, calidad="desconocida", fuente=None):
        from nook.modelo import Poi

        # `geocode_calidad` vale "desconocida" por defecto, asi que replicar
        # ese default importa: es justo lo que hacia que un no-encontrado
        # pareciera un descartado.
        return Poi(
            tipo="notaria", fuente="notariado",
            fuente_id=f"x{lat}{calidad}{fuente}{id(object())}",
            nombre="N", lat=lat, lon=lon,
            geocode_calidad=calidad, geocode_fuente=fuente,
        )

    def test_separa_descartadas_de_no_encontradas(self):
        from nook.salida import resumen

        pois = [
            self._poi(41.5, 2.1, "portal", "cartociudad"),
            self._poi(41.6, 2.2, "via", "cartociudad"),
            # Encontrada, pero solo a nivel de municipio: se le quita la
            # coordenada y conserva fuente y calidad como explicacion.
            self._poi(None, None, "municipio", "cartociudad"),
            # Nunca la vio nadie: calidad al valor por defecto y sin fuente.
            self._poi(None, None),
            self._poi(None, None),
        ]
        r = resumen(pois)
        assert r["total"] == 5
        assert r["sin_coordenadas"] == 3
        assert r["descartadas_por_calidad"] == {"municipio": 1}
        assert r["no_encontradas"] == 2

    def test_no_encontrada_no_cuenta_como_descartada(self):
        # El caso que se colo en la primera version: sin mirar la fuente, las
        # 176 que nadie encontro salian como "descartadas por calidad".
        from nook.salida import resumen

        r = resumen([self._poi(None, None)])
        assert r["descartadas_por_calidad"] == {}
        assert r["no_encontradas"] == 1

    def test_todo_bien_no_inventa_huecos(self):
        from nook.salida import resumen

        r = resumen([self._poi(41.5, 2.1, "portal", "cartociudad")])
        assert r["sin_coordenadas"] == 0
        assert r["descartadas_por_calidad"] == {}
        assert r["no_encontradas"] == 0


class TestComprobacionPreviaDeTipos:
    """
    Tres fallos distintos del 29/08/2026 se manifestaron solo al escribir,
    despues de hacer todo el trabajo: claves no uniformes, claves repetidas y
    un valor de enum que faltaba. Con Overture cuesta ocho minutos; con
    notarias o bancos, setenta, porque la geocodificacion va por delante.
    """

    def _sb(self, monkeypatch, respuesta):
        from nook.salida import Supabase

        sb = Supabase("https://x.supabase.co", "sb_secret_x")
        monkeypatch.setattr("nook.salida.requests.get", lambda *a, **k: respuesta)
        return sb

    def _poi(self, tipo):
        from nook.modelo import Poi

        return Poi(tipo=tipo, fuente="overture", fuente_id=tipo, nombre="N")

    def test_lee_el_enum_del_esquema(self, monkeypatch):
        sb = self._sb(monkeypatch, _Spec({"enum": ["notaria", "banco", "gestoria"]}))
        assert sb.tipos_admitidos() == {"notaria", "banco", "gestoria"}

    def test_formato_antiguo_de_postgrest(self, monkeypatch):
        sb = self._sb(monkeypatch, _Spec({"format": "public.poi_tipo: 'notaria', 'banco'"}))
        assert sb.tipos_admitidos() == {"notaria", "banco"}

    def test_aborta_si_falta_un_tipo(self, monkeypatch):
        sb = self._sb(monkeypatch, _Spec({"enum": ["notaria", "banco"]}))
        with pytest.raises(SystemExit) as e:
            sb.comprueba_tipos([self._poi("gestoria")])
        # El mensaje tiene que traer la orden que lo arregla, no solo el fallo.
        assert "gestoria" in str(e.value)
        assert "alter type poi_tipo" in str(e.value)

    def test_no_aborta_si_todo_encaja(self, monkeypatch):
        sb = self._sb(monkeypatch, _Spec({"enum": ["notaria", "banco", "gestoria"]}))
        sb.comprueba_tipos([self._poi("gestoria"), self._poi("banco")])

    def test_si_no_puede_averiguarlo_no_bloquea(self, monkeypatch):
        # Un chequeo previo con falsos negativos es peor que no tenerlo:
        # acabaria impidiendo escrituras perfectamente validas.
        sb = self._sb(monkeypatch, _Spec(None))
        assert sb.tipos_admitidos() is None
        sb.comprueba_tipos([self._poi("gestoria")])


class _Spec:
    """Respuesta minima del OpenAPI que publica PostgREST en su raiz."""

    status_code = 200

    def __init__(self, tipo):
        self._tipo = tipo

    def json(self):
        if self._tipo is None:
            return {"definitions": {}}
        return {"definitions": {"pois": {"properties": {"tipo": self._tipo}}}}
