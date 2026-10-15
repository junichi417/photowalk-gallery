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

export class JpegError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

export type JpegLimits = { maxWidth: number; maxHeight: number; maxBytes: number };
export type JpegResult = { width: number; height: number; components: number; progressive: boolean; bytes: Uint8Array };

// 残してよい区切り（marker）
const KEEP = new Set([
  0xc0, 0xc1, 0xc2, // SOF0 基本 / SOF1 拡張 / SOF2 プログレッシブ
  0xc4,             // DHT ハフマン表
  0xdb,             // DQT 量子化表
  0xdd,             // DRI リスタート間隔
]);
const SOF = new Set([0xc0, 0xc1, 0xc2]);
const UNSUPPORTED_SOF = new Set([0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf]);

export function sanitizeJpeg(input: Uint8Array, limits: JpegLimits): JpegResult {
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
