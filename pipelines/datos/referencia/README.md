# Datos de referencia

## overture_categorias.csv

La taxonomía oficial de Overture Places: 2.117 categorías con su jerarquía.
Descargada de

    https://raw.githubusercontent.com/OvertureMaps/schema/main/docs/schema/concepts/by-theme/places/overture_categories.csv

Está aquí versionada porque `tests/test_overture.py` comprueba contra ella que
todos los códigos de `CATEGORIAS` existen de verdad.

Ese test no es paranoia. La primera versión del diccionario tenía seis
categorías inventadas —entre ellas `bank`, cuyo código real es `banks`, y
`real_estate_agency`, que no existe— y ninguna daba error: una categoría que no
casa simplemente no coincide nunca, así que la capa habría salido vacía o a
medias sin que nada lo anunciara.

Al subir la versión fijada del dataset en `overture.py`, conviene volver a
bajar este fichero y ver el diff.
