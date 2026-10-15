-- =====================================================================
-- 時譜舎フォトウォーク ギャラリー：データベース設定
--
-- 守りの考え方
--  * テーブルには参加者・第三者が直接書き込めない（RLSで全拒否）。
--    書き込みはすべて下の関数を通し、関数の中で「本人確認済みか・合言葉を通ったか・
--    締切前か・枚数上限内か」を判定する。
--  * 写真ファイルの保存は Edge Function（サーバー）だけが行う。
--    ストレージには参加者向けの書き込み権限を一切つけない。
--  * 締切はこのDBの events.submission_deadline が唯一の正。画面の表示は見た目だけ。
--  * 合言葉はハッシュ（bcrypt）でだけ保存する。平文はどこにも残さない。
-- =====================================================================

create extension if not exists pgcrypto with schema extensions;

-- ---------------------------------------------------------------------
-- テーブル
-- ---------------------------------------------------------------------
create table public.events (
  slug                 text primary key check (slug ~ '^[a-z0-9-]{1,64}$'),
  title                text not null,
  submission_deadline  timestamptz not null,
  submission_open      boolean not null default false,  -- 受付開始スイッチ（社長の承認後に true）
  invite_code_hash     text,                             -- 合言葉のハッシュ。null の間は誰も登録できない
  max_photos_per_user  int not null default 20 check (max_photos_per_user between 1 and 100),
  created_at           timestamptz not null default now()
);

create table public.admins (
  user_id uuid primary key references auth.users (id) on delete cascade
);

create table public.participants (
  id            uuid primary key default gen_random_uuid(),   -- 公開用ID（ログインIDとは別）
  user_id       uuid not null references auth.users (id) on delete cascade,
  event_slug    text not null references public.events (slug) on delete cascade,
  display_name  text check (display_name is null or char_length(display_name) between 1 and 30),
  sns_url       text check (sns_url is null or (char_length(sns_url) <= 300 and sns_url ~ '^https://[^[:space:]<>"]+$')),
  name_hidden   boolean not null default false,   -- 管理者が名前・SNSの表示を止める
  disabled      boolean not null default false,   -- 管理者が投稿を止める
  created_at    timestamptz not null default now(),
  unique (user_id, event_slug)
);

create table public.photos (
  id               uuid primary key default gen_random_uuid(),
  event_slug       text not null references public.events (slug) on delete cascade,
  participant_id   uuid not null references public.participants (id) on delete cascade,
  full_path        text not null unique,
  thumb_path       text not null unique,
  width            int not null check (width between 1 and 4096),
  height           int not null check (height between 1 and 4096),
  thumb_width      int not null check (thumb_width between 1 and 1024),
  thumb_height     int not null check (thumb_height between 1 and 1024),
  bytes            int not null check (bytes between 1 and 8388608),
  consent_own_photo boolean not null check (consent_own_photo),   -- 自分で撮った写真
  consent_people    boolean not null check (consent_people),      -- 写っている人の了承
  status           text not null default 'pending' check (status in ('pending', 'published', 'hidden')),
  created_at       timestamptz not null default now(),
  published_at     timestamptz
);
create index photos_event_status_idx on public.photos (event_slug, status, created_at);
create index photos_participant_idx on public.photos (participant_id);

-- 合言葉の試行記録（総当たり対策）
create table public.invite_attempts (
  id           bigint generated always as identity primary key,
  user_id      uuid not null,
  event_slug   text not null,
  success      boolean not null,
  attempted_at timestamptz not null default now()
);
create index invite_attempts_idx on public.invite_attempts (event_slug, attempted_at);

-- ---------------------------------------------------------------------
-- RLS：全テーブルで有効化。参加者が読めるのは「自分の行」だけ。書き込みポリシーは作らない
-- ---------------------------------------------------------------------
alter table public.events          enable row level security;
alter table public.admins          enable row level security;
alter table public.participants    enable row level security;
alter table public.photos          enable row level security;
alter table public.invite_attempts enable row level security;

create policy "本人は自分の参加者情報を読める" on public.participants
  for select to authenticated using (user_id = auth.uid());

create policy "本人は自分の写真を読める" on public.photos
  for select to authenticated using (
    participant_id in (select id from public.participants where user_id = auth.uid())
  );

-- Supabaseは既定で anon/authenticated にテーブル権限を付けるので、念のため書き込み権限も外す
revoke insert, update, delete, truncate on all tables in schema public from anon, authenticated;
revoke all on public.events, public.admins, public.invite_attempts from anon, authenticated;

-- ---------------------------------------------------------------------
-- 内部で使う判定
-- ---------------------------------------------------------------------
create or replace function public.is_admin()
returns boolean language sql stable security definer set search_path = public, pg_temp as $$
  select exists (select 1 from public.admins where user_id = auth.uid());
