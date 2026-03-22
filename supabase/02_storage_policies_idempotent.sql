-- Same behaviour as 02_storage_policies.sql (idempotent, no DROP).
-- Kept so old links still work. Prefer 02_storage_policies.sql.

do $body$
begin
  if not exists (
    select 1
    from pg_policy p
    join pg_class c on c.oid = p.polrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'storage'
      and c.relname = 'objects'
      and p.polname = 'anon upload observation photos'
  ) then
    create policy "anon upload observation photos"
      on storage.objects for insert
      with check (bucket_id = 'observation-photos');
  end if;

  if not exists (
    select 1
    from pg_policy p
    join pg_class c on c.oid = p.polrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'storage'
      and c.relname = 'objects'
      and p.polname = 'public read observation photos'
  ) then
    create policy "public read observation photos"
      on storage.objects for select
      using (bucket_id = 'observation-photos');
  end if;
end $body$;
