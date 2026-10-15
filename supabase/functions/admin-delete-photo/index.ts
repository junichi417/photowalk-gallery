// 管理者（社長）が写真を完全に削除する Edge Function
// 管理者かどうかは DB（admin_delete_photo）が本人のログイン情報で判定する。
// 管理者でなければ DB が拒否し、ファイルには一切触らない。
import { createClient } from "jsr:@supabase/supabase-js@2";

const URL_ = Deno.env.get("SUPABASE_URL")!;
const ANON = Deno.env.get("SUPABASE_ANON_KEY")!;
const SERVICE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const ALLOWED = (Deno.env.get("ALLOWED_ORIGINS") ?? "").split(",").map((s) => s.trim()).filter(Boolean);
const server = createClient(URL_, SERVICE, { auth: { persistSession: false } });

Deno.serve(async (req) => {
  const origin = req.headers.get("origin");
  const cors: Record<string, string> = {
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
    "Access-Control-Allow-Methods": "POST, OPTIONS", "Vary": "Origin",
  };
  if (origin && ALLOWED.includes(origin)) cors["Access-Control-Allow-Origin"] = origin;
  const reply = (status: number, body: unknown) =>
    new Response(JSON.stringify(body), { status, headers: { ...cors, "content-type": "application/json; charset=utf-8" } });

  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
  if (req.method !== "POST") return reply(405, { error: "method_not_allowed" });

  const auth = req.headers.get("authorization") ?? "";
  const { photo_id } = await req.json().catch(() => ({}));
  if (!/^[0-9a-f-]{36}$/.test(String(photo_id ?? ""))) return reply(400, { error: "bad_request" });

  const asUser = createClient(URL_, ANON, { global: { headers: { Authorization: auth } }, auth: { persistSession: false } });
  const { data, error } = await asUser.rpc("admin_delete_photo", { p_photo_id: photo_id });
  if (error) return reply(error.message.includes("admin_only") ? 403 : 500, { error: error.message });

  const paths = (data ?? []).flatMap((r: { full_path: string; thumb_path: string }) => [r.full_path, r.thumb_path]);
  if (paths.length) {
    const { error: e2 } = await server.storage.from("gallery").remove(paths);
    if (e2) return reply(500, { error: "storage_remove_failed", paths });
  }
  return reply(200, { deleted: paths.length > 0 });
});
