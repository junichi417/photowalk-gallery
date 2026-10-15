// 投稿処理（Edge Function の本体）と画像検査のテスト
// 実行：python3 tests/functions/make_fixtures.py <dir> のあと
//       FIXTURES=<dir> node --experimental-strip-types --test tests/functions/upload.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { sanitizeJpeg, JpegError } from "../../supabase/functions/_shared/jpeg.ts";
import { createUploadHandler, LIMITS, type UploadDeps } from "../../supabase/functions/_shared/upload_handler.ts";

const FX = process.env.FIXTURES!;
const fx = (name: string) => new Uint8Array(readFileSync(join(FX, name)));
const big = { maxWidth: 4096, maxHeight: 4096, maxBytes: 20 * 1024 * 1024 };

// 出力を Pillow で開き直して、画素が読めること・メタデータが無いことを確かめる
function inspect(bytes: Uint8Array) {
  const dir = mkdtempSync(join(tmpdir(), "jpeg-"));
  const f = join(dir, "x.jpg");
  writeFileSync(f, bytes);
  const py = `
import json,sys
from PIL import Image
im=Image.open(sys.argv[1]); im.load()
ex=im.getexif()
print(json.dumps({"size":im.size,"exif":len(ex),"gps":len(ex.get_ifd(0x8825)),
  "icc":"icc_profile" in im.info,"comment":"comment" in im.info,"xmp":"xmp" in im.info}))`;
  return JSON.parse(execFileSync("python3", ["-c", py, f]).toString());
}

// ---------------------------------------------------------------- 画像検査
test("位置情報(GPS)・機種・ICC・コメントつきの写真 → 全部消えて、画像は読める", () => {
  const before = inspect(fx("gps.jpg"));
  assert.ok(before.gps > 0 && before.icc && before.comment, "元の写真に情報が入っていること");
  const r = sanitizeJpeg(fx("gps.jpg"), big);
  const after = inspect(r.bytes);
  assert.deepEqual(after.size, [1600, 1067]);
  assert.equal(after.exif, 0);
  assert.equal(after.gps, 0);
  assert.equal(after.icc, false);
  assert.equal(after.comment, false);
  assert.ok(!Buffer.from(r.bytes).includes("TestCamera"), "機種名の文字列も残らない");
});

test("プログレッシブJPEGも受け付け、メタデータを消す", () => {
  const r = sanitizeJpeg(fx("prog.jpg"), big);
  assert.equal(r.progressive, true);
  assert.equal(inspect(r.bytes).gps, 0);
});

test("白黒の写真は受け付ける", () => {
  assert.equal(sanitizeJpeg(fx("gray.jpg"), big).components, 1);
});

test("末尾に別のデータ（zip/HTML）を隠したファイル → 隠しデータを捨てる", () => {
  const r = sanitizeJpeg(fx("trailing.jpg"), big);
  const s = Buffer.from(r.bytes);
  assert.ok(!s.includes("PK\x03\x04") && !s.includes("<script>"));
  assert.equal(r.bytes[r.bytes.length - 2], 0xff);
  assert.equal(r.bytes[r.bytes.length - 1], 0xd9);
  assert.deepEqual(inspect(r.bytes).size, [1600, 1067]);
});

for (const [name, code] of [
  ["photo.png", "not_jpeg"], ["fake.jpg", "corrupt"], ["truncated.jpg", "truncated"],
  ["cmyk.jpg", "unsupported"],
] as const) {
  test(`拒否：${name}（${code}）`, () => {
    assert.throws(() => sanitizeJpeg(fx(name), big), (e: unknown) => e instanceof JpegError && e.code === code);
  });
}

test("拒否：縦横が上限（2048px）を超える", () => {
  assert.throws(() => sanitizeJpeg(fx("huge_dims.jpg"), LIMITS.full), (e: unknown) => e instanceof JpegError && e.code === "too_big_dimensions");
});

test("拒否：容量が上限を超える", () => {
  assert.throws(() => sanitizeJpeg(fx("gps.jpg"), { ...big, maxBytes: 1000 }), (e: unknown) => e instanceof JpegError && e.code === "too_large");
});

