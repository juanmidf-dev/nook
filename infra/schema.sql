-- ============================================================
-- NOOK · Esquema de datos (PostgreSQL + PostGIS / Supabase)
-- ============================================================
-- Ejecutar en el SQL editor de Supabase o vía `psql -f infra/schema.sql`.
-- Idempotente: se puede volver a lanzar sin romper nada.

create extension if not exists postgis;
create extension if not exists pg_trgm;      -- fuzzy matching para deduplicar POIs
create extension if not exists unaccent;     -- normalización de nombres en español

-- ------------------------------------------------------------
-- 1. Tipos
-- ------------------------------------------------------------

do $$ begin
  create type poi_tipo as enum ('notaria', 'banco', 'inmobiliaria', 'abogados', 'gestoria', 'registro');
exception when duplicate_object then null; end $$;

do $$ begin
  create type poi_fuente as enum (
    'notariado',          -- Consejo General del Notariado / Guía Notarial
    'colegio_notarial',   -- webs de los 17 colegios notariales
    'bde',                -- Banco de España, registro de oficinas
    'overture',           -- Overture Maps Places
    'osm',                -- OpenStreetMap / Overpass
    'google',             -- Google Places (solo validación en vivo, NO se persiste)
    'icab_ica',           -- censos de Colegios de Abogados
    'manual'
  );
exception when duplicate_object then null; end $$;

-- Para las bases de datos ya creadas antes de que existiera este valor: el
-- bloque de arriba no se vuelve a ejecutar porque el tipo ya existe, asi que
-- el valor nuevo hay que anadirlo aparte. `if not exists` lo hace idempotente.
alter type poi_tipo add value if not exists 'gestoria';

-- ------------------------------------------------------------
-- 2. Referencia geográfica
-- ------------------------------------------------------------

create table if not exists municipios (
  cod_ine       text primary key,              -- 5 dígitos: provincia(2) + municipio(3)
  nombre        text not null,
  provincia     text not null,
  cod_provincia text not null,
  ccaa          text not null,
  poblacion     integer,
  geom          geometry(MultiPolygon, 4326)
);
create index if not exists municipios_geom_idx on municipios using gist (geom);
create index if not exists municipios_nombre_idx on municipios using gin (nombre gin_trgm_ops);

-- Secciones censales: la unidad con la que repartimos población dentro del municipio.
create table if not exists secciones_censales (
  cusec      text primary key,                 -- código de sección censal del INE
  cod_ine    text references municipios(cod_ine),
  poblacion  integer,
  geom       geometry(MultiPolygon, 4326)
);
create index if not exists secciones_geom_idx on secciones_censales using gist (geom);

-- ------------------------------------------------------------
-- 3. Puntos de interés (competencia + demanda)
-- ------------------------------------------------------------
-- Una sola tabla con discriminador de tipo: el motor de calor hace una
-- única consulta espacial en vez de cuatro, y añadir una quinta fuente de
-- demanda en el futuro no toca el esquema.

create table if not exists pois (
  id                uuid primary key default gen_random_uuid(),
  tipo              poi_tipo   not null,
  fuente            poi_fuente not null,
  fuente_id         text       not null,       -- id estable en el origen
  nombre            text,
  direccion         text,
  cp                text,
  municipio         text,
  -- Sin clave ajena a municipios a proposito: ver la nota al final del
  -- fichero. El codigo INE que publica el Banco de Espana es bueno, pero
  -- `municipios` arranca vacia y la FK tiraria el lote entero.
  cod_ine           text,
  provincia         text,
  telefono          text,
  email             text,
  web               text,
  lat               double precision,
  lon               double precision,
  geom              geography(Point, 4326),
  geocode_fuente    text,                      -- cartociudad | nominatim | origen | overture
  geocode_calidad   text,                      -- portal | via | municipio | desconocida
  extra             jsonb not null default '{}'::jsonb,
  activo            boolean not null default true,
  visto_en          timestamptz not null default now(),
  creado_en         timestamptz not null default now(),
  actualizado_en    timestamptz not null default now(),
  unique (fuente, fuente_id)
);
create index if not exists pois_geom_idx on pois using gist (geom);
create index if not exists pois_tipo_idx on pois (tipo) where activo;
create index if not exists pois_muni_idx on pois (cod_ine, tipo) where activo;
create index if not exists pois_nombre_idx on pois using gin (nombre gin_trgm_ops);

comment on column pois.extra is
  'notaría: {notario, colegio, plaza}. banco: {entidad, cod_entidad, cod_oficina}. overture: {categorias, confianza}.';

-- Deduplicación: pares detectados como el mismo sitio en fuentes distintas.
create table if not exists poi_duplicados (
  id_principal   uuid references pois(id) on delete cascade,
  id_duplicado   uuid references pois(id) on delete cascade,
  similitud      double precision,
  distancia_m    double precision,
  primary key (id_principal, id_duplicado)
);

