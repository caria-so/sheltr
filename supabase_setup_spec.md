# Sheltr — Supabase Setup Spec

Version 0.2

---

## 1. Create the Project

1. Go to https://supabase.com and sign in
2. New project → name it `sheltr` (or keep an existing project; this doc matches the schema Sheltr uses)
3. Choose region: `eu-central-1` (Frankfurt — closest to Sardinia)
4. Save the database password somewhere safe
5. Once provisioned, go to Project Settings → API and copy:
   - `Project URL` → `SUPABASE_URL`
   - `anon public` key → `SUPABASE_ANON_KEY`

These two values are all the webapp needs. No backend.

---

## 2. Database Schema

Ready-to-run files (same content as below): `supabase/01_fresh_schema_and_seed.sql` then create the Storage bucket, then `supabase/02_storage_policies.sql`.

Run this in the Supabase SQL editor (Database → SQL Editor → New query).

```sql
-- ─── Extensions ────────────────────────────────────────────────────────────

create extension if not exists "uuid-ossp";
create extension if not exists "postgis";   -- for geo queries later


-- ─── Strips ────────────────────────────────────────────────────────────────
-- One record per uninterrupted sand strip.
-- Manually curated. Not user-generated.

create table strips (
  id              text primary key,           -- e.g. 'capitana', 'poetto_west'
  name            text not null,              -- display name
  parent_name     text,                       -- beach family, e.g. 'Poetto'
  lat             double precision not null,
  lon             double precision not null,
  facing_deg      double precision,           -- seaward direction (0=N, 90=E)
  openness_angle  double precision,           -- angular width of sea opening
  notes           text,
  validated       boolean default false,
  created_at      timestamptz default now()
);


-- ─── Score Snapshots ───────────────────────────────────────────────────────
-- Auto-written every time /api/score is called (no user action needed).
-- Captures conditions + predicted scores for ALL strips in one row.

create table score_snapshots (
  id                  uuid primary key default uuid_generate_v4(),
  recorded_at         timestamptz not null default now(),

  -- Observer position
  observer_lat        double precision not null,
  observer_lon        double precision not null,
  observer_accuracy   double precision,

  -- Fetched conditions
  wind_dir_deg        double precision,
  wind_speed_kmh      double precision,
  wind_gusts_kmh      double precision,
  terrain_shield_json jsonb,            -- { "0": 0.8, "22.5": 0.3, ... }

  -- Predicted scores for every strip: { "capitana": 7.2, "poetto_west": 4.1, ... }
  scores_json         jsonb not null
);

create index on score_snapshots (recorded_at desc);
create index on score_snapshots (wind_dir_deg);


-- ─── Observations ──────────────────────────────────────────────────────────
-- User-triggered, linked to a snapshot. Just the felt experience + pointer.

create table observations (
  id                  uuid primary key default uuid_generate_v4(),
  snapshot_id         uuid references score_snapshots(id) on delete set null,
  strip_id            text references strips(id) on delete set null,

  -- User observation (the ground truth)
  felt_sand_wind      text check (felt_sand_wind in ('none','light','moderate','strong')),
  felt_water_state    text check (felt_water_state in ('flat','light_chop','choppy','rough')),
  felt_comfort        integer check (felt_comfort between 1 and 5),
  notes               text,
  image_url           text,               -- public URL in Supabase Storage

  created_at          timestamptz default now()
);

create index on observations (strip_id, created_at desc);
create index on observations (snapshot_id);


-- ─── Terrain Cache ─────────────────────────────────────────────────────────
-- Avoid re-fetching elevation for coordinates we've already sampled.
-- Key: rounded lat/lon at ~10m precision.

create table terrain_cache (
  lat         double precision not null,
  lon         double precision not null,
  elevation_m double precision not null,
  fetched_at  timestamptz default now(),
  primary key (lat, lon)
);


-- ─── Strip Fingerprints ────────────────────────────────────────────────────
-- Computed exposure profiles per strip.
-- Rebuilt whenever enough new observations exist.

create table strip_fingerprints (
  strip_id          text primary key references strips(id),
  fingerprint       jsonb not null,   -- { "0": 0.8, "22.5": 0.6, ... } exposure per direction
  observation_count integer,          -- how many observations went into this
  last_computed_at  timestamptz default now()
);
```

---

## 3. Row Level Security

The app runs entirely in the browser with the anon key. We need RLS so anyone can read strips but only authenticated users (you) can write observations.

For MVP, simplest approach: disable auth entirely and use a shared secret in the app. Add proper auth later when other people use it.

```sql
-- Enable RLS on all tables
alter table strips              enable row level security;
alter table score_snapshots     enable row level security;
alter table observations        enable row level security;
alter table terrain_cache       enable row level security;
alter table strip_fingerprints  enable row level security;

-- Public read on strips and fingerprints
create policy "public read strips"
  on strips for select using (true);

create policy "public read fingerprints"
  on strip_fingerprints for select using (true);

-- Full access for anon on snapshots, observations, and terrain cache (MVP)
create policy "anon full access snapshots"
  on score_snapshots for all using (true) with check (true);

create policy "anon full access observations"
  on observations for all using (true) with check (true);

create policy "anon full access terrain cache"
  on terrain_cache for all using (true) with check (true);
```

---

## 3b. Storage Bucket for Photos

Go to **Storage** in the Supabase dashboard, then create a new bucket:

- **Name:** `observation-photos`
- **Public:** Yes (so images are accessible via public URL)
- **File size limit:** 10 MB
- **Allowed MIME types:** `image/*`

Then add policies to allow uploads via the anon key (for MVP). Run `supabase/02_storage_policies.sql` — it only `CREATE`s when a policy is missing (idempotent, no `DROP`, no destructive-query warning). `02_storage_policies_idempotent.sql` is the same.

