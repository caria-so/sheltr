-- Add polygon support to strips table for imported beaches
-- Run after 01_fresh_schema_and_seed.sql

-- Add new columns for polygon beaches
ALTER TABLE strips ADD COLUMN IF NOT EXISTS geometry jsonb;
ALTER TABLE strips ADD COLUMN IF NOT EXISTS area_m2 double precision;
ALTER TABLE strips ADD COLUMN IF NOT EXISTS source text DEFAULT 'manual';

-- Index for faster spatial queries
CREATE INDEX IF NOT EXISTS strips_source_idx ON strips(source);
CREATE INDEX IF NOT EXISTS strips_area_idx ON strips(area_m2) WHERE area_m2 IS NOT NULL;

-- Add PostGIS geography index if available (for proper spatial queries)
-- Note: Requires PostGIS extension which Supabase has enabled
CREATE INDEX IF NOT EXISTS strips_location_idx ON strips USING GIST(
  ST_MakePoint(lon, lat)
);

-- Function to check if a point is near a beach polygon
CREATE OR REPLACE FUNCTION point_near_beach(
  user_lat double precision,
  user_lon double precision,
  beach_geometry jsonb,
  max_distance_m double precision DEFAULT 200
) RETURNS boolean AS $$
DECLARE
  coord jsonb;
  beach_lat double precision;
  beach_lon double precision;
  distance double precision;
BEGIN
  -- Simple proximity check to any polygon vertex
  FOR coord IN SELECT * FROM jsonb_array_elements(beach_geometry)
  LOOP
    beach_lat := (coord->0)::double precision;
    beach_lon := (coord->1)::double precision;
    
    -- Haversine distance calculation
    distance := 6371000 * 2 * asin(sqrt(
      power(sin(radians(beach_lat - user_lat) / 2), 2) +
      cos(radians(user_lat)) * cos(radians(beach_lat)) *
      power(sin(radians(beach_lon - user_lon) / 2), 2)
    ));
    
    IF distance <= max_distance_m THEN
      RETURN true;
    END IF;
  END LOOP;
  
  RETURN false;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- View for beaches with calculated properties
CREATE OR REPLACE VIEW beaches_enriched AS
SELECT 
  s.*,
  CASE 
    WHEN geometry IS NOT NULL THEN jsonb_array_length(geometry)
    ELSE 0
  END as vertex_count,
  CASE
    WHEN area_m2 > 100000 THEN 'large'
    WHEN area_m2 > 10000 THEN 'medium'
    WHEN area_m2 > 0 THEN 'small'
    ELSE 'point'
  END as size_category
FROM strips s;

-- Update RLS policies to include new columns
-- (Existing policies should still work, but documenting for completeness)