-- ------------------------------------------------------------
-- 4. Rejilla H3 y mapa de calor
-- ------------------------------------------------------------

create table if not exists celdas (
  h3         text primary key,                 -- índice H3 en hexadecimal
  resolucion smallint not null,
  cod_ine    text references municipios(cod_ine),
  centro     geography(Point, 4326) not null,
  geom       geometry(Polygon, 4326) not null,
  poblacion  double precision default 0        -- repartida desde secciones censales
);
create index if not exists celdas_geom_idx on celdas using gist (geom);
create index if not exists celdas_muni_idx on celdas (cod_ine);

-- Un escenario = un juego de ponderaciones. El notario puede mover sliders y
-- el front recalcula contra un escenario guardado o al vuelo.
create table if not exists escenarios (
  id            uuid primary key default gen_random_uuid(),
  nombre        text not null,
  es_por_defecto boolean not null default false,
  -- pesos por tipo de POI; negativo = competencia
  pesos         jsonb not null default
    '{"notaria": -3, "banco": 1, "inmobiliaria": 1, "abogados": 1}'::jsonb,
  -- sigma del kernel gaussiano, en metros: a qué distancia deja de influir un punto
  bandwidth_m   integer not null default 600,
  peso_poblacion double precision not null default 1.0,
  creado_en     timestamptz not null default now()
);

create table if not exists celda_scores (
  h3            text not null references celdas(h3) on delete cascade,
  escenario_id  uuid not null references escenarios(id) on delete cascade,
  demanda       double precision not null,     -- bruto, antes de normalizar
  competencia   double precision not null,
  score         double precision not null,     -- 0-100, normalizado dentro del municipio
  detalle       jsonb not null default '{}'::jsonb,  -- aportación por tipo de POI
  calculado_en  timestamptz not null default now(),
  primary key (h3, escenario_id)
);
create index if not exists celda_scores_score_idx on celda_scores (escenario_id, score desc);

-- ------------------------------------------------------------
-- 5. Locales en alquiler (fase Idealista)
-- ------------------------------------------------------------

create table if not exists locales (
  id             uuid primary key default gen_random_uuid(),
  fuente         text not null,                -- idealista | fotocasa | manual
  fuente_id      text not null,
  titulo         text,
  direccion      text,
  cod_ine        text,                          -- sin FK, igual que pois
  precio_mes     numeric,
  superficie_m2  numeric,
  planta         text,
  url            text,
  lat            double precision,
  lon            double precision,
  geom           geography(Point, 4326),
  h3             text,
  publicado_en   date,
  visto_en       timestamptz not null default now(),
  activo         boolean not null default true,
  extra          jsonb not null default '{}'::jsonb,
  unique (fuente, fuente_id)
);
create index if not exists locales_geom_idx on locales using gist (geom);
create index if not exists locales_h3_idx on locales (h3) where activo;

-- ------------------------------------------------------------
-- 6. Trazabilidad de las ingestas
-- ------------------------------------------------------------

create table if not exists ingestas (
  id           uuid primary key default gen_random_uuid(),
  fuente       poi_fuente not null,
  ambito       text,                            -- 'ES', 'cataluna', '08' (provincia)...
  inicio       timestamptz not null default now(),
  fin          timestamptz,
  estado       text not null default 'en_curso', -- en_curso | ok | error
  registros    integer,
  nuevos       integer,
  actualizados integer,
  bajas        integer,
  mensaje      text
);

-- ------------------------------------------------------------
-- 6.bis. Geometria derivada de lat/lon
-- ------------------------------------------------------------
-- Los extractores escriben por PostgREST y solo mandan `lat` y `lon`: la API
-- REST no puede construir un `geography`. Sin esto la columna `geom` se queda
-- a NULL para siempre, y como los indices espaciales y `puntos_de_demanda()`
-- cuelgan de ella, el resultado es que la tabla se llena, todo parece
-- correcto y las consultas por distancia devuelven vacio. Es justo el tipo de
-- fallo que no da la cara hasta que un cliente pregunta por que su informe
-- sale sin puntos de demanda.

create or replace function geom_desde_latlon() returns trigger
language plpgsql as $$
begin
  new.geom := case
    when new.lat is null or new.lon is null then null
    -- Ojo al orden: st_makepoint es (x, y), o sea (lon, lat). Invertirlo
    -- coloca Sabadell en algun punto de Somalia y no da ningun error.
    else st_setsrid(st_makepoint(new.lon, new.lat), 4326)::geography
  end;
  return new;
end $$;

drop trigger if exists pois_geom on pois;
create trigger pois_geom
  before insert or update on pois
  for each row execute function geom_desde_latlon();

drop trigger if exists locales_geom on locales;
create trigger locales_geom
  before insert or update on locales
  for each row execute function geom_desde_latlon();

