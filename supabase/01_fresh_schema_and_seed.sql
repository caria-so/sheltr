-- Sheltr — run once in Supabase → SQL Editor (empty / new project).
-- Order: this file first, then create Storage bucket, then 02_storage_policies.sql

-- ─── Extensions ────────────────────────────────────────────────────────────

create extension if not exists "uuid-ossp";
create extension if not exists "postgis";


-- ─── Strips ──────────────────────────────────────────────────────────────────

create table strips (
  id              text primary key,
  name            text not null,
  parent_name     text,
  lat             double precision not null,
  lon             double precision not null,
  facing_deg      double precision,
  openness_angle  double precision,
  notes           text,
  validated       boolean default false,
  created_at      timestamptz default now()
);


-- ─── Score snapshots ─────────────────────────────────────────────────────────

create table score_snapshots (
  id                  uuid primary key default uuid_generate_v4(),
  recorded_at         timestamptz not null default now(),
  observer_lat        double precision not null,
  observer_lon        double precision not null,
  observer_accuracy   double precision,
  wind_dir_deg        double precision,
  wind_speed_kmh      double precision,
  wind_gusts_kmh      double precision,
  terrain_shield_json jsonb,
  scores_json         jsonb not null
);

create index on score_snapshots (recorded_at desc);
create index on score_snapshots (wind_dir_deg);


-- ─── Observations ────────────────────────────────────────────────────────────

create table observations (
  id                  uuid primary key default uuid_generate_v4(),
  snapshot_id         uuid references score_snapshots(id) on delete set null,
  strip_id            text references strips(id) on delete set null,
  felt_sand_wind      text check (felt_sand_wind in ('none','light','moderate','strong')),
  felt_water_state    text check (felt_water_state in ('flat','light_chop','choppy','rough')),
  felt_comfort        integer check (felt_comfort between 1 and 5),
  notes               text,
  image_url           text,
  created_at          timestamptz default now()
);

create index on observations (strip_id, created_at desc);
create index on observations (snapshot_id);


-- ─── Terrain cache ───────────────────────────────────────────────────────────

create table terrain_cache (
  lat         double precision not null,
  lon         double precision not null,
  elevation_m double precision not null,
  fetched_at  timestamptz default now(),
  primary key (lat, lon)
);


-- ─── Strip fingerprints ──────────────────────────────────────────────────────

create table strip_fingerprints (
  strip_id          text primary key references strips(id),
  fingerprint       jsonb not null,
  observation_count integer,
  last_computed_at  timestamptz default now()
);


-- ─── Row Level Security ──────────────────────────────────────────────────────

alter table strips              enable row level security;
alter table score_snapshots     enable row level security;
alter table observations        enable row level security;
alter table terrain_cache       enable row level security;
alter table strip_fingerprints  enable row level security;

create policy "public read strips"
  on strips for select using (true);

create policy "public read fingerprints"
  on strip_fingerprints for select using (true);

create policy "anon full access snapshots"
  on score_snapshots for all using (true) with check (true);

create policy "anon full access observations"
  on observations for all using (true) with check (true);

create policy "anon full access terrain cache"
  on terrain_cache for all using (true) with check (true);


-- ─── Seed strips (safe to re-run) ────────────────────────────────────────────

insert into strips (id, name, parent_name, lat, lon, facing_deg, notes) values
('capitana',
 'Capitana',
 'Capitana',
 39.205068, 9.318388,
 10.0,
 'Short uniform beach facing Gulf of Cagliari (N). Start slightly more sheltered than end but difference is marginal.'),
('mortorius',
 'Mortorius',
 'Mortorius',
 39.199177, 9.325747,
 null,
 'Opposite orientation to Baja Azzurra. Control case — should behave differently under same wind.'),
('baja_azzurra_cala',
 'Baja Azzurra (cala)',
 'Baja Azzurra',
 39.201005, 9.323482,
 null,
 'Cala side. Separated from promontory strip by cliffs.'),
('baja_azzurra_promontory',
 'Baja Azzurra (promontory)',
 'Baja Azzurra',
 39.200300, 9.322702,
 null,
 'Small strip near promontory. Cliffs present. Expect higher exposure than cala.'),
('poetto_west',
 'Poetto (Marina Piccola)',
 'Poetto',
 39.2130, 9.1350,
 180.0,
 'Sheltered from W/NW by Sella del Diavolo mountain. Key terrain shielding test case.'),
('poetto_east',
 'Poetto (Margine Rosso)',
 'Poetto',
 39.2200, 9.1900,
 180.0,
 'No terrain shielding. Open. Should score lower than west end under W/NW wind.')
on conflict (id) do nothing;
