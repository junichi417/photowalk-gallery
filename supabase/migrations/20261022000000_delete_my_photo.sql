-- 参加者が自分の写真を取り消せる（2026-10-22 追加・既存の表と関数は変えない）
--  ・取り消せるのは「自分の」「掲載中(published)」の写真だけ（運営が非公開にした写真は対象外）
--  ・受付中(スイッチON かつ 締切前)だけ。締切後は削除しない（運営だけが消せる）
--  ・返すのは消すべきファイルの場所。ファイルの削除は Edge Function(delete-my-photo)が行う
create or replace function public.delete_my_photo(p_photo_id uuid)
returns table (full_path text, thumb_path text)
language plpgsql volatile security definer set search_path = public, pg_temp as $$
declare
  v_event text;
begin
  if auth.uid() is null then raise exception 'not_authenticated' using errcode = '28000'; end if;

  select p.event_slug into v_event
    from public.photos p
    join public.participants pt on pt.id = p.participant_id
   where p.id = p_photo_id and pt.user_id = auth.uid() and p.status = 'published';
  if v_event is null then raise exception 'photo_not_found' using errcode = 'P0001'; end if;

  if not public._accepting(v_event) then raise exception 'submission_closed' using errcode = 'P0001'; end if;

  return query delete from public.photos where id = p_photo_id
    returning photos.full_path, photos.thumb_path;
end $$;

revoke execute on function public.delete_my_photo(uuid) from public, anon;
grant  execute on function public.delete_my_photo(uuid) to authenticated;
