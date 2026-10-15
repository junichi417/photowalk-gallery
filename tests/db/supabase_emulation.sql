-- ローカルの PostgreSQL で Supabase の「認証・権限まわり」を再現するための下地。
-- 本番の Supabase には最初からあるので、本番では実行しない（テスト専用）。
--
-- 再現しているもの
--  * ロール anon / authenticated / service_role（service_role は RLS を無視できる）
--  * auth.users と auth.uid()（ログイン中の人のID。JWT の sub から取る）
--  * storage.buckets / storage.objects（RLS 有効・ポリシーなし）
--  * Supabase の既定権限：public スキーマの新しいテーブル・関数に anon/authenticated が
--    最初から全権限を持つ（＝RLS と revoke で守らないと穴が開く、という厳しめの条件）

create role anon nologin noinherit;
create role authenticated nologin noinherit;
create role service_role nologin noinherit bypassrls;

create schema extensions;
create schema auth;
create schema storage;
grant usage on schema public, extensions to anon, authenticated, service_role;
grant usage on schema auth, storage to anon, authenticated, service_role;

create table auth.users (
  id uuid primary key,
  email text unique,
  email_confirmed_at timestamptz
);

create function auth.uid() returns uuid language sql stable as $$
  select nullif(
    coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''),
             nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'),
    '')::uuid
$$;
grant execute on function auth.uid() to anon, authenticated, service_role;

create table storage.buckets (
  id text primary key, name text, public boolean default false,
  file_size_limit bigint, allowed_mime_types text[]
);
create table storage.objects (
  id uuid primary key default gen_random_uuid(),
  bucket_id text references storage.buckets(id), name text, owner uuid
);
alter table storage.objects enable row level security;
grant all on storage.objects to anon, authenticated, service_role;
grant select on storage.buckets to anon, authenticated, service_role;

-- Supabase の既定権限
alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
alter default privileges in schema public grant execute on functions to anon, authenticated, service_role;
