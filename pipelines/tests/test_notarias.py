"""
Pruebas del extractor de la Guía Notarial, con registros reales de Sabadell.

Los cinco registros son copia literal de lo que devolvió
`POST /guianotarial/rest/buscar/notarios` el 28/08/2026, sin retocar. Están
elegidos por lo que rompen: el nombre viene invertido y con guion y partícula
("Díaz-Fraile del Monte, Aurora Cristina"), la dirección trae el código postal
pegado al final sin separador, y hay registros con los tres campos de correo
vacíos salvo uno.

Ninguna prueba toca la red.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nook.fuentes.notarias import (
    interpreta_registro,
    interpreta_respuesta,
    nombre_legible,
)

MUESTRA = [
    {
        "apellidos_nombre": "Cembrano Zaldivar, Jesús",
        "direccion": "Calle Del Sol, número 1 Pl 2  08201",
        "municipio": "Sabadell",
        "provincia": "Barcelona",
        "telefono": "937.262.244",
        "fax": "937.276.755",
        "estado": "AC",
        "correoElectronicoPersonal": "jesuscembrano@notariado.org",
        "correoElectronicoCorporativo": "jcembrano@correonotarial.org",
        "correoElectronicoNotaria": "",
        "codigoUltimasVoluntades": "8600407",
        "codigoNotaria": "081878170",
        "idiomasExtranjeros": "Catalán y Francés",
    },
    {
        "apellidos_nombre": "Díaz-Fraile del Monte, Aurora Cristina",
        "direccion": "Plaza Del Farell, número 3 Local 4 08207",
        "municipio": "Sabadell",
        "provincia": "Barcelona",
        "telefono": "937.109.090",
        "fax": "",
        "estado": "AC",
        "correoElectronicoPersonal": "",
        "correoElectronicoCorporativo": "",
        "correoElectronicoNotaria": "notaria@farell.es",
        "codigoUltimasVoluntades": "8600411",
        "codigoNotaria": "081878168",
        "idiomasExtranjeros": "",
    },
    {
        "apellidos_nombre": "Colomé Serra, Lluis",
        "direccion": "Calle Sant Antoni Mª. Claret, número 1 Pl 2  08202",
        "municipio": "Sabadell",
        "provincia": "Barcelona",
        "telefono": "937.257.777",
        "estado": "AC",
        "codigoNotaria": "081878165",
    },
    {
        "apellidos_nombre": "Gómez Martínez, Juan",
        "direccion": "Avenida Francesc Macià, número 60 Planta 6  (Torre Millenium) 08208",
        "municipio": "Sabadell",
        "provincia": "Barcelona",
        "telefono": "937.481.354",
        "estado": "AC",
        "codigoNotaria": "081878164",
    },
    {
        "apellidos_nombre": "Sáez Ripoll, Alejandro",
        "direccion": "Avenida Francesc Macià, número 60 Planta 6  08208",
        "municipio": "Sabadell",
        "provincia": "Barcelona",
        "telefono": "937.271.111",
        "estado": "AC",
        "codigoNotaria": "081878015",
    },
]


class TestNombreLegible:
    def test_invierte_por_la_primera_coma(self):
        assert nombre_legible("Cembrano Zaldivar, Jesús") == "Jesús Cembrano Zaldivar"

    def test_apellido_con_guion_y_particula(self):
        assert (
            nombre_legible("Díaz-Fraile del Monte, Aurora Cristina")
            == "Aurora Cristina Díaz-Fraile del Monte"
        )

    def test_sin_coma_se_deja_igual(self):
        assert nombre_legible("Notaría de Sabadell") == "Notaría de Sabadell"


class TestInterpretaRegistro:
    def test_usa_el_codigo_de_la_fuente_como_id(self):
        # Es la diferencia entre actualizar y duplicar en la ejecución
        # mensual, y sobrevive a que el despacho cambie de domicilio.
        assert interpreta_registro(MUESTRA[0]).fuente_id == "081878170"

    def test_saca_el_cp_del_final_de_la_direccion(self):
        p = interpreta_registro(MUESTRA[0])
        assert p.cp == "08201"
        # Y no lo deja pegado a la vía: empeora la geocodificación a portal.
        assert "08201" not in p.direccion

    def test_conserva_el_parentesis_del_edificio(self):
        # "(Torre Millenium)" es lo que distingue este portal del de al lado;
        # una limpieza demasiado agresiva lo borraba.
        p = interpreta_registro(MUESTRA[3])
        assert "Torre Millenium" in p.direccion
        assert p.cp == "08208"

    def test_prefiere_el_correo_de_la_notaria_al_personal(self):
        assert interpreta_registro(MUESTRA[1]).email == "notaria@farell.es"

    def test_cae_al_corporativo_si_no_hay_de_notaria(self):
        assert interpreta_registro(MUESTRA[0]).email == "jcembrano@correonotarial.org"

    def test_registro_sin_nombre_se_descarta(self):
        assert interpreta_registro({"direccion": "Calle Mayor 1", "municipio": "Sabadell"}) is None

    def test_no_inventa_coordenadas(self):
        # Una notaría mal situada hace que el mapa recomiende el portal de al
        # lado de una notaría ya abierta. Sin coordenadas se queda pendiente
        # de geocodificar, nunca con un relleno.
        p = interpreta_registro(MUESTRA[0])
        assert p.lat is None and p.lon is None and not p.geolocalizado

    def test_guarda_el_nombre_original(self):
        assert interpreta_registro(MUESTRA[0]).extra["apellidos_nombre"] == "Cembrano Zaldivar, Jesús"

    def test_campos_vacios_no_ensucian_extra(self):
        # `idiomasExtranjeros` viene "" en este registro: no debe aparecer.
        assert "idiomas" not in interpreta_registro(MUESTRA[1]).extra


class TestInterpretaRespuesta:
    def test_lista_pelada(self):
        pois = interpreta_respuesta(MUESTRA)
        assert len(pois) == 5
        assert all(p.tipo == "notaria" and p.fuente == "notariado" for p in pois)

    def test_ids_unicos(self):
        pois = interpreta_respuesta(MUESTRA)
        assert len({p.fuente_id for p in pois}) == len(pois)

    def test_dos_notarias_en_el_mismo_portal_no_se_pisan(self):
        # Francesc Macià 60 planta 6 alberga dos notarías distintas. Con un id
        # derivado de la dirección, la segunda sobreescribía a la primera.
        pois = interpreta_respuesta([MUESTRA[3], MUESTRA[4]])
        assert len({p.fuente_id for p in pois}) == 2

    def test_envoltorio_content(self):
        assert len(interpreta_respuesta({"content": MUESTRA})) == 5

    def test_respuesta_inesperada_no_revienta(self):
        # Devuelve vacío y deja que `cli.escribe` aborte: es ahí donde está la
        # decisión de no escribir un censo vacío.
        assert interpreta_respuesta(None) == []
        assert interpreta_respuesta({"error": "algo"}) == []