```sql
create policy "anon upload observation photos"
  on storage.objects for insert
  with check (bucket_id = 'observation-photos');

create policy "public read observation photos"
  on storage.objects for select
  using (bucket_id = 'observation-photos');
```

---

## 4. Seed the Strip Database

```sql
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
 'No terrain shielding. Open. Should score lower than west end under W/NW wind.');
```

---

## 5. Key Queries

### Predicted score time series for a strip (no user observations needed)
```sql
select
  recorded_at,
  wind_dir_deg,
  wind_speed_kmh,
  scores_json->>'capitana' as predicted
from score_snapshots
order by recorded_at desc;
```

### Model accuracy — predicted vs felt comfort
```sql
select
  s.name,
  round(avg((snap.scores_json->>o.strip_id)::numeric), 1) as avg_predicted,
  round(avg(o.felt_comfort)::numeric, 1)                   as avg_felt,
  count(*)                                                  as visits
from observations o
join score_snapshots snap on snap.id = o.snapshot_id
join strips s on s.id = o.strip_id
where o.felt_comfort is not null
group by s.name
order by s.name;
```

### All observations under NW wind (Mistral) ± 30°
```sql
select
  s.name,
  snap.recorded_at,
  snap.wind_speed_kmh,
  (snap.scores_json->>o.strip_id)::numeric as predicted,
  o.felt_comfort
from observations o
join score_snapshots snap on snap.id = o.snapshot_id
join strips s on s.id = o.strip_id
where
  snap.wind_dir_deg between 285 and 345
  and o.felt_comfort is not null
order by snap.recorded_at desc;
```

### Snapshot count and wind coverage
```sql
select
  count(*) as total_snapshots,
  count(distinct date_trunc('day', recorded_at)) as distinct_days,
  min(recorded_at) as first,
  max(recorded_at) as last
from score_snapshots;
```

---

## 6. Webapp Environment Variables

The webapp needs only these two values, hardcoded or in a `.env` file:

```
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_ANON_KEY=eyJhbGci...
```

Include the Supabase JS client from CDN — no build step needed:

```html
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script>
  const { createClient } = supabase;
  const db = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
</script>
```

---

## 7. Data Flow Summary

```
User arrives at beach
        ↓
App gets GPS position
        ↓
App calls /api/score (lat, lon)
  ├── Open-Meteo:     wind_dir, wind_speed, gusts
  └── OpenTopoData:   80-point radial elevation profile
        ↓
Server computes scores for ALL strips
        ↓
Server auto-writes → score_snapshots   ← happens silently, every session
  (wind, terrain shield, all predicted scores)
        ↓
Returns ranked list + snapshot_id to frontend
        ↓
Optionally, user records felt conditions:
  ├── sand wind felt
  ├── water state
  └── comfort 1–5
        ↓
App writes → observations (snapshot_id + strip_id + felt data)
        ↓
Over time:
  • score_snapshots accumulate automatically — data even without user input
  • observations link ground truth to conditions via snapshot FK
  • model accuracy = join snapshots.scores_json with observations.felt_comfort
```

---

## 8. Migration from v0.1

If you already have the old `observations` table (with wind/terrain columns), run this to migrate:

```sql
-- 1. Create score_snapshots table
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

alter table score_snapshots enable row level security;
create policy "anon full access snapshots"
  on score_snapshots for all using (true) with check (true);

-- 2. Migrate existing observations into snapshots, then slim observations
-- (only needed if you have existing data you want to preserve)
insert into score_snapshots (recorded_at, observer_lat, observer_lon, observer_accuracy,
  wind_dir_deg, wind_speed_kmh, wind_gusts_kmh, terrain_shield_json, scores_json)
select recorded_at, gps_lat, gps_lon, gps_accuracy_m,
  wind_dir_deg, wind_speed_kmh, wind_gusts_kmh, terrain_shield,
  jsonb_build_object(coalesce(strip_id, '_unknown'), coalesce(predicted_score, 0))
from observations;

-- 3. Add snapshot_id column and backfill
alter table observations add column snapshot_id uuid references score_snapshots(id) on delete set null;
create index on observations (snapshot_id);

update observations o set snapshot_id = s.id
from score_snapshots s
where s.recorded_at = o.recorded_at
  and s.observer_lat = o.gps_lat and s.observer_lon = o.gps_lon;

-- 4. Drop the now-redundant columns
alter table observations
  drop column if exists gps_lat,
  drop column if exists gps_lon,
  drop column if exists gps_accuracy_m,
  drop column if exists recorded_at,
  drop column if exists wind_dir_deg,
  drop column if exists wind_speed_kmh,
  drop column if exists wind_gusts_kmh,
  drop column if exists wind_fetched_at,
  drop column if exists terrain_profile_raw,
  drop column if exists terrain_shield,
  drop column if exists predicted_score,
  drop column if exists app_version;

-- 5. Drop old indexes that reference removed columns
drop index if exists observations_wind_dir_deg_idx;
drop index if exists observations_strip_id_recorded_at_idx;

-- 6. Add image_url column
alter table observations add column if not exists image_url text;
```

If starting fresh, just run the full schema in Section 2 + Section 3b (storage bucket) instead.

---

## 9. What Comes After MVP

Once you have ~20–30 observations across different wind days:

- Recompute `strip_fingerprints` from real data instead of pure geometry
- Compare computed fingerprint to geometric fingerprint — where they diverge, local terrain is doing something the geometry didn't predict
- That divergence is itself the finding: it tells you which beaches need manual terrain corrections

The database is designed to support this from day one.
