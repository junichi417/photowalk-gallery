/**
 * 写真の投稿を受け付ける処理（本体）。Supabase との通信は deps で差し替えられるので、
 * ここだけを手元でテストできる（tests/functions/）。
 *
 * 流れ
 *  1. ログイン確認（本人のJWT）
 *  2. 入力の確認（イベント名・同意2つ・写真2枚＝拡大用とサムネイル）
 *  3. 画像の検査とメタデータ除去（_shared/jpeg.ts）
 *  4. DB で「本人・参加者・締切・枚数」を判定して保存先を受け取る（本人として呼ぶ）
 *  5. ストレージに保存（サーバー権限）→ 掲載（サーバー権限）
 *     途中で失敗したら、保存したファイルと行を取り消す
 */
import { JpegError, sanitizeJpeg } from "./jpeg.ts";

export const LIMITS = {
  requestBytes: 6 * 1024 * 1024,
  full: { maxWidth: 2048, maxHeight: 2048, maxBytes: 4 * 1024 * 1024 },
  thumb: { maxWidth: 640, maxHeight: 640, maxBytes: 400 * 1024 },
};

export type UploadDeps = {
  allowedOrigins: string[];
  getUser(authHeader: string): Promise<{ id: string } | null>;
  beginUpload(authHeader: string, args: {
    event: string; consentOwn: boolean; consentPeople: boolean;
    width: number; height: number; thumbWidth: number; thumbHeight: number; bytes: number;
  }): Promise<{ photo_id: string; full_path: string; thumb_path: string }>;
  putObject(path: string, bytes: Uint8Array): Promise<void>;
  removeObjects(paths: string[]): Promise<void>;
  finishUpload(photoId: string): Promise<void>;
  abortUpload(photoId: string): Promise<void>;
};

// DB からのエラーを、画面に出す言葉に変える
const DB_ERRORS: Record<string, [number, string]> = {
  submission_closed: [403, "写真の受付は終了しました"],
  not_participant: [403, "参加登録がまだです。合言葉を入力してください"],
  consent_required: [400, "投稿前の確認2つにチェックしてください"],
  photo_limit_reached: [409, "投稿できる枚数の上限に達しました"],
  not_authenticated: [401, "ログインし直してください"],
};

function corsHeaders(origin: string | null, allowed: string[]): Record<string, string> {
  const h: Record<string, string> = {
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
  };
  if (origin && allowed.includes(origin)) h["Access-Control-Allow-Origin"] = origin;
  return h;
}

export function createUploadHandler(deps: UploadDeps) {
  return async (req: Request): Promise<Response> => {
    const origin = req.headers.get("origin");
    const cors = corsHeaders(origin, deps.allowedOrigins);
    const reply = (status: number, body: Record<string, unknown>) =>
      new Response(JSON.stringify(body), { status, headers: { ...cors, "content-type": "application/json; charset=utf-8" } });
    const fail = (status: number, code: string, message: string) => reply(status, { error: code, message });

    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (req.method !== "POST") return fail(405, "method_not_allowed", "POSTのみ受け付けます");
    if (origin && !deps.allowedOrigins.includes(origin)) return fail(403, "origin_not_allowed", "このページからは投稿できません");

    const auth = req.headers.get("authorization") ?? "";
    if (!/^Bearer [A-Za-z0-9._-]+$/.test(auth)) return fail(401, "not_authenticated", "ログインしてください");
    const user = await deps.getUser(auth).catch(() => null);
    if (!user) return fail(401, "not_authenticated", "ログインし直してください");

    const declared = Number(req.headers.get("content-length") ?? "0");
    if (declared > LIMITS.requestBytes) return fail(413, "too_large", "送信できる容量を超えています");

    let form: FormData;
    try { form = await req.formData(); } catch { return fail(400, "bad_request", "送信内容を読み取れませんでした"); }

    const event = String(form.get("event") ?? "");
    if (!/^[a-z0-9-]{1,64}$/.test(event)) return fail(400, "bad_request", "イベントの指定が正しくありません");
    const consentOwn = form.get("consent_own_photo") === "true";
    const consentPeople = form.get("consent_people") === "true";
    if (!consentOwn || !consentPeople) return fail(400, "consent_required", DB_ERRORS.consent_required[1]);

    const full = form.get("full");
    const thumb = form.get("thumb");
    if (!(full instanceof File) || !(thumb instanceof File)) return fail(400, "bad_request", "写真が添付されていません");
    if (full.size + thumb.size > LIMITS.requestBytes) return fail(413, "too_large", "送信できる容量を超えています");

    let fullImg, thumbImg;
    try {
      fullImg = sanitizeJpeg(new Uint8Array(await full.arrayBuffer()), LIMITS.full);
      thumbImg = sanitizeJpeg(new Uint8Array(await thumb.arrayBuffer()), LIMITS.thumb);
    } catch (e) {
      if (e instanceof JpegError) return fail(400, `invalid_image:${e.code}`, `画像を確認できませんでした：${e.message}`);
      throw e;
    }
    // サムネイルが別の画像でないか（縦横比が大きくずれていないか）
    const r1 = fullImg.width / fullImg.height, r2 = thumbImg.width / thumbImg.height;
    if (Math.abs(r1 - r2) / r1 > 0.03) return fail(400, "invalid_image:mismatch", "画像を確認できませんでした：サムネイルが一致しません");

    let slot;
    try {
      slot = await deps.beginUpload(auth, {
        event, consentOwn, consentPeople,
        width: fullImg.width, height: fullImg.height,
        thumbWidth: thumbImg.width, thumbHeight: thumbImg.height,
        bytes: fullImg.bytes.length,
      });
    } catch (e) {
      const code = Object.keys(DB_ERRORS).find((k) => String((e as Error)?.message ?? "").includes(k));
      if (code) return fail(DB_ERRORS[code][0], code, DB_ERRORS[code][1]);
      return fail(500, "server_error", "投稿を受け付けられませんでした。時間をおいてもう一度お試しください");
    }

    const saved: string[] = [];
    try {
      await deps.putObject(slot.full_path, fullImg.bytes); saved.push(slot.full_path);
      await deps.putObject(slot.thumb_path, thumbImg.bytes); saved.push(slot.thumb_path);
      await deps.finishUpload(slot.photo_id);
    } catch {
      await deps.removeObjects(saved).catch(() => {});
      await deps.abortUpload(slot.photo_id).catch(() => {});
      return fail(500, "server_error", "写真を保存できませんでした。もう一度お試しください");
    }

    return reply(201, {
      id: slot.photo_id, full_path: slot.full_path, thumb_path: slot.thumb_path,
      width: fullImg.width, height: fullImg.height,
    });
  };
}
