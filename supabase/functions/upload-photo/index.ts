// 写真の投稿を受け付ける Edge Function（Supabase 上で動く）
// 必要な設定（Supabase の管理画面 → Edge Functions → Secrets）：
//   ALLOWED_ORIGINS = ギャラリーのURL（例 https://junichi417.github.io）。複数ならカンマ区切り
// SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY は Supabase が自動で渡す
import { createClient } from "jsr:@supabase/supabase-js@2";
import { createUploadHandler } from "../_shared/upload_handler.ts";

const URL_ = Deno.env.get("SUPABASE_URL")!;
const ANON = Deno.env.get("SUPABASE_ANON_KEY")!;
const SERVICE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const BUCKET = "gallery";

const server = createClient(URL_, SERVICE, { auth: { persistSession: false } });
const asUser = (authHeader: string) =>
  createClient(URL_, ANON, { global: { headers: { Authorization: authHeader } }, auth: { persistSession: false } });

Deno.serve(createUploadHandler({
  allowedOrigins: (Deno.env.get("ALLOWED_ORIGINS") ?? "").split(",").map((s) => s.trim()).filter(Boolean),

  async getUser(authHeader) {
    const { data, error } = await asUser(authHeader).auth.getUser();
    return error || !data.user ? null : { id: data.user.id };
  },

  async beginUpload(authHeader, a) {
    const { data, error } = await asUser(authHeader).rpc("begin_photo_upload", {
      p_event: a.event, p_consent_own_photo: a.consentOwn, p_consent_people: a.consentPeople,
      p_width: a.width, p_height: a.height, p_thumb_width: a.thumbWidth, p_thumb_height: a.thumbHeight,
      p_bytes: a.bytes,
    }).single();
    if (error) throw new Error(error.message);
    return data as { photo_id: string; full_path: string; thumb_path: string };
  },

  async putObject(path, bytes) {
    const { error } = await server.storage.from(BUCKET).upload(path, bytes, {
      contentType: "image/jpeg", upsert: false, cacheControl: "3600",
    });
    if (error) throw new Error(error.message);
  },

  async removeObjects(paths) {
    if (paths.length) await server.storage.from(BUCKET).remove(paths);
  },

  async finishUpload(photoId) {
    const { error } = await server.rpc("finish_photo_upload", { p_photo_id: photoId });
    if (error) throw new Error(error.message);
  },

  async abortUpload(photoId) {
    await server.rpc("abort_photo_upload", { p_photo_id: photoId });
  },
}));