test("壊れたデータを大量に入れても、例外（拒否）になるだけで止まらない", () => {
  const src = fx("gps.jpg");
  let seed = 1;
  const rnd = () => (seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31;
  for (let k = 0; k < 300; k++) {
    const b = new Uint8Array(src);
    for (let j = 0; j < 20; j++) b[Math.floor(rnd() * b.length)] = Math.floor(rnd() * 256);
    try { sanitizeJpeg(b, big); } catch (e) { assert.ok(e instanceof JpegError, String(e)); }
  }
});

// ---------------------------------------------------------------- 投稿処理
const ORIGIN = "https://junichi417.github.io";
const TOKEN = "Bearer eyJhbGciOi.payload.sig";

function fakeDeps(over: Partial<UploadDeps> = {}) {
  const log: string[] = [];
  const stored = new Map<string, Uint8Array>();
  const deps: UploadDeps = {
    allowedOrigins: [ORIGIN],
    getUser: async (h) => (h === TOKEN ? { id: "user-1" } : null),
    beginUpload: async (_h, a) => { log.push(`begin:${a.width}x${a.height}`); return { photo_id: "p1", full_path: "ev/p1.jpg", thumb_path: "ev/p1_t.jpg" }; },
    putObject: async (p, b) => { log.push(`put:${p}`); stored.set(p, b); },
    removeObjects: async (ps) => { log.push(`remove:${ps.join(",")}`); },
    finishUpload: async (id) => { log.push(`finish:${id}`); },
    abortUpload: async (id) => { log.push(`abort:${id}`); },
    ...over,
  };
  return { deps, log, stored };
}

function form(fields: Record<string, string>, files: Record<string, Uint8Array | null> = { full: fx("gps.jpg"), thumb: fx("thumb.jpg") }) {
  const f = new FormData();
  for (const [k, v] of Object.entries(fields)) f.set(k, v);
  for (const [k, v] of Object.entries(files)) if (v) f.set(k, new File([v], `${k}.jpg`, { type: "image/jpeg" }));
  return f;
}
const okFields = { event: "izu-oshima-2026", consent_own_photo: "true", consent_people: "true" };
const req = (body: FormData | null, headers: Record<string, string> = { authorization: TOKEN, origin: ORIGIN }) =>
  new Request("https://x.supabase.co/functions/v1/upload-photo", { method: "POST", headers, body: body ?? undefined });

test("正しい参加者の投稿 → 保存して掲載。保存されたファイルに位置情報は無い", async () => {
  const { deps, log, stored } = fakeDeps();
  const res = await createUploadHandler(deps)(req(form(okFields)));
  assert.equal(res.status, 201);
  assert.deepEqual(log, ["begin:1600x1067", "put:ev/p1.jpg", "put:ev/p1_t.jpg", "finish:p1"]);
  assert.equal(inspect(stored.get("ev/p1.jpg")!).gps, 0);
  assert.equal(res.headers.get("access-control-allow-origin"), ORIGIN);
});

test("ログインしていない → 401、DBにもストレージにも触らない", async () => {
  const { deps, log } = fakeDeps();
  const res = await createUploadHandler(deps)(req(form(okFields), { origin: ORIGIN }));
  assert.equal(res.status, 401);
  assert.deepEqual(log, []);
});

test("偽のログイン情報 → 401", async () => {
  const { deps, log } = fakeDeps();
  const res = await createUploadHandler(deps)(req(form(okFields), { authorization: "Bearer forged.token.x", origin: ORIGIN }));
  assert.equal(res.status, 401);
  assert.deepEqual(log, []);
});

test("許可していないサイトからの投稿 → 403", async () => {
  const { deps, log } = fakeDeps();
  const res = await createUploadHandler(deps)(req(form(okFields), { authorization: TOKEN, origin: "https://evil.example" }));
  assert.equal(res.status, 403);
  assert.deepEqual(log, []);
});

test("同意チェックが無い → 400、DBに触らない", async () => {
  const { deps, log } = fakeDeps();
  const res = await createUploadHandler(deps)(req(form({ ...okFields, consent_people: "false" })));
  assert.equal(res.status, 400);
  assert.deepEqual(log, []);
});

test("PNGや偽装ファイル → 400、DBに触らない", async () => {
  for (const bad of ["photo.png", "fake.jpg", "truncated.jpg"]) {
    const { deps, log } = fakeDeps();
    const res = await createUploadHandler(deps)(req(form(okFields, { full: fx(bad), thumb: fx("thumb.jpg") })));
    assert.equal(res.status, 400, bad);
    assert.deepEqual(log, [], bad);
  }
});

test("サムネイルが別の画像（縦横比が違う）→ 400", async () => {
  const { deps } = fakeDeps();
  const res = await createUploadHandler(deps)(req(form(okFields, { full: fx("gps.jpg"), thumb: fx("thumb_mismatch.jpg") })));
  assert.equal(res.status, 400);
});

test("DBが「締切」と判定 → 403「写真の受付は終了しました」、保存しない", async () => {
  const { deps, log } = fakeDeps({ beginUpload: async () => { throw new Error("submission_closed"); } });
  const res = await createUploadHandler(deps)(req(form(okFields)));
  assert.equal(res.status, 403);
  assert.equal((await res.json()).message, "写真の受付は終了しました");
  assert.deepEqual(log, []);
});

test("DBが「参加者でない」と判定（第三者）→ 403、保存しない", async () => {
  const { deps, log } = fakeDeps({ beginUpload: async () => { throw new Error("not_participant"); } });
  const res = await createUploadHandler(deps)(req(form(okFields)));
  assert.equal(res.status, 403);
  assert.deepEqual(log, []);
});

test("保存の途中で失敗 → 保存済みファイルを消し、行も取り消す（中途半端な掲載を残さない）", async () => {
  let n = 0;
  const { deps, log } = fakeDeps({
    putObject: async (p) => { if (++n === 2) throw new Error("storage down"); log.push(`put:${p}`); },
  });
  const res = await createUploadHandler(deps)(req(form(okFields)));
  assert.equal(res.status, 500);
  assert.deepEqual(log, ["begin:1600x1067", "put:ev/p1.jpg", "remove:ev/p1.jpg", "abort:p1"]);
});

test("GET など POST 以外 → 405", async () => {
  const { deps } = fakeDeps();
  const res = await createUploadHandler(deps)(new Request("https://x/f", { method: "GET", headers: { origin: ORIGIN } }));
  assert.equal(res.status, 405);
});
