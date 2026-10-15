/* 投稿前に端末の中で写真を作り直す（サーバーに送る前に位置情報などを消す）
 *
 *  - 写真を画像として読み込み、キャンバスに描き直して JPEG に書き出す。
 *    描き直した画像には EXIF（位置情報・機種）などは一切含まれない。
 *  - 拡大用は長い辺 2048px、一覧用サムネイルは長い辺 640px に縮める（通信量の節約）。
 *  - 向き（縦横）は写真の情報どおりに直してから描く。
 * サーバー側でも同じ確認をもう一度行う（supabase/functions/_shared/jpeg.ts）。
 */
(function (global) {
  "use strict";

  const ORIGINAL_MAX_BYTES = 10 * 1024 * 1024;   // 元の写真は1枚10MBまで
  const ACCEPT = ["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", ""];

  class PrepError extends Error {
    constructor(code, message) { super(message); this.code = code; }
  }

  async function decode(file) {
    try {
      return await createImageBitmap(file, { imageOrientation: "from-image" });
    } catch {
      // 一部の端末向け：<img> 経由で読み込む
      const url = URL.createObjectURL(file);
      try {
        const img = new Image();
        img.decoding = "async";
        img.src = url;
        await img.decode();
        return img;
      } finally {
        setTimeout(() => URL.revokeObjectURL(url), 0);
      }
    }
  }

  function fit(w, h, maxSide) {
    const s = Math.min(1, maxSide / Math.max(w, h));
    return [Math.max(1, Math.round(w * s)), Math.max(1, Math.round(h * s))];
  }

  function render(src, sw, sh, w, h, quality) {
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";              // 透過PNGの透明部分は白に
    ctx.fillRect(0, 0, w, h);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(src, 0, 0, sw, sh, 0, 0, w, h);
    return new Promise((resolve, reject) =>
      canvas.toBlob((b) => (b ? resolve(b) : reject(new PrepError("encode_failed", "画像を書き出せませんでした"))), "image/jpeg", quality));
  }

  async function prepareImage(file) {
    if (!(file instanceof Blob)) throw new PrepError("no_file", "写真が選ばれていません");
    if (file.size > ORIGINAL_MAX_BYTES) throw new PrepError("too_large", "1枚10MBまでの写真を選んでください");
    if (!ACCEPT.includes(file.type) && !/\.(jpe?g|png|webp|heic|heif)$/i.test(file.name || "")) {
      throw new PrepError("bad_type", "JPEG・PNG・WebP・HEIC の写真を選んでください");
    }
    let src;
    try { src = await decode(file); } catch {
      throw new PrepError("decode_failed", "この写真は読み込めませんでした。JPEGに変換してからお試しください");
    }
    const sw = src.width || src.naturalWidth, sh = src.height || src.naturalHeight;
    if (!sw || !sh) throw new PrepError("decode_failed", "この写真は読み込めませんでした");

    const [w, h] = fit(sw, sh, 2048);
    const [tw, th] = fit(sw, sh, 640);
    const full = await render(src, sw, sh, w, h, 0.85);
    const thumb = await render(src, sw, sh, tw, th, 0.8);
    if (src.close) src.close();
    return { full, thumb, width: w, height: h, thumbWidth: tw, thumbHeight: th };
  }

  global.ImagePrep = { prepareImage, PrepError, ORIGINAL_MAX_BYTES };
})(window);
