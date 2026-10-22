// ⚠ 自動生成ファイル（tools/bundle_functions.py）。直接編集しない。元は supabase/functions/
// 参加者が「自分の写真」を取り消す Edge Function
// 自分の写真かどうか・受付中かどうかは DB（delete_my_photo）が本人のログイン情報で判定する。
// 条件を満たさなければ DB が拒否し、ファイルには一切触らない。
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
  if (!/^Bearer \S+/.test(auth)) return reply(401, { error: "not_authenticated" });
  const { photo_id } = await req.json().catch(() => ({}));
  if (!/^[0-9a-f-]{36}$/.test(String(photo_id ?? ""))) return reply(400, { error: "bad_request" });

  const asUser = createClient(URL_, ANON, { global: { headers: { Authorization: auth } }, auth: { persistSession: false } });
  const { data, error } = await asUser.rpc("delete_my_photo", { p_photo_id: photo_id });
  if (error) {
    const m = error.message;
    if (/not_authenticated|permission denied/i.test(m)) return reply(401, { error: "not_authenticated", message: "ログインし直してください" });
    if (/photo_not_found/.test(m)) return reply(404, { error: "photo_not_found", message: "この写真は取り消せません（すでに取り消した、または運営が管理している写真です）" });
    if (/submission_closed/.test(m)) return reply(403, { error: "submission_closed", message: "いまは写真を取り消せません（受付が終了している、または止まっています）" });
    console.error("delete_my_photo failed:", m);
    return reply(500, { error: "internal_error", message: "取り消せませんでした。時間をおいてお試しください" });
  }

  const paths = (data ?? []).flatMap((r: { full_path: string; thumb_path: string }) => [r.full_path, r.thumb_path]);
  if (paths.length) {
    const { error: e2 } = await server.storage.from("gallery").remove(paths);
    if (e2) {
      console.error("storage_remove_failed:", paths);
      return reply(500, { error: "storage_remove_failed", message: "取り消しの途中で問題が起きました。運営にお知らせください" });
    }
  }
  return reply(200, { deleted: paths.length > 0 });
});