$$;

create or replace function public._accepting(p_event text)
returns boolean language sql stable security definer set search_path = public, pg_temp as $$
  select coalesce((select submission_open and now() <= submission_deadline
                   from public.events where slug = p_event), false);
$$;

-- 合言葉の正規化：前後の空白を除き、全角→半角（NFKC）、小文字に
create or replace function public._normalize_code(p text)
returns text language sql immutable as $$
  select lower(normalize(btrim(coalesce(p, '')), NFKC));
$$;

-- ---------------------------------------------------------------------
-- 公開：ギャラリーの一覧（誰でも呼べる。公開済みの写真だけ返す）
-- ---------------------------------------------------------------------
create or replace function public.get_gallery(p_event text)
returns table (
  id uuid, full_path text, thumb_path text,
  width int, height int, thumb_width int, thumb_height int,
  created_at timestamptz,
  participant_id uuid, display_name text, sns_url text
)
language sql stable security definer set search_path = public, pg_temp as $$
  select ph.id, ph.full_path, ph.thumb_path,
         ph.width, ph.height, ph.thumb_width, ph.thumb_height,
         ph.published_at,
         pa.id,
         case when pa.name_hidden then null else pa.display_name end,
         case when pa.name_hidden then null else pa.sns_url end
  from public.photos ph
  join public.participants pa on pa.id = ph.participant_id
  where ph.event_slug = p_event and ph.status = 'published'
  order by ph.published_at, ph.id;
$$;

-- 公開：受付状態（締切時刻・受付中か）
create or replace function public.get_event_status(p_event text)
returns table (slug text, title text, submission_deadline timestamptz, accepting boolean, server_now timestamptz)
language sql stable security definer set search_path = public, pg_temp as $$
  select e.slug, e.title, e.submission_deadline, public._accepting(e.slug), now()
  from public.events e where e.slug = p_event;
$$;

-- ---------------------------------------------------------------------
-- 参加者：合言葉で参加登録（メールの本人確認が済んでいる人だけ）
-- ---------------------------------------------------------------------
create or replace function public.redeem_invite(
  p_event text, p_code text, p_display_name text default null, p_sns_url text default null
) returns uuid
language plpgsql volatile security definer set search_path = public, extensions, pg_temp as $$
declare
  v_uid   uuid := auth.uid();
  v_hash  text;
  v_ok    boolean;
  v_pid   uuid;
begin
  if v_uid is null then
    raise exception 'not_authenticated' using errcode = '28000';
  end if;
  if not exists (select 1 from auth.users where id = v_uid and email_confirmed_at is not null) then
    raise exception 'email_not_confirmed' using errcode = '28000';
  end if;
  if not public._accepting(p_event) then
    raise exception 'submission_closed' using errcode = 'P0001';
  end if;

  -- 総当たり対策：1人あたり1時間に5回、イベント全体で10分に30回まで失敗を許す
  if (select count(*) from public.invite_attempts
      where user_id = v_uid and event_slug = p_event and not success
        and attempted_at > now() - interval '1 hour') >= 5
     or (select count(*) from public.invite_attempts
      where event_slug = p_event and not success
        and attempted_at > now() - interval '10 minutes') >= 30 then
    raise exception 'too_many_attempts' using errcode = 'P0001';
  end if;

  select invite_code_hash into v_hash from public.events where slug = p_event;
  v_ok := v_hash is not null
          and char_length(public._normalize_code(p_code)) between 1 and 100
          and extensions.crypt(public._normalize_code(p_code), v_hash) = v_hash;

  insert into public.invite_attempts (user_id, event_slug, success) values (v_uid, p_event, v_ok);
  if not v_ok then
    -- 失敗も記録を残したいので、例外ではなく null を返す
    return null;
  end if;

  insert into public.participants (user_id, event_slug, display_name, sns_url)
  values (v_uid, p_event, nullif(btrim(p_display_name), ''), nullif(btrim(p_sns_url), ''))
  on conflict (user_id, event_slug) do update
    set display_name = excluded.display_name, sns_url = excluded.sns_url
  returning id into v_pid;
  return v_pid;
end $$;

-- 参加者：表示名・SNSの変更（受付期間中のみ）
create or replace function public.update_my_profile(p_event text, p_display_name text, p_sns_url text)
returns void
language plpgsql volatile security definer set search_path = public, pg_temp as $$
begin
  if auth.uid() is null then raise exception 'not_authenticated' using errcode = '28000'; end if;
  if not public._accepting(p_event) then raise exception 'submission_closed' using errcode = 'P0001'; end if;
  update public.participants
     set display_name = nullif(btrim(p_display_name), ''), sns_url = nullif(btrim(p_sns_url), '')
   where user_id = auth.uid() and event_slug = p_event;
  if not found then raise exception 'not_participant' using errcode = '42501'; end if;