-- Relleno de lo que ya estuviera escrito sin geometria.
update pois    set geom = st_setsrid(st_makepoint(lon, lat), 4326)::geography
  where geom is null and lat is not null and lon is not null;
update locales set geom = st_setsrid(st_makepoint(lon, lat), 4326)::geography
  where geom is null and lat is not null and lon is not null;

-- ------------------------------------------------------------
-- 6.ter. Retirada de las claves ajenas a municipios
-- ------------------------------------------------------------
-- Idempotencia hacia atras: si se aplico una version anterior del esquema,
-- estas FK ya existen y hay que quitarlas.
--
-- El motivo: `municipios` es una tabla de referencia que se carga del INE, y
-- todavia no hay nada en el pipeline que la pueble. El Banco de Espana si
-- publica el codigo INE de cada oficina, asi que `pois.cod_ine` viene relleno
-- desde la primera ingesta y la FK rechazaria el lote completo de 500
-- registros. Descartar el dato para que encaje seria peor: es un dato bueno.
--
-- Cuando `municipios` este cargada se puede recuperar la integridad sin
-- bloquear nada:
--   alter table pois add constraint pois_cod_ine_fkey
--     foreign key (cod_ine) references municipios(cod_ine) not valid;
--   alter table pois validate constraint pois_cod_ine_fkey;

alter table pois    drop constraint if exists pois_cod_ine_fkey;
alter table locales drop constraint if exists locales_cod_ine_fkey;

-- ------------------------------------------------------------
-- 7. Vista de servicio para el front
-- ------------------------------------------------------------

create or replace view v_heatmap as
select
  c.h3,
  c.cod_ine,
  c.geom,
  s.escenario_id,
  s.score,
  s.demanda,
  s.competencia,
  s.detalle,
  c.poblacion
from celdas c
join celda_scores s on s.h3 = c.h3;

-- Puntos de demanda alrededor de una coordenada: es el entregable de 199 €.
create or replace function puntos_de_demanda(
  p_lat double precision,
  p_lon double precision,
  p_radio_m integer default 1000
)
returns table (
  tipo poi_tipo, nombre text, direccion text, telefono text,
  email text, web text, distancia_m double precision
)
language sql stable as $$
  select p.tipo, p.nombre, p.direccion, p.telefono, p.email, p.web,
         round(st_distance(p.geom, st_makepoint(p_lon, p_lat)::geography)::numeric, 0)::double precision
  from pois p
  where p.activo
    and p.tipo <> 'notaria'
    and st_dwithin(p.geom, st_makepoint(p_lon, p_lat)::geography, p_radio_m)
  order by 7;
$$;

-- Escenario por defecto con las ponderaciones del documento de producto.
insert into escenarios (nombre, es_por_defecto)
select 'Por defecto', true
where not exists (select 1 from escenarios where es_por_defecto);

-- ------------------------------------------------------------
-- 9. Privilegios
-- ------------------------------------------------------------
-- Los proyectos nuevos de Supabase ya no conceden privilegios automaticos
-- sobre las tablas de `public`: sin esto, la ingesta recibe un 403 con
-- "permission denied for table ingestas" aunque la clave secreta sea
-- correcta. El esquema se los da el mismo, para no depender de como venga
-- configurado el proyecto.

grant usage on schema public to service_role;
grant all on all tables    in schema public to service_role;
grant all on all sequences in schema public to service_role;
grant execute on all functions in schema public to service_role;

-- Y para lo que se cree despues de este fichero.
alter default privileges in schema public grant all on tables    to service_role;
alter default privileges in schema public grant all on sequences to service_role;

-- A `anon` y `authenticated` NO se les concede nada, y es deliberado.
--
-- La clave publicable viaja en el bundle de JavaScript: cualquiera que abra
-- el inspector la tiene. Conceder lectura sobre `pois` haria que el censo de
-- competencia y los puntos de demanda —que es exactamente el activo que se
-- vende a 500 y 199 euros— se pudiera descargar entero con una peticion.
--
-- Cuando el frontend deje de usar el corte estatico y tenga que leer de aqui,
-- la via es una vista con solo lo que el mapa necesita (celda, score, sin
-- datos de contacto) y una politica RLS que la abra, nunca un grant sobre las
-- tablas base.

-- Defensa en profundidad: con RLS activada y sin politicas, cualquier rol que
-- no sea service_role no ve nada aunque alguien le conceda un grant por error.
-- Lista explicita y no un recorrido de pg_tables: `public` tambien contiene
-- `spatial_ref_sys`, que la trae PostGIS, no es nuestra y no se puede alterar
-- ("must be owner of table spatial_ref_sys"). Enumerar tambien evita activar
-- RLS sin querer sobre lo que instale una extension futura.
do $$
declare t text;
begin
  foreach t in array array[
    'municipios', 'secciones_censales', 'pois', 'poi_duplicados',
    'celdas', 'escenarios', 'celda_scores', 'locales', 'ingestas'
  ] loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end $$;
