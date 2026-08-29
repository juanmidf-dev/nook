-- ============================================================
-- Verificación posterior a una ingesta en modo real
-- ============================================================
-- Pegar en el SQL Editor de Supabase. No modifica nada.
--
-- La comprobación que importa es la 2: `geom` la rellena un trigger a partir
-- de lat/lon, porque los extractores escriben por PostgREST y la API REST no
-- puede construir un `geography`. Si el trigger no funcionara, la tabla se
-- llenaría, nada daría error, y todas las consultas por distancia devolverían
-- vacío para siempre. Ver el punto 6 de CLAUDE.md.

-- 1. ¿Cuántas filas hay y de qué tipo?
select tipo, fuente, count(*) as filas
from pois
group by tipo, fuente
order by filas desc;

-- 2. LA COMPROBACIÓN CRÍTICA: ¿se rellenó geom?
--    `sin_geom_teniendo_latlon` tiene que ser 0. Si no lo es, el trigger no
--    está funcionando y los índices espaciales no sirven de nada.
select
  count(*)                                                          as total,
  count(*) filter (where lat is not null)                           as con_latlon,
  count(*) filter (where geom is not null)                          as con_geom,
  count(*) filter (where lat is not null and geom is null)          as sin_geom_teniendo_latlon,
  count(*) filter (where lat is null and geom is not null)          as geom_sin_latlon
from pois;

-- 3. ¿La geometría cae donde dice lat/lon? Debe ser 0 metros (o casi).
--    Si saliera una distancia grande, el trigger estaría invirtiendo
--    longitud y latitud, que no da error y coloca todo en otro continente.
select
  nombre, municipio,
  round(st_distance(geom, st_makepoint(lon, lat)::geography)::numeric, 2) as desvio_m
from pois
where geom is not null
order by desvio_m desc
limit 5;

-- 4. Reparto por calidad de geocodificación. No debe aparecer 'municipio'
--    con geometría: esas se descartan a propósito en el pipeline.
select geocode_calidad, geocode_fuente,
       count(*) as filas,
       count(*) filter (where geom is not null) as con_geom
from pois
group by geocode_calidad, geocode_fuente
order by filas desc;

-- 5. El entregable de 199 €: puntos de demanda alrededor de un punto.
--    Sobre el centro de Sabadell. Con solo notarías cargadas devolverá vacío
--    —la función excluye tipo 'notaria' a propósito—, y eso es correcto:
--    lo que se comprueba aquí es que la función corre y usa el índice.
select * from puntos_de_demanda(41.5431, 2.1097, 1000) limit 10;

-- 6. Y la traza de la propia ingesta.
select fuente, ambito, estado, registros, inicio, fin, mensaje
from ingestas
order by inicio desc
limit 5;
