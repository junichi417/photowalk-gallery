// ⚠ 自動生成ファイル（tools/bundle_functions.py）。直接編集しない。元は supabase/functions/
import { createClient } from "jsr:@supabase/supabase-js@2";

// ---- _shared/jpeg.ts ----
/**
 * JPEG の検査と「余計な情報」の除去（外部ライブラリなし）。
 *
 * 写真は投稿前に端末側で読み込み直して JPEG に作り直している（このとき位置情報などは消える）。
 * サーバーではそれを信用せず、もう一度ここで構造を1バイトずつ確かめ、次を行う。
 *  - JPEG として正しい形か（先頭・各区切り・長さ・終端）を確認。おかしければ拒否
 *  - EXIF（位置情報・撮影機材）、XMP、ICC、コメントなど、画素以外の情報をすべて取り除く
 *  - 終端（EOI）の後ろにくっつけられたデータ（別形式のファイルを隠す手口）を捨てる
 *  - 幅・高さの上限を確認
 * 出力は「画素データ＋表示に必要な最小限の情報」だけの JPEG。
 */

class JpegError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

type JpegLimits = { maxWidth: number; maxHeight: number; maxBytes: number };
type JpegResult = { width: number; height: number; components: number; progressive: boolean; bytes: Uint8Array };

// 残してよい区切り（marker）
const KEEP = new Set([
  0xc0, 0xc1, 0xc2, // SOF0 基本 / SOF1 拡張 / SOF2 プログレッシブ
  0xc4,             // DHT ハフマン表
  0xdb,             // DQT 量子化表
  0xdd,             // DRI リスタート間隔
]);
const SOF = new Set([0xc0, 0xc1, 0xc2]);
const UNSUPPORTED_SOF = new Set([0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf]);

function sanitizeJpeg(input: Uint8Array, limits: JpegLimits): JpegResult {
  const n = input.length;
  if (n > limits.maxBytes) throw new JpegError("too_large", `容量が上限（${limits.maxBytes}バイト）を超えています`);
  if (n < 4 || input[0] !== 0xff || input[1] !== 0xd8) throw new JpegError("not_jpeg", "JPEG画像ではありません");

  const out: Uint8Array[] = [new Uint8Array([0xff, 0xd8])];
  let i = 2;
  let width = 0, height = 0, components = 0, progressive = false;
  let sawSof = false, sawSos = false, sawEoi = false, keptApp0 = false;

  const u16 = (p: number) => {
    if (p + 1 >= n) throw new JpegError("truncated", "ファイルが途中で切れています");
    return (input[p] << 8) | input[p + 1];
  };

  while (i < n) {
    if (input[i] !== 0xff) throw new JpegError("corrupt", "JPEGの区切りが見つかりません");
    while (i < n && input[i] === 0xff) i++; // 詰め物の 0xFF を飛ばす
    if (i >= n) throw new JpegError("truncated", "ファイルが途中で切れています");
    const m = input[i++];

    if (m === 0xd9) { sawEoi = true; break; }                   // EOI：ここで終わり（後ろは捨てる）
    if (m === 0xd8 || m === 0x01 || (m >= 0xd0 && m <= 0xd7) || m === 0x00) {
      throw new JpegError("corrupt", "JPEGの区切りの並びが正しくありません");
    }

    const len = u16(i);
    if (len < 2 || i + len > n) throw new JpegError("truncated", "JPEGの区切りの長さが正しくありません");
    const seg = input.subarray(i - 2, i + len); // FF xx + 長さ + 中身
    const body = input.subarray(i + 2, i + len);
    i += len;

    if (UNSUPPORTED_SOF.has(m)) throw new JpegError("unsupported", "対応していないJPEG形式です");

    if (SOF.has(m)) {
      if (sawSof) throw new JpegError("corrupt", "画像の情報が重複しています");
      if (body.length < 6) throw new JpegError("corrupt", "画像の情報が不足しています");
      const precision = body[0];
      height = (body[1] << 8) | body[2];
      width = (body[3] << 8) | body[4];
      components = body[5];
      if (precision !== 8) throw new JpegError("unsupported", "対応していないJPEG形式です");
      if (components !== 1 && components !== 3) throw new JpegError("unsupported", "対応していない色の形式です（CMYKなど）");
      if (body.length !== 6 + components * 3) throw new JpegError("corrupt", "画像の情報が正しくありません");
      if (width < 1 || height < 1) throw new JpegError("corrupt", "画像の大きさが正しくありません");
      if (width > limits.maxWidth || height > limits.maxHeight) {
        throw new JpegError("too_big_dimensions", `画像が大きすぎます（${width}×${height}）`);
      }
      progressive = m === 0xc2;
      sawSof = true;
      out.push(seg);
      continue;
    }

    if (m === 0xe0) {
      // APP0：JFIF の見出しだけは残す（中のサムネイルは捨てて最小の形にする）
      const isJfif = body.length >= 14 && body[0] === 0x4a && body[1] === 0x46 && body[2] === 0x49 && body[3] === 0x46 && body[4] === 0;
      if (isJfif && !keptApp0 && !sawSof) {
        const jfif = new Uint8Array([0xff, 0xe0, 0x00, 0x10, ...body.subarray(0, 12), 0x00, 0x00]);
        out.push(jfif);
        keptApp0 = true;
      }
      continue;
    }
    if ((m >= 0xe1 && m <= 0xef) || m === 0xfe) continue; // EXIF・XMP・ICC・コメント等は捨てる

    if (m === 0xda) {
      // SOS：この後ろに圧縮された画素データが続く。次の区切りまで読み進める
      if (!sawSof) throw new JpegError("corrupt", "画像の情報より前に画素データがあります");
      sawSos = true;
      out.push(seg);
      const start = i;
      while (i < n) {
        if (input[i] !== 0xff) { i++; continue; }
        const next = input[i + 1];
        if (next === 0x00 || (next >= 0xd0 && next <= 0xd7)) { i += 2; continue; } // 埋め込み・リスタート
        if (next === 0xff) { i++; continue; }
        break; // 本当の区切り
      }
      if (i >= n) throw new JpegError("truncated", "画素データが途中で切れています");
      out.push(input.subarray(start, i));
      continue;
    }

    if (KEEP.has(m)) { out.push(seg); continue; }
    throw new JpegError("unsupported", `想定外のJPEGの区切りがあります（0x${m.toString(16)}）`);
  }

  if (!sawSof || !sawSos || !sawEoi) throw new JpegError("truncated", "JPEGが完結していません");
  out.push(new Uint8Array([0xff, 0xd9]));

  const total = out.reduce((s, a) => s + a.length, 0);
  const bytes = new Uint8Array(total);
  let p = 0;
  for (const a of out) { bytes.set(a, p); p += a.length; }
  return { width, height, components, progressive, bytes };
}

// ---- _shared/upload_handler.ts ----
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

const LIMITS = {
  requestBytes: 6 * 1024 * 1024,
  full: { maxWidth: 2048, maxHeight: 2048, maxBytes: 4 * 1024 * 1024 },
  thumb: { maxWidth: 640, maxHeight: 640, maxBytes: 400 * 1024 },
};

type UploadDeps = {
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

function createUploadHandler(deps: UploadDeps) {
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

// ---- upload-photo/index.ts ----
// 写真の投稿を受け付ける Edge Function（Supabase 上で動く）
// 必要な設定（Supabase の管理画面 → Edge Functions → Secrets）：
//   ALLOWED_ORIGINS = ギャラリーのURL（例 https://junichi417.github.io）。複数ならカンマ区切り
// SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY は Supabase が自動で渡す

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