end $$;

-- ---------------------------------------------------------------------
-- 投稿：Edge Function だけが呼ぶ（本人のログイン情報で呼び、本人として判定する）
-- ---------------------------------------------------------------------
create or replace function public.begin_photo_upload(
  p_event text, p_consent_own_photo boolean, p_consent_people boolean,
  p_width int, p_height int, p_thumb_width int, p_thumb_height int, p_bytes int
) returns table (photo_id uuid, full_path text, thumb_path text)
language plpgsql volatile security definer set search_path = public, pg_temp as $$
declare
  v_pid  uuid;
  v_max  int;
  v_id   uuid := gen_random_uuid();
begin
  if auth.uid() is null then raise exception 'not_authenticated' using errcode = '28000'; end if;
  if not public._accepting(p_event) then raise exception 'submission_closed' using errcode = 'P0001'; end if;
  if not (coalesce(p_consent_own_photo, false) and coalesce(p_consent_people, false)) then
    raise exception 'consent_required' using errcode = 'P0001';
  end if;

  select id into v_pid from public.participants
   where user_id = auth.uid() and event_slug = p_event and not disabled;
  if v_pid is null then raise exception 'not_participant' using errcode = '42501'; end if;

  -- 同じ人の同時投稿で上限を超えないように、本人単位でロック
  perform pg_advisory_xact_lock(hashtextextended(v_pid::text, 0));
  select max_photos_per_user into v_max from public.events where slug = p_event;
  if (select count(*) from public.photos
       where participant_id = v_pid
         and (status <> 'pending' or created_at > now() - interval '10 minutes')) >= v_max then
    raise exception 'photo_limit_reached' using errcode = 'P0001';
  end if;

  return query
  insert into public.photos (id, event_slug, participant_id, full_path, thumb_path,
                             width, height, thumb_width, thumb_height, bytes,
                             consent_own_photo, consent_people)
  values (v_id, p_event, v_pid,
          p_event || '/' || v_id || '.jpg', p_event || '/' || v_id || '_t.jpg',
          p_width, p_height, p_thumb_width, p_thumb_height, p_bytes,
          p_consent_own_photo, p_consent_people)
  returning photos.id, photos.full_path, photos.thumb_path;
end $$;

-- 投稿の完了：ファイルの保存に成功したら自動掲載。サーバー（service_role）だけが呼べる。
-- 開始が締切前なら、完了が数分遅れても受け付ける
create or replace function public.finish_photo_upload(p_photo_id uuid)
returns void
language plpgsql volatile security definer set search_path = public, pg_temp as $$
begin
  update public.photos
     set status = 'published', published_at = now()
   where id = p_photo_id and status = 'pending'
     and created_at > now() - interval '10 minutes';
  if not found then raise exception 'upload_not_found' using errcode = 'P0001'; end if;
end $$;

-- 投稿の取り消し（保存に失敗したとき）。サーバーだけが呼べる
create or replace function public.abort_photo_upload(p_photo_id uuid)
returns void
language sql volatile security definer set search_path = public, pg_temp as $$
  delete from public.photos where id = p_photo_id and status = 'pending';
$$;

-- ---------------------------------------------------------------------
-- 管理者（社長）だけが使える操作
-- ---------------------------------------------------------------------
create or replace function public.admin_set_invite_code(p_event text, p_code text)
returns void
language plpgsql volatile security definer set search_path = public, extensions, pg_temp as $$
begin
  if not public.is_admin() then raise exception 'admin_only' using errcode = '42501'; end if;
  if char_length(public._normalize_code(p_code)) < 8 then
    raise exception 'code_too_short' using errcode = 'P0001';
  end if;
  update public.events
     set invite_code_hash = extensions.crypt(public._normalize_code(p_code), extensions.gen_salt('bf', 10))
   where slug = p_event;
end $$;

create or replace function public.admin_disable_invite_code(p_event text)
returns void
language plpgsql volatile security definer set search_path = public, pg_temp as $$
begin
  if not public.is_admin() then raise exception 'admin_only' using errcode = '42501'; end if;
  update public.events set invite_code_hash = null where slug = p_event;
end $$;

create or replace function public.admin_set_submission_open(p_event text, p_open boolean)
returns void
language plpgsql volatile security definer set search_path = public, pg_temp as $$
begin
  if not public.is_admin() then raise exception 'admin_only' using errcode = '42501'; end if;
  update public.events set submission_open = p_open where slug = p_event;
