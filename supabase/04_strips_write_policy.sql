-- Add write permissions for strips table to allow beach import
-- Run this after enabling RLS on the strips table

-- Allow anon users to insert and update strips (for import script)
-- In production, you'd want this restricted to admin users only

CREATE POLICY "anon insert strips"
  ON strips FOR INSERT
  WITH CHECK (true);

CREATE POLICY "anon update strips"  
  ON strips FOR UPDATE
  USING (true)
  WITH CHECK (true);

-- Optional: If you want to allow deletion as well
CREATE POLICY "anon delete strips"
  ON strips FOR DELETE
  USING (true);

-- Note: The existing "public read strips" policy already allows SELECT
-- To check existing policies:
-- SELECT * FROM pg_policies WHERE tablename = 'strips';