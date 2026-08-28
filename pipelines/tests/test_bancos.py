"""
Pruebas del extractor del Banco de España, con un fragmento del fichero real.

El fragmento incluye a propósito el bloque de metadatos del final —la fila de
almohadillas y los criterios de consulta— porque el lector de CSV los entrega
como filas normales y, sin filtrarlos, se colaban dos "oficinas" llamadas
"########" en mitad del parque bancario.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nook.fuentes.bancos import cod_ine, interpreta, nombre_entidad

FRAGMENTO = """ Cod. Tipo Entidad ; Tipo Entidad ; Cód. Entidad ; Entidad ; Cód. País ; País ; Cod CCAA ; CCAA ; Cod. Provincia ; Provincia ; Cód. Municipio ; Municipio/Población ; Domicilio ; CP ; Tipo
BP ; BANCOS ; 0019 ; DEUTSCHE BANK, S.A.E. (0019) ; ES ; ESPAÑA ; 09 ; CATALUÑA           ; 08 ; Barcelona ; 187 ; SABADELL ; ZZ PASSEIG PLAÇA MAJOR 62-64 ; 08202 ; Operativas ;
BP ; BANCOS ; 0049 ; BANCO SANTANDER, S.A. (0049) ; ES ; ESPAÑA ; 09 ; CATALUÑA           ; 08 ; Barcelona ; 187 ; SABADELL ; CR DE TERRASSA 0335 ; 08205 ; Operativas ;
CA ; CAJAS ; 2100 ; CAIXABANK, S.A. (2100) ; ES ; ESPAÑA ; 09 ; CATALUÑA           ; 08 ; Barcelona ; 187 ; SABADELL ; CL RAMBLA, 95 0095 ; 08202 ; No operativas ;
######## ; ######## ; ######## ; ######## ; ######## ; ######## ; ######## ;
CRITERIOS DE CONSULTA ;
Oficinas en: ; España ;
Fecha de obtención: 21/10/2024,12:37 ; ; ; ; ; ; ; ; ; Fecha de Referencia: 30/06/2024 ;
"""


class TestNombreEntidad:
    def test_separa_el_codigo(self):
        assert nombre_entidad("BANCO SANTANDER, S.A. (0049)") == ("Banco Santander, S.A.", "0049")

    def test_sin_codigo(self):
        nombre, codigo = nombre_entidad("Caja Rural")
        assert nombre == "Caja Rural" and codigo is None

    def test_vacio(self):
        assert nombre_entidad(None) == (None, None)


class TestCodIne:
    def test_rellena_con_ceros(self):
        # Sabadell viene como provincia 08 y municipio 187: el código INE es
        # 08187, no "08"+"187" sin más suerte.
        assert cod_ine("08", "187") == "08187"
        assert cod_ine("8", "7") == "08007"

    def test_rechaza_lo_que_no_es_numero(self):
        assert cod_ine("Barcelona", "187") is None
        assert cod_ine(None, "187") is None


class TestInterpreta:
    def test_descarta_el_bloque_de_metadatos(self):
        pois = interpreta(FRAGMENTO)
        nombres = [p.nombre for p in pois]
        assert not any("#" in n for n in nombres)
        assert not any("CRITERIOS" in n.upper() for n in nombres)

    def test_solo_oficinas_operativas(self):
        # Una oficina no operativa no atiende al público, así que no genera
        # tránsito de personas ni, por tanto, demanda notarial.
        pois = interpreta(FRAGMENTO)
        assert len(pois) == 2
        assert all("Caixabank" not in p.nombre for p in pois)

    def test_campos_bien_mapeados(self):
        pois = interpreta(FRAGMENTO)
        db = next(p for p in pois if "Deutsche" in p.nombre)
        assert db.tipo == "banco"
        assert db.fuente == "bde"
        assert db.cod_ine == "08187"
        assert db.cp == "08202"
        assert db.municipio == "Sabadell"
        assert db.direccion == "Passeig Plaça Major 62-64"
        assert db.extra["cod_entidad"] == "0019"

    def test_conserva_el_numero_de_portal(self):
        pois = interpreta(FRAGMENTO)
        santander = next(p for p in pois if "Santander" in p.nombre)
        assert santander.direccion == "Carretera De Terrassa 335"

    def test_ids_estables_entre_ejecuciones(self):
        primera = {p.fuente_id for p in interpreta(FRAGMENTO)}
        segunda = {p.fuente_id for p in interpreta(FRAGMENTO)}
        assert primera == segunda

    def test_sin_coordenadas_de_origen(self):
        # El BdE no publica coordenadas: todo pasa por geocodificación, y eso
        # tiene que quedar declarado.
        pois = interpreta(FRAGMENTO)
        assert all(not p.geolocalizado for p in pois)
        assert all(p.geocode_calidad == "desconocida" for p in pois)