end $$;

-- 非公開／再公開
create or replace function public.admin_set_photo_hidden(p_photo_id uuid, p_hidden boolean)
returns void
language plpgsql volatile security definer set search_path = public, pg_temp as $$
begin
  if not public.is_admin() then raise exception 'admin_only' using errcode = '42501'; end if;
  update public.photos
     set status = case when p_hidden then 'hidden' else 'published' end,
         published_at = coalesce(published_at, now())
   where id = p_photo_id and status in ('published', 'hidden');
end $$;

-- 削除：行を消し、消すべきファイルの場所を返す（ファイルは Edge Function が消す）
create or replace function public.admin_delete_photo(p_photo_id uuid)
returns table (full_path text, thumb_path text)
language plpgsql volatile security definer set search_path = public, pg_temp as $$
begin
  if not public.is_admin() then raise exception 'admin_only' using errcode = '42501'; end if;
  return query delete from public.photos where id = p_photo_id
    returning photos.full_path, photos.thumb_path;
end $$;

create or replace function public.admin_set_participant(p_participant_id uuid, p_name_hidden boolean, p_disabled boolean)
returns void
language plpgsql volatile security definer set search_path = public, pg_temp as $$
begin
  if not public.is_admin() then raise exception 'admin_only' using errcode = '42501'; end if;
  update public.participants set name_hidden = p_name_hidden, disabled = p_disabled
   where id = p_participant_id;
end $$;

-- 管理画面用：非公開を含む全写真
create or replace function public.admin_list_photos(p_event text)
returns table (id uuid, thumb_path text, status text, created_at timestamptz,
               participant_id uuid, display_name text, name_hidden boolean, disabled boolean)
language plpgsql stable security definer set search_path = public, pg_temp as $$
begin
  if not public.is_admin() then raise exception 'admin_only' using errcode = '42501'; end if;
  return query
    select ph.id, ph.thumb_path, ph.status, ph.created_at, pa.id, pa.display_name, pa.name_hidden, pa.disabled
    from public.photos ph join public.participants pa on pa.id = ph.participant_id
    where ph.event_slug = p_event and ph.status <> 'pending'
    order by ph.created_at desc;
end $$;

-- ---------------------------------------------------------------------
-- 関数の実行権限：既定（全員実行可）を外し、必要なものだけ許す
-- ---------------------------------------------------------------------
revoke execute on all functions in schema public from public, anon, authenticated;

grant execute on function public.get_gallery(text)                 to anon, authenticated;
grant execute on function public.get_event_status(text)            to anon, authenticated;
grant execute on function public.redeem_invite(text, text, text, text)        to authenticated;
grant execute on function public.update_my_profile(text, text, text)          to authenticated;
grant execute on function public.is_admin()                                   to authenticated;
grant execute on function public.admin_set_invite_code(text, text)            to authenticated;
grant execute on function public.admin_disable_invite_code(text)              to authenticated;
grant execute on function public.admin_set_submission_open(text, boolean)     to authenticated;
grant execute on function public.admin_set_photo_hidden(uuid, boolean)        to authenticated;
grant execute on function public.admin_delete_photo(uuid)                     to authenticated;
grant execute on function public.admin_set_participant(uuid, boolean, boolean) to authenticated;
grant execute on function public.admin_list_photos(text)                      to authenticated;
-- 投稿の開始は「本人のログイン情報」で呼び、本人・締切・上限をDBが判定する。
-- 直接呼ばれても「保存待ち」の行ができるだけで、掲載（finish）はサーバーしかできない
grant execute on function public.begin_photo_upload(text, boolean, boolean, int, int, int, int, int) to authenticated;
grant execute on function public.finish_photo_upload(uuid) to service_role;
grant execute on function public.abort_photo_upload(uuid)  to service_role;

-- 今後この schema に作る関数も、既定では誰も実行できないようにする
alter default privileges in schema public revoke execute on functions from public, anon, authenticated;

-- ---------------------------------------------------------------------
-- ストレージ：公開バケット（読むのは誰でも・書くのは Edge Function だけ）
-- 参加者向けの insert/update/delete ポリシーは作らない ＝ 直接アップロード不可
-- ---------------------------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('gallery', 'gallery', true, 8388608, array['image/jpeg'])
on conflict (id) do nothing;

-- ---------------------------------------------------------------------
-- 伊豆大島（受付は閉じた状態で作る。合言葉の設定と受付開始は社長が行う）
-- ---------------------------------------------------------------------
insert into public.events (slug, title, submission_deadline)
values ('izu-oshima-2026', '伊豆大島 フォトウォーク', '2026-10-31T23:59:59+09:00')
on conflict (slug) do nothing;
